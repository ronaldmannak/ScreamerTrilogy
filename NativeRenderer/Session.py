#!/usr/bin/env python3
"""Own one live Rally engine/bridge session for the native macOS frontend."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent/'bridge'))
from clock_shared import now_ns

def publish(path,value):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,separators=(',',':'))+'\n')
    os.replace(temporary,path)

def stop_process(process):
    if process is None or process.poll() is not None:return
    process.terminate()
    try:process.wait(timeout=7)
    except subprocess.TimeoutExpired:
        process.kill();process.wait(timeout=3)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resources',type=Path,required=True)
    parser.add_argument('--session-dir',type=Path,required=True)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--parent-pid',type=int,required=True)
    args=parser.parse_args()
    resources=args.resources.resolve(strict=True);session=args.session_dir.resolve()
    content=Path(os.environ.get('SCREAMER_CONTENT_ROOT',str(resources))).resolve(strict=True)
    session.mkdir(parents=True,exist_ok=True)
    live=resources/'Live';state=session/'state.json'
    engine=resources.parent/'MacOS/dosbox'
    status={'schema':'screamer-live/v1','epoch':session.name,'sequence':0,'seq':0,
            'status':'starting','mode':'framebuffer','running':True,
            'physics_period_ms':30,'sample_monotonic_ns':now_ns(),'published_monotonic_ns':now_ns(),
            'error':None}
    publish(state,status)
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as port_socket:
        port_socket.bind(('127.0.0.1',0));port=port_socket.getsockname()[1]
    children=[];logs=[];stopping=False
    def requested_stop(_signum,_frame):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,requested_stop);signal.signal(signal.SIGINT,requested_stop)
    def spawn(script,arguments,label):
        log=(session/(label+'.log')).open('wb');logs.append(log)
        environment=os.environ.copy()
        environment.update(PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1')
        process=subprocess.Popen([sys.executable,str(script),*map(str,arguments)],
                                 cwd=live,env=environment,stdout=log,stderr=subprocess.STDOUT)
        children.append(process);return process
    error=None
    try:
        engine_process=spawn(live/'Execution/launch_engine.py',[
            '--engine',engine,'--game-root',content/'game','--data-dir',args.data_dir,
            '--session-dir',session,'--parent-pid',args.parent_pid,'--port',port], 'engine-launcher')
        bridge_args=['--base-url',f'http://127.0.0.1:{port}','--layout',session/'layout.json',
                     '--state',state,'--input',session/'input.json','--cache-root',session/'assets',
                     '--extractor-dir',live/'extractor','--parent-pid',args.parent_pid,
                     '--poll-hz','100','--frame-hz','30','--game-root',content/'game/SR']
        profile=live/'hud-profile.json'
        if profile.is_file():bridge_args+=['--hud-profile',profile]
        bridge_process=spawn(live/'bridge/live_bridge.py',bridge_args,'bridge')
        publish(session/'session-info.json',{'engine_launcher_pid':engine_process.pid,
            'bridge_pid':bridge_process.pid,'gui_pid':args.parent_pid,'port':port,
            'data_dir':str(args.data_dir),'started_utc':time.time()})
        while not stopping:
            try:os.kill(args.parent_pid,0)
            except ProcessLookupError:break
            if engine_process.poll() is not None:
                if engine_process.returncode:error=f'Game engine exited ({engine_process.returncode}). See engine-launcher.log and runtime.log.'
                break
            if bridge_process.poll() is not None:
                error=f'Live bridge exited ({bridge_process.returncode}). See bridge.log.'
                break
            time.sleep(.1)
    except Exception as exception:
        error=str(exception)
    finally:
        # Stop the input bridge first so it can release keys while the CPU runs.
        for process in reversed(children):stop_process(process)
        for log in logs:log.close()
        try:status=json.loads(state.read_text())
        except (OSError,ValueError):pass
        status.update(running=False,status='error' if error else 'stopped',error=error,
                      sequence=status.get('sequence',0)+1,seq=status.get('seq',0)+1,
                      published_monotonic_ns=now_ns())
        publish(state,status)
    if error:print(error,file=sys.stderr)
    return 1 if error else 0

if __name__=='__main__':raise SystemExit(main())
