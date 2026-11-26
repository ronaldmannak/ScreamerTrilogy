#!/usr/bin/env python3
"""Own an unpatched S2_3DFX process and publish its exact live LE layout."""
from pathlib import Path
import argparse,datetime,fcntl,hashlib,json,os,shutil,signal,socket,subprocess,sys,time,uuid
sys.dont_write_bytecode=True
LIVE=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(LIVE),str(LIVE/'bridge')]
from profile_s2 import EXE_SHA256,OVL_SHA256,RAM_SIZE,executable_profile,resolve
from le_image import require
from live_api import LiveAPI
from clock_shared import now_ns

def publish(path,value):
 temp=path.with_name('.'+path.name+'.tmp');temp.write_text(json.dumps(value,separators=(',',':'))+'\n');os.replace(temp,path)
def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def clean_path(path):
 path=path.expanduser().resolve();require(not any(c in str(path)for c in ('"','\r','\n')),'Unsupported quote/newline in path');return path

def configuration(cue,run,port):
 return f'''[sdl]\nfullscreen=false\nwindow_size=1280x960\noutput=texture\n[dosbox]\nmachine=svga_s3\nmemsize=16\n[cpu]\ncore=auto\ncpu_cycles=3000\ncpu_cycles_protected=max\n[render]\naspect=on\n[dos]\nshell_history_file=\n[capture]\ncapture_dir={run}/capture\n[midi]\nmididevice=none\n[sblaster]\nsbtype=sb16\nsbbase=220\nirq=7\ndma=1\nhdma=5\n[joystick]\njoysticktype=disabled\n[voodoo]\nvoodoo=on\nvoodoo_memsize=4\nvoodoo_threads=auto\n[webserver]\nwebserver_enabled=on\nwebserver_bind_address=127.0.0.1\nwebserver_port={port}\n[autoexec]\n@echo off\nmount c "."\nimgmount d "{cue}" -t iso\nc:\nS2_3DFX.EXE\nexit\n'''

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('engine','game-root','data-dir','session-dir'):p.add_argument('--'+name,type=Path,required=True)
 p.add_argument('--ovl',type=Path);p.add_argument('--port',type=int,required=True);p.add_argument('--parent-pid',type=int)
 p.add_argument('--max-seconds',type=float,default=0);p.add_argument('--startup-timeout',type=float,default=70);p.add_argument('--audio',choices=('on','dummy'),default='on')
 a=p.parse_args();require(1<=a.port<=65535 and 0<=a.max_seconds<=86400 and 0<a.startup_timeout<=300,'Invalid port/duration')
 require(a.parent_pid is None or a.parent_pid>1,'Parent PID must exceed one')
 engine,source,data,run=map(clean_path,(a.engine,a.game_root,a.data_dir,a.session_dir))
 require(not(data==source or data in source.parents or source in data.parents),'Writable data must not overlap the original game source')
 require(not(run==source or source in run.parents),'Session files must not be written into the original game source')
 exe=source/'S2_3DFX.EXE';raw=exe.read_bytes();objects,fixups,*_=executable_profile(raw)
 ovl_path=clean_path(a.ovl or source/'GLIDE2X.OVL');ovl=ovl_path.read_bytes();require(hashlib.sha256(ovl).hexdigest()==OVL_SHA256,'Expected owned genuine DOS Glide driver')
 cue=source/'GAME.DAT';require(cue.read_text().startswith('FILE "GAME.GOG" BINARY'),'Expected original case-sensitive GOG cue pair');require((source/'GAME.GOG').is_file(),'Missing owned CD image')
 require(engine.is_file()and os.access(engine,os.X_OK),'Engine not executable')
 owner_path=data/'.screamer2-metal-owner.json';owner={'application':'Screamer2Metal','source_sha256':EXE_SHA256,'ovl_sha256':OVL_SHA256}
 if data.exists()and any(data.iterdir()):require(owner_path.is_file()and all(json.loads(owner_path.read_text()).get(k)==v for k,v in owner.items()),'Existing data folder is not owned by this S2 profile')
 data.mkdir(parents=True,exist_ok=True)
 lock=(data/'.running.lock').open('a+b');fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
 if not owner_path.exists():publish(owner_path,dict(owner,created_utc=utc()))
 game=data/'Game'
 if not game.exists():
  staging=data/('.staging-'+uuid.uuid4().hex);staging.mkdir()
  for src in source.iterdir():
   if src.name in ('GAME.GOG','GAME.DAT')or src.suffix.lower()in('.pif','.ico','.conf'):continue
   if src.is_dir():shutil.copytree(src,staging/src.name)
   else:shutil.copy2(src,staging/src.name)
  (staging/'GLIDE2X.OVL').write_bytes(ovl);os.replace(staging,game)
 require(hashlib.sha256((game/'S2_3DFX.EXE').read_bytes()).hexdigest()==EXE_SHA256,'Writable S2 original changed; refusing execution')
 require(hashlib.sha256((game/'GLIDE2X.OVL').read_bytes()).hexdigest()==OVL_SHA256,'Writable DOS Glide driver changed')
 run.mkdir(parents=True,exist_ok=True);require(not(run/'layout.json').exists(),'Use a fresh session directory')
 (run/'dosbox.conf').write_text(configuration(cue,run,a.port));api=LiveAPI(f'http://127.0.0.1:{a.port}',timeout=.5)
 env=dict(os.environ,SCREAMER_METAL_BRIDGE='1',SDL_VIDEODRIVER='dummy',SDL_RENDER_DRIVER='software',PYTHONDONTWRITEBYTECODE='1')
 env['SDL_AUDIODRIVER']='dummy'if a.audio=='dummy'else'coreaudio'if sys.platform=='darwin'else env.get('SDL_AUDIODRIVER','')
 stop=False
 def stop_requested(*unused):nonlocal stop;stop=True
 signal.signal(signal.SIGTERM,stop_requested);signal.signal(signal.SIGINT,stop_requested)
 process=None;start=time.monotonic();ready=False;reason='engine-exited';status={'state':'starting','profile':'screamer2-3dfx-v1','api_base_url':api.origin,'launcher_pid':os.getpid(),'data_dir':str(data),'original_wait_ticks':2}
 log=(run/'runtime.log').open('wb')
 try:
  process=subprocess.Popen([str(engine),'--noprimaryconf','--nolocalconf','--conf',str(run/'dosbox.conf')],cwd=game,env=env,stdout=log,stderr=subprocess.STDOUT)
  status['engine_pid']=process.pid;publish(run/'engine-status.json',status)
  print(json.dumps(dict(status,session=str(run))),flush=True)
  while not stop and process.poll()is None:
   elapsed=time.monotonic()-start
   if a.max_seconds and elapsed>=a.max_seconds:reason='bounded-time-limit';break
   if a.parent_pid:
    try:os.kill(a.parent_pid,0)
    except ProcessLookupError:reason='parent-exited';break
   if not ready:
    if elapsed>a.startup_timeout:reason='layout-timeout';break
    try:
     before=now_ns();parts,info=api.batch([(0,RAM_SIZE)],0,wait=False,full=True);after=now_ns();memory=parts[0]
     loaded,evidence,markers,physical=resolve(memory,objects,fixups)
     meta={'schema_version':1,'profile':'screamer2-3dfx-v1','epoch':run.name,'session_id':run.name,'executable_sha256':EXE_SHA256,'runtime_executable_sha256':EXE_SHA256,
       'ram_sha256':hashlib.sha256(memory).hexdigest(),'physical_ram_base':0,'ram_size':RAM_SIZE,'pointer_bias':0,'objects':loaded,
       'object_resolution_evidence':evidence,'markers':markers,'registers':info.get('registers'),'captured_utc':utc(),'monotonic_ns':(before+after)//2,
       'source_executable':str(exe),'ovl_sha256':OVL_SHA256,'api_base_url':api.origin,'engine_pid':process.pid,'physics_wait_ticks':2,
       'configured_minimum_physics_period_ms':20,'capture_duration_ms':(after-before)/1e6,'limitations':'Boot layout may precede world; bridge independently captures loaded assets at original frame wait'}
     publish(run/'layout.json',meta);ready=True;status.update(state='ready',layout_path=str(run/'layout.json'));status.pop('last_error',None)
     print('Screamer2 original two-tick layout ready',flush=True)
    except (OSError,ValueError,KeyError)as e:status['last_error']=str(e)[:500]
   status['elapsed_seconds']=elapsed;status['updated_utc']=utc();publish(run/'engine-status.json',status);time.sleep(.25 if ready else.5)
 finally:
  if process is not None and process.poll()is None:
   process.terminate()
   try:process.wait(timeout=5)
   except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)
  log.close();lock.close();status.update(state='stopped',stop_reason=reason,engine_exit=process.returncode if process else None);publish(run/'engine-status.json',status)
 return 0 if ready else 1
if __name__=='__main__':raise SystemExit(main())
