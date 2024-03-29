# -*- coding: utf-8 -*-
#########################################################
# python
import os, sys, traceback, re, json, threading, time, shutil
from datetime import datetime
# third-party
import requests
# third-party
from flask import request, render_template, jsonify, redirect, Response, send_file
from sqlalchemy import or_, and_, func, not_, desc
import lxml.html
from lxml import etree as ET


# sjva 공용
from framework import db, scheduler, path_data, socketio, SystemModelSetting, app, py_urllib
from framework.util import Util
from framework.common.util import headers
from plugin import LogicModuleBase, default_route_socketio
from support.site.tving import SupportTving
# 패키지
from lib_metadata import SiteDaumTv, SiteTmdbTv, SiteTvingTv, SiteWavveTv, SiteUtil

from .plugin import P
logger = P.logger
package_name = P.package_name
ModelSetting = P.ModelSetting

from lib_metadata.server_util import MetadataServerUtil
#########################################################

class LogicKtv(LogicModuleBase):
    db_default = {
        'ktv_db_version' : '1',
        'ktv_use_kakaotv' : 'True',
        'ktv_use_kakaotv_episode' : 'False',
        'ktv_episode_info_order' : 'daum, tving, wavve',
        'ktv_use_theme' : 'True',

        'ktv_total_test_search' : '',
        'ktv_daum_test_search' : '',
        'ktv_daum_test_episode' : '',
        'ktv_wavve_test_search' : '',
        'ktv_wavve_test_info' : '',
        'ktv_tving_test_search' : '',
        'ktv_tving_test_info' : '',
        'ktv_use_tmdb' : 'True',
        'ktv_total_test_info' : '',
        'ktv_change_actor_name_rule' : '',
        # Daum 에피소드 줄거리에서 날짜, 제목 제거.
        'ktv_summary_duplicate_remove' : 'False',
    }

    module_map = {'daum':SiteDaumTv, 'tving':SiteTvingTv, 'wavve':SiteWavveTv, 'tmdb':SiteTmdbTv}

    def __init__(self, P):
        super(LogicKtv, self).__init__(P, 'setting')
        self.name = 'ktv'

    def process_menu(self, sub, req):
        arg = P.ModelSetting.to_dict()
        arg['sub'] = self.name

        try:
            return render_template('{package_name}_{module_name}_{sub}.html'.format(package_name=P.package_name, module_name=self.name, sub=sub), arg=arg)
        except:
            return render_template('sample.html', title='%s - %s' % (P.package_name, sub))

    def process_ajax(self, sub, req):
        try:
            if sub == 'test':
                keyword = req.form['keyword'].strip()
                call = req.form['call']
                mode = req.form['mode']
                ModelSetting.set('ktv_%s_test_%s' % (call, mode), keyword)

                if call == 'total':
                    ret = {}
                    if mode == 'search':
                        manual = (req.form['manual'] == 'manual')
                        ret['search'] = self.search(keyword, manual=manual)
                        if 'daum' in ret['search']:
                            ret['info'] = self.info(ret['search']['daum']['code'], ret['search']['daum']['title'])
                        elif 'tving' in ret['search']:
                            ret['info'] = self.info(ret['search']['tving'][0]['code'], '')
                        elif 'wavve' in ret['search']:
                            ret['info'] = self.info(ret['search']['wavve'][0]['code'], '')
                    elif mode == 'info':
                        code = keyword
                        title = ''
                        tmps = keyword.split('|')
                        if len(tmps) == 2:
                            code = tmps[0]
                            title = tmps[1]
                        
                        ret['info'] = self.info(code, title)
                    
                elif call == 'daum':
                    if mode == 'search':
                        ret = {}
                        ret['search'] = SiteDaumTv.search(keyword)
                        if ret['search']['ret'] == 'success':
                            ret['info'] = self.info(ret['search']['data']['code'], ret['search']['data']['title'])
                    elif mode == 'episode':
                        ret = {}
                        ret['episode'] = self.episode_info(keyword)
                elif call == 'wavve':
                    import  framework.wavve.api as Wavve
                    if mode == 'search':
                        ret = Wavve.search_tv(keyword)
                    elif mode == 'info':
                        ret = {}
                        ret['program'] = Wavve.vod_programs_programid(keyword)
                        ret['episodes'] = []
                        page = 1
                        while True:
                            episode_data = Wavve.vod_program_contents_programid(keyword, page=page)
                            ret['episodes'] += episode_data['list']
                            page += 1
                            if episode_data['pagecount'] == episode_data['count']:# or page == 6:
                                break
                elif call == 'tving':
                    if mode == 'search':
                        ret = SupportTving.ins.search(keyword)
                    elif mode == 'info':
                        ret = {}
                        ret['program'] = SupportTving.ins.get_program_programid(keyword)
                        ret['episodes'] = []
                        page = 1
                        while True:
                            episode_data = SupportTving.ins.get_frequency_programid(keyword, page=page)
                            for epi in episode_data['result']:
                                ret['episodes'].append(epi['episode'])
                            page += 1
                            if episode_data['has_more'] == 'N':
                                break
                return jsonify(ret)
        except Exception as e: 
            P.logger.error('Exception:%s', e)
            P.logger.error(traceback.format_exc())
            return jsonify({'ret':'exception', 'log':str(e)})
        


    def process_api(self, sub, req):
        if sub == 'search':
            call = req.args.get('call')
            manual = bool(req.args.get('manual'))
            if call == 'plex' or call == 'kodi':
                return jsonify(self.search(req.args.get('keyword'), manual=manual))
        elif sub == 'info':
            call = req.args.get('call')
            data = self.info(req.args.get('code'), req.args.get('title'))
            if call == 'kodi':
                data = SiteUtil.info_to_kodi(data)
            return jsonify(data)
        elif sub == 'episode_info':
            return jsonify(self.episode_info(req.args.get('code')))
            #return jsonify(self.episode_info(req.args.get('code'), req.args.get('no'), req.args.get('premiered'), req.args.get('param')))
            #return jsonify(self.episode_info(req.args.get('code'), req.args.get('no'), py_urllib.unquote(req.args.get('param'))))

    #########################################################

    def search(self, keyword, manual=False):
        ret = {}
        #site_list = ModelSetting.get_list('jav_censored_order', ',')
        site_list = ['daum', 'tving', 'wavve']
        for idx, site in enumerate(site_list):
            logger.debug(site)
            site_data = self.module_map[site].search(keyword)
            #logger.debug(data)

            if site_data['ret'] == 'success':
                ret[site] = site_data['data']
                logger.info(u'KTV 검색어 : %s site : %s 매칭', keyword, site)
                if manual:
                    continue
                return ret
        return ret

    def info(self, code, title):
        try:
            show = None
            if code[1] == 'D':
                tmp = SiteDaumTv.info(code, title)
                if tmp['ret'] == 'success':
                    show = tmp['data']

                if 'kakao_id' in show['extra_info'] and show['extra_info']['kakao_id'] is not None and ModelSetting.get_bool('ktv_use_kakaotv'):
                    show['extras'] = SiteDaumTv.get_kakao_video(show['extra_info']['kakao_id'])

                if ModelSetting.get_bool('ktv_use_tmdb'):
                    from lib_metadata import SiteTmdbTv
                    tmdb_id = SiteTmdbTv.search_tv(show['title'], show['premiered'])
                    show['extra_info']['tmdb_id'] = tmdb_id
                    if tmdb_id is not None:
                        show['tmdb'] = {}
                        show['tmdb']['tmdb_id'] = tmdb_id
                        SiteTmdbTv.apply(tmdb_id, show, apply_image=True, apply_actor_image=True)

                if 'tving_episode_id' in show['extra_info']:
                    SiteTvingTv.apply_tv_by_episode_code(show, show['extra_info']['tving_episode_id'], apply_plot=True, apply_image=True )
                else: #use_tving 정도
                    SiteTvingTv.apply_tv_by_search(show, apply_plot=True, apply_image=True)

                SiteWavveTv.apply_tv_by_search(show)
                #extra
                if ModelSetting.get_bool('ktv_use_theme'):
                    extra = MetadataServerUtil.get_meta_extra(code)
                    if extra is not None:
                        if 'themes' in extra:
                            show['extra_info']['themes'] = extra['themes']

            elif code[1] == 'V': 
                tmp = SiteTvingTv.info(code)
                if tmp['ret'] == 'success':
                    show = tmp['data']
            elif code[1] == 'W': 
                tmp = SiteWavveTv.info(code)
                if tmp['ret'] == 'success':
                    show = tmp['data']

            logger.info('KTV info title:%s code:%s tving:%s wavve:%s', title, code, show['extra_info']['tving_id'] if 'tving_id' in show['extra_info'] else None, show['extra_info']['wavve_id'] if 'wavve_id' in show['extra_info'] else None)

            if show is not None:
                show['ktv_episode_info_order'] = ModelSetting.get_list('ktv_episode_info_order', ',')

                try:
                    rules = ModelSetting.get_list('ktv_change_actor_name_rule', '\n')
                    for rule in rules:
                        tmps = rule.split('|')
                        if len(tmps) != 3:
                            continue
                        if tmps[0] == show['title']:
                            for actor in show['actor']:
                                if actor['name'] == tmps[1]:
                                    actor['name'] = tmps[2]
                                    break
                except Exception as e: 
                    P.logger.error('Exception:%s', e)
                    P.logger.error(traceback.format_exc())

                return show

        except Exception as e: 
            P.logger.error('Exception:%s', e)
            P.logger.error(traceback.format_exc())

    
    
    def episode_info(self, code):
        try:
            if code[1] == 'D':
                from lib_metadata import SiteDaumTv
                data = SiteDaumTv.episode_info(code, include_kakao=ModelSetting.get_bool('ktv_use_kakaotv_episode'), summary_duplicate_remove=ModelSetting.get_bool('ktv_summary_duplicate_remove'))
                if data['ret'] == 'success':
                    return data['data']

        except Exception as e: 
            P.logger.error('Exception:%s', e)
            P.logger.error(traceback.format_exc())