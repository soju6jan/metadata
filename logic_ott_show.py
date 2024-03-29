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

# 패키지
from lib_metadata import SiteDaumTv, SiteTmdbTv, SiteTvingTv, SiteWavveTv

from .plugin import P
logger = P.logger
package_name = P.package_name
ModelSetting = P.ModelSetting

from lib_metadata.server_util import MetadataServerUtil
#########################################################

class LogicOttShow(LogicModuleBase):
    module_char = 'P'
    db_default = {
        'ott_show_db_version' : '1',
    }

    module_map = {'daum':SiteDaumTv, 'tving':SiteTvingTv, 'wavve':SiteWavveTv, 'tmdb':SiteTmdbTv}

    def __init__(self, P):
        super(LogicOttShow, self).__init__(P, 'setting')
        self.name = 'ott_show'

    def process_api(self, sub, req):
        if sub == 'search':
            call = req.args.get('call')
            manual = bool(req.args.get('manual'))
            if call == 'plex':
                return jsonify(self.search(req.args.get('keyword'), manual=manual))
        elif sub == 'info':
            return jsonify(self.info(req.args.get('code')))
        elif sub == 'episode_info':
            return jsonify(self.episode_info(req.args.get('code')))
            #return jsonify(self.episode_info(req.args.get('code'), req.args.get('no'), req.args.get('premiered'), req.args.get('param')))
            #return jsonify(self.episode_info(req.args.get('code'), req.args.get('no'), py_urllib.unquote(req.args.get('param'))))
        elif sub == 'stream.m3u8':
            ret = self.stream(req.args.get('code'))
            if ret['site'] == 'tving':
                return redirect(ret['url'])
            else:
                return jsonify(ret)


    #########################################################

    def search(self, keyword, manual=False):
        ret = {}
        site_list = ['tving', 'wavve']
        for idx, site in enumerate(site_list):
            logger.debug(site)
            site_data = self.module_map[site].search(keyword, module_char=self.module_char)

            if site_data['ret'] == 'success':
                ret[site] = site_data['data']
                logger.info(u'KTV 검색어 : %s site : %s 매칭', keyword, site)
                if manual:
                    continue
                if site_data['data'][0]['score'] == 100:
                    return ret
        return ret

    def info(self, code):
        try:
            show = None
            if code[1] == 'V': 
                tmp = SiteTvingTv.info(code)
                if tmp['ret'] == 'success':
                    show = tmp['data']
            elif code[1] == 'W': 
                tmp = SiteWavveTv.info(code)
                if tmp['ret'] == 'success':
                    show = tmp['data']
            return show
        except Exception as e: 
            P.logger.error('Exception:%s', e)
            P.logger.error(traceback.format_exc())

    def stream(self, code):
        try:
            show = None
            if code[1] == 'V': 
                from support.site.tving import SupportTving
                data = SupportTving.ins.get_info(code[2:], 'stream50')
                return {'ret':'success', 'site':'tving', 'url':data['url']}
            elif code[1] == 'W': 
                import framework.wavve.api as Wavve
                data = Wavve.streaming('vod', code[2:], '1080p', return_url=True)
                return {'ret':'success', 'site':'wavve', 'url':data}
        except Exception as e: 
            P.logger.error('Exception:%s', e)
            P.logger.error(traceback.format_exc())