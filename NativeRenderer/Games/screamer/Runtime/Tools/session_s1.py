#!/usr/bin/env python3
"""Own a private original S1 engine + atomic bridge session for the native UI."""
import argparse,fcntl,hashlib,json,math,os,shutil,signal,socket,subprocess,sys,time,uuid
from pathlib import Path
from profile_s1 import EXE_SHA256,RAM_SIZE,executable_profile,resolve
from live_api import LiveAPI
from live_s1 import publish
from clock_shared import now_ns
from capture_s1 import configuration


def stop(process):
    if process is None or process.poll() is not None:return
    process.terminate()
    try:process.wait(timeout=5)
    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','game-root','scenes-root','data-dir','session-dir'):p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--parent-pid',type=int);p.add_argument('--port',type=int,default=0)
    p.add_argument('--max-seconds',type=float,default=0);p.add_argument('--audio',choices=['on','dummy'],default='on')
    p.add_argument('--diagnostic-read-only',action='store_true');a=p.parse_args()
    if not 0<=a.port<=65535 or not math.isfinite(a.max_seconds) or not 0<=a.max_seconds<=3600:raise ValueError('Invalid port/duration')
    if a.parent_pid is not None and a.parent_pid<=0:raise ValueError('Parent PID must be positive')
    a.engine=a.engine.resolve(strict=True);a.game_root=a.game_root.resolve(strict=True);a.scenes_root=a.scenes_root.resolve(strict=True)
    objects,fixups,_,_=executable_profile((a.game_root/'STARTH.EXE').read_bytes())
    a.data_dir=a.data_dir.resolve();a.session_dir=a.session_dir.resolve()
    for path in (a.data_dir,a.session_dir):
        if path==a.game_root or path in a.game_root.parents or a.game_root in path.parents:raise ValueError('Private output overlaps original game source')
        if any(c in str(path) for c in ('"','\n','\r')) or any(p.endswith('.app') for p in path.parts):raise ValueError('Private data must live outside application bundles')
    if a.session_dir==a.data_dir or a.session_dir in a.data_dir.parents or a.data_dir/'Game' in a.session_dir.parents:raise ValueError('Session/data paths overlap private game data')
    allowed_gui={'session.log','input.json','performance.json'}
    if a.session_dir.exists() and any(p.name not in allowed_gui or not p.is_file() or p.is_symlink() for p in a.session_dir.iterdir()):
        raise ValueError('Session already contains engine/bridge artifacts')
    owner=a.data_dir/'.screamer1-metal-owner.json'
    if a.data_dir.exists() and any(a.data_dir.iterdir()):
        if not owner.exists():raise ValueError('Data folder is not owned by S1 Metal')
        record=json.loads(owner.read_text())
        if record.get('application')!='Screamer1MetalExperimental' or record.get('profile_sha256')!=EXE_SHA256:raise ValueError('Data folder ownership/profile mismatch')
    a.data_dir.mkdir(parents=True,exist_ok=True);a.session_dir.mkdir(parents=True,exist_ok=True)
    lock=(a.data_dir/'.running.lock').open('a+b');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if not owner.exists():publish(owner,{'application':'Screamer1MetalExperimental','profile_sha256':EXE_SHA256})
    game=a.data_dir/'Game'
    if not game.exists():
        staging=a.data_dir/('.Game-copy-'+uuid.uuid4().hex)
        shutil.copytree(a.game_root,staging,copy_function=shutil.copyfile);staging.rename(game)
    if hashlib.sha256((game/'STARTH.EXE').read_bytes()).hexdigest()!=EXE_SHA256:raise ValueError('Private original changed')
    # Mount the unmodified owned disc from the read-only application resources.
    # Original relative SCREAM.gog path is resolved beside this CUE by DOSBox.
    cue=(a.game_root/'SCREAM.DAT').resolve()
    with socket.socket() as s:s.bind(('127.0.0.1',a.port));port=s.getsockname()[1]
    config=a.session_dir/'dosbox.conf';config.write_text(configuration(a.session_dir,game,cue,port))
    api=LiveAPI(f'http://127.0.0.1:{port}',timeout=.5)
    env=dict(os.environ,SCREAMER_METAL_BRIDGE='1',SDL_VIDEODRIVER='dummy',SDL_RENDER_DRIVER='software',PYTHONDONTWRITEBYTECODE='1',
             SDL_AUDIODRIVER='dummy' if a.audio=='dummy' else 'coreaudio')
    runtime=(a.session_dir/'runtime.log').open('wb');bridge_log=(a.session_dir/'bridge.log').open('wb')
    engine=bridge=None;stopping=False;started=time.monotonic();ready=False;error=None
    def requested(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,requested);signal.signal(signal.SIGINT,requested)
    direct_parent=os.getppid()
    def alive():
        if os.getppid()!=direct_parent:return False
        if a.parent_pid:
            try:os.kill(a.parent_pid,0)
            except ProcessLookupError:return False
        return True
    status={'profile':'screamer1-original','state':'starting','engine_pid':None,'bridge_pid':None,'api_base_url':api.origin,
        'physics_wait_ticks':2,'physics_patches':[],'input_diagnostic_disabled':a.diagnostic_read_only}
    now=now_ns()
    publish(a.session_dir/'state.json',{'schema':'screamer-live/v1','epoch':a.session_dir.name,'sequence':0,'seq':0,
        'status':'starting','mode':'framebuffer','running':True,'physics_period_ms':20,'sample_monotonic_ns':now,
        'published_monotonic_ns':now,'error':None})
    try:
        engine=subprocess.Popen([str(a.engine),'--noprimaryconf','--nolocalconf','--conf',str(config)],cwd=game,env=env,stdout=runtime,stderr=subprocess.STDOUT)
        command=[sys.executable,str(Path(__file__).with_name('live_s1.py')),'--base-url',api.origin,
            '--layout',str(a.session_dir/'layout.json'),'--state',str(a.session_dir/'state.json'),'--input',str(a.session_dir/'input.json'),
            '--game-root',str(a.game_root),'--scenes-root',str(a.scenes_root),'--cache-root',str(a.session_dir/'assets')]
        if a.parent_pid:command+=['--parent-pid',str(a.parent_pid)]
        if a.diagnostic_read_only:command+=['--diagnostic-read-only']
        bridge=subprocess.Popen(command,stdout=bridge_log,stderr=subprocess.STDOUT,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
        status.update(engine_pid=engine.pid,bridge_pid=bridge.pid);publish(a.session_dir/'engine-status.json',status)
        print(json.dumps({'session':str(a.session_dir),'endpoint':api.origin,'engine_pid':engine.pid,'bridge_pid':bridge.pid}),flush=True)
        while not stopping and alive() and engine.poll() is None and bridge.poll() is None and (not a.max_seconds or time.monotonic()-started<a.max_seconds):
            if not ready:
                try:
                    data,info=api.batch([(0,RAM_SIZE)],0,wait=False,full=True);ram=data[0]
                    loaded,evidence,markers,_=resolve(ram,objects,fixups)
                    metadata={'schema_version':1,'profile':'screamer1-software-v1','executable_sha256':EXE_SHA256,'runtime_executable_sha256':EXE_SHA256,
                        'physical_ram_base':0,'ram_size':RAM_SIZE,'pointer_bias':0,'objects':loaded,'object_resolution_evidence':evidence,
                        'markers':markers,'registers':info.get('registers'),'ram_sha256':hashlib.sha256(ram).hexdigest(),'engine_pid':engine.pid,
                        'epoch':a.session_dir.name,'physics_wait_ticks':2,'timer_frequency_hz':100,'api_base_url':api.origin}
                    publish(a.session_dir/'layout.json',metadata);ready=True;status['state']='ready';status.pop('last_error',None)
                    print('Original S1 live layout ready',flush=True)
                except (OSError,ValueError,KeyError) as e:status['last_error']=str(e)
                if not ready and time.monotonic()-started>70:raise RuntimeError('Original S1 layout startup timed out')
                publish(a.session_dir/'engine-status.json',status)
            time.sleep(.1 if ready else .5)
        if bridge.poll() not in (None,0):error=f'Bridge exited {bridge.returncode}'
        if engine.poll() not in (None,0):error=f'Engine exited {engine.returncode}'
    except Exception as e:error=str(e)
    finally:
        stop(bridge);stop(engine);runtime.close();bridge_log.close();lock.close()
        status.update(state='error' if error else 'stopped',error=error,engine_exit=engine.returncode if engine else None,bridge_exit=bridge.returncode if bridge else None)
        publish(a.session_dir/'engine-status.json',status)
    if error:print(error,file=sys.stderr)
    return 1 if error else 0


if __name__=='__main__':raise SystemExit(main())
