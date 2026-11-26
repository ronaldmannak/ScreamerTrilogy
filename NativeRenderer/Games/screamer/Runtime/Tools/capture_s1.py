#!/usr/bin/env python3
"""Bounded input-free S1 capture. Original two-tick physics; hidden SDL video."""
import argparse,datetime,hashlib,json,os,signal,socket,struct,subprocess,time
from pathlib import Path
from live_api import LiveAPI,NotReady
from clock_shared import now_ns
from profile_s1 import EXE_SHA256,RAM_SIZE,WAIT_LINK,LINKS,executable_profile,resolve
from le_image import require,u32


def write_json(path,value):
    with path.open('x') as f:json.dump(value,f,indent=2);f.write('\n')


def configuration(root,game,cue,port):
    return f'''[sdl]\nfullscreen=false\nwindow_size=640x480\noutput=texture\n[dosbox]\nmachine=svga_s3\nmemsize=16\n[cpu]\ncore=auto\ncpu_cycles=3000\ncpu_cycles_protected=max\n[render]\naspect=on\n[dos]\nshell_history_file=\n[capture]\ncapture_dir={root}/capture\n[midi]\nmididevice=none\n[sblaster]\nsbtype=sb16\nsbbase=220\nirq=5\ndma=1\nhdma=5\n[joystick]\njoysticktype=disabled\n[webserver]\nwebserver_enabled=on\nwebserver_bind_address=127.0.0.1\nwebserver_port={port}\n[autoexec]\n@echo off\nmount c "."\nimgmount d "{cue}" -t iso\nc:\nSTARTH.EXE\nexit\n'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True,type=Path);p.add_argument('--game-root',required=True,type=Path)
    p.add_argument('--engine',required=True,type=Path);p.add_argument('--seconds',type=float,default=90)
    p.add_argument('--hold-seconds',type=float,default=0)
    a=p.parse_args();require(0<a.seconds<=180 and 0<=a.hold_seconds<=300,'Bounded capture required')
    source=a.game_root/'STARTH.EXE';objects,fixups,_,_=executable_profile(source.read_bytes())
    root=a.output.resolve();require(not root.exists(),'Use a fresh capture folder');root.mkdir(parents=True)
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    cue=a.game_root/'SCREAM.DAT'
    require(cue.is_file() and (a.game_root/'SCREAM.gog').is_file(),'Owned disc image missing')
    (root/'dosbox.conf').write_text(configuration(root,a.game_root,cue,port))
    env=dict(os.environ,SCREAMER_METAL_BRIDGE='1',SDL_VIDEODRIVER='dummy',SDL_RENDER_DRIVER='software',SDL_AUDIODRIVER='dummy')
    api=LiveAPI(f'http://127.0.0.1:{port}',timeout=.5);started=time.monotonic();process=None;captured=None;last_error=None;stop=False
    def stopping(*_):
        nonlocal stop
        stop=True
    signal.signal(signal.SIGINT,stopping);signal.signal(signal.SIGTERM,stopping)
    log=(root/'engine.log').open('wb')
    try:
        process=subprocess.Popen([str(a.engine),'--noprimaryconf','--nolocalconf','--conf',str(root/'dosbox.conf')],cwd=a.game_root,env=env,stdout=log,stderr=subprocess.STDOUT)
        write_json(root/'engine-info.json',{'engine_pid':process.pid,'endpoint':api.origin,'input_api_used':False,'physics_patches':[]})
        print(json.dumps({'endpoint':api.origin,'engine_pid':process.pid,'output':str(root),'input_api_used':False}),flush=True)
        helper=None;boot=False
        while not stop and process.poll() is None and time.monotonic()-started<a.seconds:
            try:
                before=now_ns();data,info=api.batch([(0,RAM_SIZE)],helper or 0,wait=helper is not None,full=True);after=now_ns()
                ram=data[0];loaded,evidence,markers,physical=resolve(ram,objects,fixups);helper=physical(WAIT_LINK,11)
                meta={'schema_version':1,'profile':'screamer1-software-v1','epoch':root.name,'executable_sha256':EXE_SHA256,'runtime_executable_sha256':EXE_SHA256,
                    'ram_sha256':hashlib.sha256(ram).hexdigest(),'physical_ram_base':0,'ram_size':RAM_SIZE,'pointer_bias':0,
                    'captured_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'monotonic_ns':(before+after)//2,
                    'capture_started_monotonic_ns':before,'capture_duration_ms':(after-before)/1e6,'objects':loaded,'object_resolution_evidence':evidence,
                    'markers':markers,'registers':info.get('registers'),'linear_eip':info.get('linear_eip'),'linear_esp':info.get('linear_esp'),
                    'source_executable':str(source),'engine':str(a.engine),'api_base_url':api.origin,'input_api_used':False,
                    'physics_wait_ticks':2,'timer_frequency_hz':100,'configured_minimum_physics_period_ms':20,'engine_pid':process.pid}
                if not boot:
                    (root/'boot-ram.bin').write_bytes(ram);write_json(root/'layout.json',meta);boot=True
                    print(json.dumps({'layout_ready':str(root/'layout.json'),'objects':loaded}),flush=True)
                valid=lambda address,size:0x10000<=address<=RAM_SIZE-size
                rows,models,camera=(markers[k]['u32'] for k in ('rows','models','camera'))
                require(all(valid(p,n) for p,n in ((rows,1024),(models,4),(camera,112))),'World/camera loading')
                sp=info['linear_esp'];caller=u32(ram,sp+24)
                caller_link=next((o['link_base']+caller-o['physical_base'] for o in loaded if o['physical_base']<=caller<o['physical_base']+o['virtual_size']),None)
                world_name=ram[physical(LINKS['world_name']):physical(LINKS['world_name'])+16].split(b'\0')[0].decode('ascii','replace')
                entries=[];table=physical(LINKS['scene_list'])
                for i in range(512):
                    raw=u32(ram,table+4*i)
                    if not raw:break
                    ptr=raw&0xbfffffff
                    if valid(ptr,0x40):entries.append({'id':f'list:{i}','physical_address':ptr,'flags':raw&0x40000000,'model':u32(ram,ptr),'position':list(struct.unpack_from('<3i',ram,ptr+8))})
                require(len(entries)>=2 and world_name.upper().startswith('MAP'),'No race scene roots yet')
                meta.update(world_name=world_name,scene_roots=entries,caller_link=caller_link,capture_consistency='atomic-cpu-step-at-original-two-tick-frame-wait')
                (root/'guest-ram.bin').write_bytes(ram);write_json(root/'snapshot-metadata.json',meta);captured=str(root/'guest-ram.bin')
                print(json.dumps({'CAPTURE_READY':captured,'metadata':str(root/'snapshot-metadata.json'),'world_name':world_name,'caller_link':caller_link,'scene_roots':len(entries)}),flush=True)
                deadline=time.monotonic()+a.hold_seconds
                while not stop and process.poll() is None and time.monotonic()<deadline:time.sleep(.1)
                break
            except (OSError,ValueError,KeyError,struct.error) as error:last_error=str(error)
            time.sleep(.25 if helper else .5)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)
        log.close();write_json(root/'result.json',{'captured':captured,'last_error':last_error,'engine_exit':process.returncode if process else None,
            'elapsed_seconds':time.monotonic()-started,'input_api_used':False,'physics_patches':[]})
        print(json.dumps({'stopped':True,'capture':captured,'last_error':last_error}),flush=True)
    return 0 if captured else 1


if __name__=='__main__':raise SystemExit(main())
