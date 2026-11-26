#!/usr/bin/env python3
"""Live, loopback Screamer2 game-state bridge. No physics writes or OS input automation.

The custom engine exposes atomic range reads, normal keyboard events and its
actual cached framebuffer. Stock read/guarded keyboard-table paths are optional
fallbacks. Extraction is performed in a separate low-priority child process.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime,timezone
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import struct
import sys
import threading
import time
import urllib.error
import uuid

sys.dont_write_bytecode=True

from asset_jobs import AssetJobs
import original_draw_distance
import s2_sky_state
from s2_sky_assets import export_sky
from s2_overlay_api import paired_display
from s2_hud import HudPublisher
from clock_shared import now_ns
from guest_memory import Snapshot, SnapshotError, SUPPORTED_EXECUTABLES
from input_lease import InputLease, KeyboardOutput
from live_api import LiveAPI, NotReady
from replay import (SCENE, VIEW_CAMERAS, CAMERA_STRUCTURE_OFFSET, camera_from_pose,
                    read_instances, rotation)


RAM_SIZE = 16*1024*1024
LINK = {"helper":0x519B4,"pending":0x519EA,"clocks":0x153D94,"track":0x151680,
        "flags":0x151748,"race_state":0x13FAC0,"step":0x153D88,"raw_step":0x153D8C,
        "rows":0x133710,"models":0x154760,"view":VIEW_CAMERAS,"scene":SCENE,
        "current_camera":0x8383C,"view_height":0x83854,"center_y":0x8386C,"view_width":0x83880}
LINK.update(s2_sky_state.LINKS)
LINK["mirror_enabled"]=0x13fadc
MAX_CLOCK_INTERVAL_NS=150_000_000


def integer(value):
    result = int(value, 0) if isinstance(value, str) else value
    if not isinstance(result, int) or isinstance(result, bool) or result < 0 or result >= (1<<32):
        raise SnapshotError("Invalid32-bit layout value")
    return result


class Layout:
    """Validated address mapping without requiring a saved RAM image at boot."""
    def __init__(self, metadata):
        if metadata.get("executable_sha256") not in SUPPORTED_EXECUTABLES:
            raise SnapshotError("Unsupported original S2_3DFX layout")
        if metadata.get("physical_ram_base", 0) != 0 or metadata.get("ram_size") != RAM_SIZE or metadata.get("pointer_bias", 0) != 0:
            raise SnapshotError("Live prototype requires16MiB flat RAM with zero pointer bias")
        objects = []
        for item in metadata["objects"]:
            link, physical, size = integer(item["link_base"]),integer(item.get("physical_base",item.get("runtime_base"))),integer(item.get("virtual_size",item.get("size")))
            if not size or physical+size > RAM_SIZE or link+size > (1<<32):
                raise SnapshotError("LE mapping exceeds the live RAM range")
            objects.append((link,physical,size))
        if not objects or len(objects)>256:
            raise SnapshotError("Invalid LE object count")
        for column in (0,1):
            ordered=sorted(objects,key=lambda item:item[column])
            if any(a[column]+a[2]>b[column] for a,b in zip(ordered,ordered[1:])):
                raise SnapshotError("Overlapping live LE mappings")
        self.objects,self.metadata=objects,dict(metadata)
        for address in LINK.values():
            self.link(address,4)

    def link(self,address,size=1):
        for link,physical,length in self.objects:
            offset=address-link
            if 0<=offset and size<=length-offset:
                return physical+offset
        raise SnapshotError(f"Unknown link range{address:#x}+{size}")

    def to_link(self,address):
        for link,physical,size in self.objects:
            if physical<=address<physical+size:
                return link+address-physical
        raise SnapshotError("Runtime code pointer lies outside the recognized image")

    def translate_pointer(self,address):
        return integer(address)


def atomic_bytes(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name("."+path.name+f".{os.getpid()}.tmp")
    with temporary.open("wb") as output:
        output.write(data)
    os.replace(temporary,path)


def atomic_json(path,value):
    atomic_bytes(path,(json.dumps(value,separators=(",",":"),allow_nan=False)+"\n").encode())


def hud_for_phase(profile,phase,camera_mode,frame,flags=0):
    """Publish the honest phase descriptor; frontend owns partial-HUD consent."""
    if not isinstance(profile,dict) or not frame:return None
    if profile.get("schema")=="screamer-hud-profiles/v1":
        selected=profile.get("profiles",{}).get(phase)
    else:selected=profile
    if not isinstance(selected,dict) or selected.get("phase") not in {None,phase}:return None
    overrides=selected.get("camera_overrides",{})
    if isinstance(overrides,dict) and str(camera_mode) in overrides:selected=overrides[str(camera_mode)]
    if not isinstance(selected,dict):return None
    requirements=selected.get("requires",{})
    if not isinstance(requirements,dict)or requirements.get("phase") not in {None,phase}:return None
    clear=requirements.get("game_flags_mask_clear",0)
    mask=requirements.get("game_flags_mask",0);expected=requirements.get("game_flags_value",0)
    if any(type(value)is not int or not 0<=value<2**32 for value in (flags,clear,mask,expected)):return None
    if flags&clear or flags&mask!=expected:return None
    modes=selected.get("allowed_camera_modes")
    if modes is not None and camera_mode not in modes:return None
    if selected.get("source_width",frame["width"])!=frame["width"] or selected.get("source_height",frame["height"])!=frame["height"]:return None
    complete=selected.get("complete") is True
    partial=selected.get("complete") is False and selected.get("primary_hud_validated") is True
    rectangles=selected.get("rects")
    if not(complete or partial)or not isinstance(rectangles,list)or not 1<=len(rectangles)<=64:return None
    for r in rectangles:
        if not isinstance(r,dict)or any(type(r.get(k))is not int for k in ("x","y","width","height")):return None
        if not(0<=r["x"] and 0<=r["y"] and r["width"]>0 and r["height"]>0 and r["x"]+r["width"]<=frame["width"] and r["y"]+r["height"]<=frame["height"]):return None
    return {key:value for key,value in selected.items()if key!="camera_overrides"}


class PoseFeed:
    def __init__(self,api,layout):
        self.api,self.layout=api,layout
        self.helper=layout.link(LINK["helper"],13)
        self.address={name:layout.link(value,4) for name,value in LINK.items()}
        self.cars=[];self.camera_address=None;self.owner=None
        self.epoch_key=None
        self.cache_generation=0
        self.last_clocks=None
        self.unique_clocks=0
        self.first_clock_ns=self.last_clock_ns=None
        self.active_race_ns=0;self.last_phase=None;self.last_phase_ns=None;self.clock_transitions=0
        self.attempts=self.not_ready=0

    def invalidate(self):
        """Retire every cached guest pointer before attempting a new capture."""
        self.cars=[];self.owner=None;self.camera_address=None;self.epoch_key=None
        self.cache_generation+=1

    def ranges(self):
        a=self.address
        result=[(a["helper"],13),(a["pending"],4),(a["clocks"],8),(a["track"],16),
                (a["flags"],4),(a["race_state"],4),(a["step"],4),(a["raw_step"],4),
                (a["rows"],4),(a["models"],4),(a["view"],4),(a["current_camera"],4),
                (a["view_height"],4),(a["center_y"],4),(a["view_width"],4),(a["mirror_enabled"],4)]
        result += [(a[name],4)for name in s2_sky_state.LINKS]
        if self.camera_address is not None:
            result += [(self.camera_address,24),(a["scene"],(max(int(item["id"].split(":")[1]) for item in self.cars)+1)*28)]
            if self.owner is not None and self.owner+0xAE8<=RAM_SIZE:
                result += [(self.owner+0xAE4,4)]
            result += [(item["guest_address"],36) for item in self.cars]
        result += original_draw_distance.ranges(self.layout,'screamer2')
        return result

    def _legacy(self,ranges):
        a=self.address
        before=self.api.marker(a["clocks"],a["pending"],self.helper,self.layout.to_link)
        data={address:self.api.read(address,size) for address,size in ranges}
        after=self.api.marker(a["clocks"],a["pending"],self.helper,self.layout.to_link)
        if (before["clocks"]!=after["clocks"] or before["caller"]!=after["caller"]
                or not 0<=before["pending"]<=after["pending"]<2):
            raise NotReady("Legacy field group crossed a frame/timer boundary")
        return data,{"registers":after["registers"],"caller_link":after["caller"],"atomic_batch":False}

    def read(self):
        self.attempts+=1
        before=now_ns();ranges=self.ranges()
        try:
            if self.api.native_batch is not False:
                try:
                    data,info=self.api.batch(ranges,self.helper)
                except urllib.error.HTTPError as error:
                    if error.code not in (404,405):raise
                    data,info=self._legacy(ranges)
            else:
                data,info=self._legacy(ranges)
        except NotReady:
            self.not_ready+=1
            raise
        after=now_ns()
        a=self.address
        # The relocated wait helper's load target must be its own tick counter,
        # and the configured pacing immediate must remain two ticks.
        code=data[a["helper"]]
        if (code[:2]!=b"\x50\xa1" or struct.unpack_from("<I",code,2)[0]!=a["pending"]
                or code[6:]!=bytes.fromhex("83f8027cf658c3")):
            raise SnapshotError("Live guest wait/code guard failed")
        if "caller_link" in info:
            caller=info["caller_link"]
        else:
            raw=base64.b64decode(info["stack"]["data"],validate=True)
            if len(raw)<8:raise SnapshotError("Atomic batch omitted the wait stack")
            caller=self.layout.to_link(struct.unpack_from("<I",raw,4)[0])
        phase="race" if caller==0x50C6D else "menu" if caller==0x50BCB else "loading"
        flags_value=struct.unpack("<I",data[a["flags"]])[0]
        metric_phase="attract" if phase=="race" and flags_value&0x80 else phase
        pending=struct.unpack("<I",data[a["pending"]])[0]
        # A single atomic batch in the wait helper is a coherent completed
        # frame even when drawing already consumed the minimum two ticks.
        # Only the multi-request fallback needs remaining idle-time margin.
        if pending>=2 and not self.api.native_batch:raise NotReady("Legacy wait has reached its next simulation step")
        clocks=data[a["clocks"]]
        real_clock,simulation_clock=struct.unpack("<2f",clocks)
        if not all(math.isfinite(value) for value in (real_clock,simulation_clock)):
            raise SnapshotError("Non-finite live game clocks")
        midpoint=(before+after)//2
        # Pauses/non-wait phases can yield no accepted reads. Their wall time
        # must not dilute the rate after resuming. Within a contiguous segment
        # retain the entire elapsed interval, including ordinary poll jitter.
        interval=midpoint-self.last_phase_ns if self.last_phase_ns is not None else 0
        contiguous=(metric_phase=="race" and self.last_phase=="race"
                    and 0<interval<=MAX_CLOCK_INTERVAL_NS)
        if contiguous:self.active_race_ns+=interval
        if metric_phase=="race" and clocks!=self.last_clocks:
            if contiguous:self.clock_transitions+=1
            self.unique_clocks+=1
            self.last_clocks=clocks
            self.last_clock_ns=(before+after)//2
            if self.first_clock_ns is None:self.first_clock_ns=self.last_clock_ns
        self.last_phase,self.last_phase_ns=metric_phase,midpoint
        car_count,track,condition,detail=struct.unpack("<4I",data[a["track"]])
        rows=struct.unpack("<I",data[a["rows"]])[0];models=struct.unpack("<I",data[a["models"]])[0]
        owner=struct.unpack("<I",data[a["view"]])[0]
        epoch_key=(track,condition,detail,car_count,rows,models)
        value={"status":phase,"sample_monotonic_ns":(before+after)//2,"acquisition_ms":(after-before)/1e6,
               "track_id":track,"condition":condition,"detail":detail,"car_count":car_count,
               "scene_key":epoch_key,"camera_owner":owner,"camera_mode":None,"flags":flags_value,
               "race_state":struct.unpack("<I",data[a["race_state"]])[0],
               "guest_tick":pending,"real_clock":real_clock,"simulation_clock":simulation_clock,
               "frame_clock_bits":clocks.hex(),
               "consistency":"atomic-cpu-step-at-frame-wait" if self.api.native_batch else "before-after-wait-and-clock-guard",
               "camera":None,"instances":[]}
        value["player_telemetry"]=None
        raw_step=struct.unpack("<f",data[a["raw_step"]])[0]
        step=struct.unpack("<f",data[a["step"]])[0]
        value["timing"]={"raw_frame_step_seconds":raw_step if math.isfinite(raw_step) else None,
                         "smoothed_step_seconds":step if math.isfinite(step) else None}
        if self.epoch_key is not None and (epoch_key!=self.epoch_key or owner!=self.owner):
            self.invalidate()
        value["original_draw_distance"]=original_draw_distance.distance(self.layout,data,'screamer2')
        value["cache_generation"]=self.cache_generation
        value["sky"]=s2_sky_state.state(self.layout,data)
        value["mirror_enabled"]=bool(struct.unpack("<I",data[a["mirror_enabled"]])[0])
        if phase!="race" or epoch_key!=self.epoch_key or owner!=self.owner:
            return value
        if self.owner+0xAE4 in data:
            value["camera_mode"]=struct.unpack("<I",data[self.owner+0xAE4])[0]
        camera_data=data[self.camera_address]
        angles=struct.unpack_from("<3i",camera_data);position=struct.unpack_from("<3i",camera_data,12)
        if any(abs(angle)>2048*1024 for angle in angles):raise NotReady("Camera state is changing")
        value["camera"]=original_draw_distance.attach_camera(camera_from_pose(position,angles),value["original_draw_distance"])
        current,width,height,cy=(struct.unpack("<I",data[a[key]])[0] for key in ("current_camera","view_width","view_height","center_y"))
        if current==self.camera_address and width==640 and height==400 and 0<=cy<=400:
            value["camera"]["projection"]["cy"]=cy*1.2
            value["camera"]["projection_source"]="live main-view globals at original frame wait; fixed256 focal from verified projection code"
        value["camera"]["guest_address"]=self.camera_address
        value["camera"]["source_view"]="main-view"
        table=data[a["scene"]]
        for original in self.cars:
            entry=int(original["id"].split(":")[1]);pointer=struct.unpack_from("<I",table,entry*28+12)[0]
            if pointer!=original["guest_address"]:
                self.invalidate()
                raise NotReady("Car table changed; cached scene retired")
            raw=data[pointer];model,flags=struct.unpack_from("<2I",raw)
            if model!=original["model"] or flags&0x8000:
                self.invalidate()
                raise NotReady("Car model changed; cached scene retired")
            item=dict(original);item["position"]=list(struct.unpack_from("<3i",raw,8));item["angles"]=[v%2048 for v in struct.unpack_from("<3i",raw,20)]
            item["rotation"]=rotation(item["angles"]);item["flags"]=flags
            value["instances"].append(item)
        return value

    def capture_race(self,value):
        before=now_ns()
        if self.api.native_batch is not False:
            data,info=self.api.batch([(0,RAM_SIZE)],self.helper,full=True)
            ram=data[0]
        else:
            # An atomic stock JSON memory read includes the CPU registers; it
            # must still end in the recognized completed-frame wait phase.
            body,_=self.api.request("GET",f"/api/v1/memory/0/{RAM_SIZE}",headers={"Accept":"application/json"},limit=24*1024*1024,timeout=3)
            result=json.loads(body);pc=int(result["registers"]["eip"])
            if pc not in {self.helper+1,self.helper+6,self.helper+9}:raise NotReady("Full capture is outside the frame wait")
            ram=base64.b64decode(result["memory"]["data"],validate=True)
            info={}
        after=now_ns()
        metadata=dict(self.layout.metadata,ram_sha256=hashlib.sha256(ram).hexdigest(),monotonic_ns=(before+after)//2,
                      captured_utc=datetime.now(timezone.utc).isoformat(),capture_started_monotonic_ns=before,
                      capture_duration_ms=(after-before)/1e6,server_capture_ns=info.get("capture_ns"))
        memory=Snapshot(ram,metadata)
        cars,rejected=read_instances(memory)
        cars=[item for item in cars if item["name"].startswith("auto") and not item["billboard"]]
        if not 1<=len(cars)<=16 or len(cars)!=value["car_count"]:raise NotReady("S2 scene car count has not settled")
        owner=memory.pointer(memory.link(VIEW_CAMERAS,4));camera_address=owner+CAMERA_STRUCTURE_OFFSET
        if not owner or not memory.readable(camera_address,24):raise NotReady("Main camera is not ready")
        actual_key=tuple(memory.rd32(memory.link(LINK["track"]+offset,4)) for offset in (4,8,12,0))
        actual_key += (memory.rd32(memory.link(LINK["rows"],4)),memory.rd32(memory.link(LINK["models"],4)))
        if actual_key!=value["scene_key"]:raise NotReady("Race changed while taking its asset capture")
        self.cars,self.owner,self.camera_address,self.epoch_key=cars,owner,camera_address,actual_key
        return memory


class Session:
    def __init__(self,args):
        self.args=args;self.epoch=uuid.uuid4().hex;self.seq=0;self.stop=False
        self.read_only=bool(getattr(args,"read_only",False))
        self.api=LiveAPI(args.base_url)
        self.input_api=LiveAPI(args.base_url)
        self.input=InputLease(args.input,self.epoch)
        self.keyboard=KeyboardOutput(self.input_api,None,False)
        if self.read_only:self.keyboard.method="disabled-read-only-diagnostic"
        self.input_error=None;self.input_thread=None
        self.layout=self.feed=None;self.layout_signature=None
        self.jobs=AssetJobs(args.cache_root,args.extractor_dir,getattr(args,'game_root',None))
        self.assets=None;self.race_epoch=None;self.scene_key=None;self.previous_phase="loading"
        self.scene_generation=None;self.capture_pending=False
        self.previous_attract=True
        self.frame=None;self.last_frame_poll=0;self.last_frame_seq=None
        self.overlay_raw=self.overlay_metadata=None;self.overlay_supported=None
        self.hud_publisher=HudPublisher(args.state.parent/"hud")
        self.sky_assets={};self.sky_error=None
        self.last_layout_check=0;self.last_capture_try=0;self.last_pose=None
        self.pose_sequence=0
        self.started=time.monotonic();self.last_error=None
        self.frame_directory=args.state.parent/"frames"
        self.hud=json.loads(args.hud_profile.read_text()) if args.hud_profile else None

    def load_layout(self,now):
        if now-self.last_layout_check<.5:return
        self.last_layout_check=now
        try:
            stat=self.args.layout.stat();signature=(stat.st_ino,stat.st_mtime_ns,stat.st_size)
            if signature==self.layout_signature:return
            if stat.st_size>1024*1024:raise SnapshotError("Live layout exceeds1MiB")
            layout=Layout(json.loads(self.args.layout.read_text()))
            self.layout,self.feed=layout,PoseFeed(self.api,layout)
            self.keyboard.memory=layout
            self.layout_signature=signature;self.scene_key=self.race_epoch=None;self.assets=None
            self.scene_generation=None;self.capture_pending=False
        except FileNotFoundError:
            pass

    def poll_frame(self,now):
        if now-self.last_frame_poll<1/self.args.frame_hz:return
        self.last_frame_poll=now
        try:
            overlay=metadata=None
            if self.overlay_supported is not False:
                try:
                    data,value,overlay,metadata=paired_display(self.api);self.overlay_supported=True
                except (KeyError,ValueError,NotReady):data,value=self.api.frame()
                except urllib.error.HTTPError as error:
                    if error.code in (404,405):self.overlay_supported=False
                    else:raise
            if self.overlay_supported is False:data,value=self.api.frame()
            if value["sequence"]!=self.last_frame_seq:
                path=self.frame_directory/f"frame-{value['sequence']%4}.bgra"
                atomic_bytes(path,data);value["path"]=str(path)
                self.frame=value;self.last_frame_seq=value["sequence"]
                self.overlay_raw,self.overlay_metadata=overlay,metadata
        except (NotReady,urllib.error.URLError,KeyError,ValueError,OSError):pass

    def sky_asset(self,pose):
        game=getattr(self.args,"game_root",None)
        if game is None:return None
        key=(pose.get("track_id"),pose.get("condition"))
        if key not in self.sky_assets:
            root=self.args.cache_root/"original-skies"
            descriptor=export_sky(game,*key,root)
            self.sky_assets[key]=str(root/descriptor["path"])
        return self.sky_assets[key]

    def state(self,pose=None):
        now=now_ns();pose=pose or self.last_pose or {}
        phase=pose.get("status","loading" if self.layout else "offline")
        age=(now-pose["sample_monotonic_ns"])/1e9 if pose.get("sample_monotonic_ns") else 0
        attract=bool(pose.get("flags",0)&0x80)
        if phase=="race" and attract:phase="attract"
        if phase in {"race","attract"} and age>.15:phase="paused"
        native_phase=phase in {"race","attract"}
        ready=bool(self.assets and self.assets["epoch"]==self.race_epoch and native_phase and pose.get("camera") and age<=.15)
        assets=dict(self.assets) if ready else None
        if assets is not None:
            assets["world_scene"]=assets.get("world_scene",assets.get("scene"))
            assets["cars_scene"]=assets.get("cars_scene",assets.get("cars"))
            try:
                sky=self.sky_asset(pose)
                if sky:assets["sky_texture"]=sky
                self.sky_error=None
            except (ValueError,OSError,KeyError,TypeError)as error:
                self.sky_error=str(error);ready=False;assets=None
        value={"schema":"screamer-live/v1","epoch":self.epoch,"sequence":self.seq,"seq":self.seq,
               "published_monotonic_ns":now,"sample_monotonic_ns":pose.get("sample_monotonic_ns",now),
               "timestamp_monotonic":pose.get("sample_monotonic_ns",now)/1e9,"physics_period_ms":20,
               "physics_period_source":"original two 100Hz timer ticks; observed clock changes measured separately",
               "status":phase,"mode":phase if ready else "framebuffer","running":not self.stop,
               "bridge_pid":os.getpid(),"pose_age_ms":age*1000,"is_attract":attract,"race_flags":pose.get("flags"),
               "read_only":self.read_only,"profile":"screamer2-3dfx-v1",
               "race_state":pose.get("race_state"),"player_telemetry":None,"timing":pose.get("timing"),
               "original_draw_distance":pose.get("original_draw_distance"),"camera":pose.get("camera"),"instances":pose.get("instances",[]),"pose_sequence":self.pose_sequence,"assets_ready":ready,
               "camera_mode":pose.get("camera_mode"),
               "cache_generation":pose.get("cache_generation"),
               "assets":assets,"framebuffer":self.frame,"sky":pose.get("sky"),"sky_error":self.sky_error,
               "track_id":pose.get("track_id"),"scene_epoch":self.race_epoch,"guest_tick":pose.get("guest_tick"),
               "real_clock":pose.get("real_clock"),"simulation_clock":pose.get("simulation_clock"),
               "consistency":pose.get("consistency"),"acquisition_ms":pose.get("acquisition_ms"),
               "input":{"method":self.keyboard.method,"focused":self.input.focused,"held_keys":sorted(self.keyboard.held),"error":self.input_error or self.input.error},
               "metrics":{"elapsed_seconds":time.monotonic()-self.started,"http_requests":self.api.requests,
                          "received_bytes":self.api.received_bytes,"pose_attempts":self.feed.attempts if self.feed else 0,
                          "not_ready":self.feed.not_ready if self.feed else 0,"distinct_race_clock_states":self.feed.unique_clocks if self.feed else 0,
                          "observed_race_seconds":self.feed.active_race_ns/1e9 if self.feed else 0,
                          "observed_clock_transitions":self.feed.clock_transitions if self.feed else 0,
                          "observed_clock_transitions_hz":self.feed.clock_transitions/(self.feed.active_race_ns/1e9) if self.feed and self.feed.active_race_ns else 0},
               "asset_error":self.jobs.error,"error":self.last_error}
        if ready:
            value["scene_dir"]=str(Path(self.assets["scene"]).parent);value["cars_dir"]=str(Path(self.assets["cars"]).parent)
        selected_hud=hud_for_phase(self.hud,phase,pose.get("camera_mode"),self.frame,pose.get("flags",0))
        if selected_hud is not None:value["hud"]=selected_hud
        if ready and not(pose.get("flags",0)&0x40) and self.overlay_raw is not None and self.overlay_metadata is not None:
            try:value["hud"]=self.hud_publisher.publish(self.overlay_raw,self.overlay_metadata,phase,pose.get("mirror_enabled",False),pose.get("camera_mode"))
            except (ValueError,OSError,KeyError):pass
        return value

    def input_loop(self):
        try:
            while not self.stop:
                try:
                    self.keyboard.send(self.input.desired())
                    self.input_error=None
                except (OSError,ValueError,KeyError,TypeError) as error:
                    self.input_error=str(error)
                time.sleep(.01)
        finally:
            try:self.keyboard.release()
            except (OSError,ValueError):pass

    def retain_pose(self,pose):
        """A heartbeat cannot retimestamp the same completed simulation state."""
        old=self.last_pose or {}
        keys=("frame_clock_bits","status","flags","scene_key","camera_owner","camera_mode","cache_generation")
        changed=(any(pose.get(key)!=old.get(key) for key in keys)
                 or bool(pose.get("camera"))!=bool(old.get("camera")))
        if changed:
            self.last_pose=pose;self.pose_sequence+=1
        return changed

    def note_scene(self,pose,attract):
        generation=pose.get("cache_generation",0)
        changed=(pose["scene_key"]!=self.scene_key or generation!=self.scene_generation
                 or self.previous_phase=="menu" or (self.previous_attract and not attract))
        if changed:
            self.scene_key=pose["scene_key"];self.scene_generation=generation
            self.race_epoch=uuid.uuid4().hex;self.assets=None;self.capture_pending=True
        if (self.feed.epoch_key!=pose["scene_key"] or self.jobs.current is None
                or self.jobs.current["epoch"]!=self.race_epoch):
            self.capture_pending=True
        return changed

    def handle_pose(self,pose,now):
        """Keep a scene capture pending across throttle skips and wait misses."""
        attract=bool(pose.get("flags",0)&0x80)
        if pose["status"]=="race":self.note_scene(pose,attract)
        # Record transitions before capture I/O, which can legitimately be
        # unavailable until a later completed-frame wait.
        self.previous_phase=pose["status"];self.previous_attract=attract
        if pose["status"]=="race":
            if self.capture_pending and now-self.last_capture_try>.25:
                self.last_capture_try=now
                memory=self.feed.capture_race(pose)
                self.jobs.start(self.race_epoch,memory.data,memory.metadata)
                self.capture_pending=False
            self.assets=self.jobs.poll(self.race_epoch)
        self.retain_pose(pose)

    def run(self):
        atomic_json(self.args.state,self.state())
        if not self.read_only:
            self.input_thread=threading.Thread(target=self.input_loop,name="rally-input",daemon=True)
            self.input_thread.start()
        due=time.monotonic()
        try:
            while not self.stop:
                now=time.monotonic()
                if self.args.seconds and now-self.started>=self.args.seconds:break
                if self.args.parent_pid:
                    try:os.kill(self.args.parent_pid,0)
                    except ProcessLookupError:break
                self.last_error=None
                self.poll_frame(now)
                try:
                    self.load_layout(now)
                    if self.feed:
                        pose=self.feed.read()
                        self.handle_pose(pose,now)
                except NotReady:
                    if self.feed and self.feed.cache_generation!=self.scene_generation:
                        self.assets=None
                except (OSError,ValueError,KeyError,TypeError) as error:
                    self.last_error=str(error)
                self.seq+=1;atomic_json(self.args.state,self.state())
                due+=1/self.args.poll_hz
                delay=due-time.monotonic()
                if delay>0:time.sleep(min(delay,.05))
                elif delay<-.2:due=time.monotonic()
        finally:
            self.stop=True
            if self.input_thread:self.input_thread.join(timeout=1)
            self.jobs.stop();self.seq+=1
            atomic_json(self.args.state,self.state())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url",required=True)
    parser.add_argument("--layout",type=Path,required=True)
    parser.add_argument("--state",type=Path,required=True)
    parser.add_argument("--input",type=Path,required=True)
    parser.add_argument("--cache-root",type=Path,required=True)
    parser.add_argument("--extractor-dir",type=Path,required=True)
    parser.add_argument("--parent-pid",type=int)
    parser.add_argument("--seconds",type=float,default=0)
    parser.add_argument("--poll-hz",type=float,default=100)
    parser.add_argument("--frame-hz",type=float,default=30)
    parser.add_argument("--hud-profile",type=Path)
    parser.add_argument("--game-root",type=Path,help="Owned original S2 game for exact sky archives")
    parser.add_argument("--read-only",action="store_true",help="Disable all keyboard service for automatic-attract diagnostics")
    args=parser.parse_args()
    if not 1<=args.poll_hz<=120 or not 1<=args.frame_hz<=60 or not 0<=args.seconds<=86400:
        parser.error("Invalid bounded rate/duration")
    if args.parent_pid is not None and args.parent_pid<=1:parser.error("ParentPID must exceed1")
    session=Session(args)
    def stop(signum,frame):session.stop=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    session.run()


if __name__=="__main__":main()
