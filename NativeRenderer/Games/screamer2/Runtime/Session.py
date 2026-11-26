#!/usr/bin/env python3
"""Own one isolated Screamer2 engine/bridge session; original two-tick timing."""
from pathlib import Path
import argparse,json,os,signal,socket,subprocess,sys,time
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent/'bridge'))
from clock_shared import now_ns

def publish(path,value):
 temp=path.with_name('.'+path.name+'.tmp');temp.write_text(json.dumps(value,separators=(',',':'))+'\n');os.replace(temp,path)
def stop_process(process):
 if process is None or process.poll()is not None:return
 process.terminate()
 try:process.wait(timeout=7)
 except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--resources',type=Path)
 p.add_argument('--session-dir',type=Path,required=True);p.add_argument('--data-dir',type=Path,required=True);p.add_argument('--parent-pid',type=int)
 p.add_argument('--engine',type=Path);p.add_argument('--game-root',type=Path);p.add_argument('--ovl',type=Path);p.add_argument('--extractor-dir',type=Path)
 p.add_argument('--max-seconds',type=float,default=0);p.add_argument('--audio',choices=('on','dummy'),default='on');p.add_argument('--read-only',action='store_true')
 a=p.parse_args()
 if not(0<=a.max_seconds<=86400)or(a.parent_pid is not None and a.parent_pid<=1)or(not a.parent_pid and not 0<a.max_seconds<=600):p.error('Require a GUI parent or a bounded diagnostic duration<=600s')
 resources=a.resources.resolve()if a.resources else None;live=resources/'Live'if resources else Path(__file__).resolve().parent
 content=Path(os.environ.get('SCREAMER_CONTENT_ROOT',str(resources))).resolve(strict=True) if resources else None
 engine=a.engine or(resources.parent/'MacOS/dosbox'if resources else Path('/private/tmp/rally-live/Engine/cmake-build/dosbox'))
 game=a.game_root or(content/'game'if resources else Path('/Applications/Screamer 2.app/Contents/Resources/game'))
 ovl=a.ovl or(game/'GLIDE2X.OVL'if resources else Path('/Applications/Screamer Rally.app/Contents/Resources/game/SR/GLIDE2X.OVL'))
 extractor=a.extractor_dir or(live/'extractor'if resources else Path('/private/tmp/screamer-4k-research/S2-renderer/extractor'))
 session=a.session_dir.resolve();session.mkdir(parents=True,exist_ok=True)
 if(session/'layout.json').exists():p.error('Use a fresh session directory')
 stamp=now_ns()
 state_path=session/'state.json';state={'schema':'screamer-live/v1','epoch':session.name,'seq':0,'sequence':0,'status':'starting','mode':'framebuffer','running':True,'physics_period_ms':20,'sample_monotonic_ns':stamp,'published_monotonic_ns':stamp,'error':None}
 publish(state_path,state)
 with socket.socket()as reservation:reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
 children=[];logs=[];stopping=False
 def stop(*unused):nonlocal stopping;stopping=True
 signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
 def spawn(script,args,label):
  log=(session/(label+'.log')).open('wb');logs.append(log);env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1')
  child=subprocess.Popen([sys.executable,'-B',str(script),*map(str,args)],cwd=live,env=env,stdout=log,stderr=subprocess.STDOUT);children.append(child);return child
 error=None;start=time.monotonic()
 try:
  launch_args=['--engine',engine,'--game-root',game,'--ovl',ovl,'--data-dir',a.data_dir,'--session-dir',session,'--port',port,'--max-seconds',a.max_seconds,'--audio',a.audio]
  bridge_args=['--base-url',f'http://127.0.0.1:{port}','--layout',session/'layout.json','--state',state_path,'--input',session/'input.json','--cache-root',session/'assets','--extractor-dir',extractor,'--seconds',a.max_seconds,'--game-root',game]
  if a.parent_pid:launch_args+=['--parent-pid',a.parent_pid];bridge_args+=['--parent-pid',a.parent_pid]
  if a.read_only:bridge_args+=['--read-only']
  if(live/'hud-profile.json').is_file():bridge_args+=['--hud-profile',live/'hud-profile.json']
  launcher=spawn(live/'Execution/launch_engine.py',launch_args,'engine-launcher');bridge=spawn(live/'bridge/live_bridge.py',bridge_args,'bridge')
  info={'profile':'screamer2-3dfx-v1','port':port,'api_base_url':f'http://127.0.0.1:{port}','engine_launcher_pid':launcher.pid,'bridge_pid':bridge.pid,'gui_pid':a.parent_pid,'session_pid':os.getpid(),'data_dir':str(a.data_dir),'read_only':a.read_only,'maximum_seconds':a.max_seconds,'state':str(state_path)}
  publish(session/'session-info.json',info);print(json.dumps(info),flush=True)
  while not stopping:
   if a.max_seconds and time.monotonic()-start>=a.max_seconds:break
   if a.parent_pid:
    try:os.kill(a.parent_pid,0)
    except ProcessLookupError:break
   if launcher.poll()is not None:
    if launcher.returncode:error=f'S2 engine launcher exited{launcher.returncode}; see engine-launcher.log/runtime.log'
    break
   if bridge.poll()is not None:
    if bridge.returncode:error=f'S2 bridge exited{bridge.returncode}; see bridge.log'
    break
   time.sleep(.1)
 except Exception as exc:error=str(exc)
 finally:
  for child in reversed(children):stop_process(child)
  for log in logs:log.close()
  try:state=json.loads(state_path.read_text())
  except (OSError,ValueError):pass
  state.update(running=False,status='error'if error else'stopped',error=error,seq=state.get('seq',0)+1,sequence=state.get('sequence',0)+1,published_monotonic_ns=now_ns());publish(state_path,state)
 if error:print(error,file=sys.stderr)
 return 1 if error else 0
if __name__=='__main__':raise SystemExit(main())
