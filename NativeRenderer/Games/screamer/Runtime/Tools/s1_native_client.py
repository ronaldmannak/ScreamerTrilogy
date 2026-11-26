#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Guarded S1 engine graphics policy + exact original HUD transport helper.

No keyboard inputs are generated. Call install only after executable_profile()
validated the owned STARTH.EXE SHA and resolve() independently found all LE
objects. A 600ms engine lease restores original polygon drawing if this client
or the Metal frontend stops renewing readiness.
"""
import json
import time

EXE_SHA256='1246afc95463f96598d5fee764fc99c847b6d3e0bf8ca2268bd362c664bb28a3'

class S1NativeGraphics:
    def __init__(self,api):
        self.api=api
        self.installed=False
        self.last_control=0.
        self.last_ready=None
        self.hud_sequence=0

    def control(self,ready,objects=None):
        request={'profile_sha256':EXE_SHA256,'renderer_ready':bool(ready)}
        if objects is not None:
            mapping={obj['index']:obj for obj in objects}
            if set(mapping)!={1,2,3}:raise ValueError('Incomplete original S1 LE mapping')
            request.update(code_base=mapping[1]['physical_base'],data_base=mapping[3]['physical_base'])
        raw,_=self.api.request('POST','/api/v1/s1/native/control',request,limit=65536)
        result=json.loads(raw)
        if result.get('profile_sha256')!=EXE_SHA256 or not result.get('installed'):
            raise ValueError('Original S1 graphics hook not installed')
        self.installed=True;self.last_ready=bool(ready);self.last_control=time.monotonic()
        return result

    def heartbeat(self,renderer_ready):
        # Renew at least 3 times inside the engine600ms expiry period. A false
        # transition is sent immediately. The caller must derive ready from a
        # fresh native frontend heartbeat AND valid current-race assets/HUD.
        ready=bool(renderer_ready)
        if self.installed and (ready!=self.last_ready or time.monotonic()-self.last_control>=.15):
            return self.control(ready)
        return None

    def hud(self):
        raw,headers=self.api.request('GET','/api/v1/s1/native/hud',limit=640*480*4,timeout=.6)
        headers={k.lower():v for k,v in headers.items()}
        width=int(headers['x-s1-hud-width']);height=int(headers['x-s1-hud-height'])
        if (width,height)!=(640,480) or len(raw)!=width*height*4:
            raise ValueError('Invalid original S1 HUD BGRA dimensions')
        if headers.get('x-s1-hud-coverage')!='original-ram-byte-writes':
            raise ValueError('Unknown original S1 HUD alpha provenance')
        sequence=int(headers['x-s1-hud-sequence'])
        metadata={'width':width,'height':height,'stride':width*4,'format':'bgra8',
                  'sequence':sequence,'capture_ns':int(headers['x-s1-hud-capture-ns']),
                  'original_hud_mode':int(headers['x-s1-hud-mode']),
                  'coverage':'original-ram-byte-writes','source_width':640,'source_height':400,
                  'row_expansion':'floor((display_y+1)*54613/65536)',
                  'contains_dashboard':True,'contains_live_needle':True,'contains_countdown':True}
        self.hud_sequence=sequence
        return raw,metadata
