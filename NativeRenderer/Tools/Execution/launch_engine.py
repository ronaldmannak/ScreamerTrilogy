#!/usr/bin/env python3
"""Isolated live Rally engine lifecycle. No scripted input or GUI automation."""

import argparse
import base64
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time
import urllib.request
import uuid

import capture_probe as profile

OWNER = 'ScreamerMetalExperimental'


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    os.replace(temporary, path)


def read_api(base, path, json_response=False):
    request = urllib.request.Request(base + path, headers={
        'Accept': 'application/json' if json_response else 'application/octet-stream'}, method='GET')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=2) as response:
        return json.load(response) if json_response else response.read()


def addresses(objects):
    def link(va):
        for obj in objects:
            if obj['link_base'] <= va < obj['link_base'] + obj['virtual_size']:
                return obj['physical_base'] + va - obj['link_base']
        raise ValueError(f'No mapped LE object for {va:#x}')
    return {
        'wait_helper': link(0x504dc), 'pending_ticks': link(0x50512),
        'menu_return': link(0x4f6f1), 'race_return': link(0x4f793),
        'real_clock': link(0x1469d0), 'simulation_clock': link(0x1469d4),
        'keyboard_isr': link(0x502fc), 'keyboard_table': link(0x50330),
        'keyboard_copy': link(0x503b0), 'keyboard_frame_table': link(0x110002),
        'setup': link(0x1435bc), 'race_flags': link(0x13146c),
        'rows': link(0x123720), 'models': link(0x147390), 'camera': link(0x81e0c),
    }


def phase_marker(base, fields):
    """A conservative wait-phase sample; bridge performs full pose coherence checks."""
    result = read_api(base, f"/api/v1/memory/{fields['wait_helper']}/64", True)
    memory = base64.b64decode(result['memory']['data'], validate=True)
    regs = result['registers']
    phase = 'working-or-loading'
    if regs['eip'] - fields['wait_helper'] in (1, 6, 9) and memory[8] == 3:
        caller = struct.unpack('<I', read_api(base, f"/api/v1/memory/{regs['esp'] + 4}/4"))[0]
        if caller == fields['menu_return']:
            phase = 'menu-wait'
        elif caller == fields['race_return']:
            phase = 'race-wait'
    return {'phase': phase, 'eip': regs['eip'], 'esp': regs['esp'],
            'pending_ticks': struct.unpack_from('<I', memory, 0x36)[0]}


def world_state(base, fields):
    setup = read_api(base, f"/api/v1/memory/{fields['setup']}/380")
    count, track, condition, detail = struct.unpack_from('<4I', setup)
    car_models = [struct.unpack_from('<I', setup, 0x10 + i * 0x2c + 4)[0]
                  for i in range(min(count, 6))]
    pointers = {}
    for name in ('rows', 'models', 'camera'):
        pointers[name] = struct.unpack('<I', read_api(base, f"/api/v1/memory/{fields[name]}/4"))[0]
    valid = (1 <= count <= 8 and 0 <= track <= 6 and 0 <= condition <= 2 and
             detail <= 2 and all(0x10000 <= p < profile.RAM_BYTES - 256 for p in pointers.values()))
    key = hashlib.sha256(json.dumps([track, condition, detail, car_models, pointers['rows'],
                                    pointers['models']], separators=(',', ':')).encode()).hexdigest()[:20]
    return {'valid': valid, 'key': key, 'track_id': track, 'condition': condition,
            'detail': detail, 'car_count': count, 'car_models': car_models, 'pointers': pointers}


def make_metadata(memory, registers, before, after, objects, evidence, markers, source, engine, epoch, base):
    return {'schema_version': 1, 'epoch': epoch, 'executable_sha256': profile.EXPECTED_SHA,
            'runtime_executable_sha256': profile.EXPECTED_RUNTIME_SHA,
            'ram_sha256': hashlib.sha256(memory).hexdigest(), 'physical_ram_base': 0,
            'ram_size': len(memory), 'pointer_bias': 0, 'captured_utc': utc(),
            'monotonic_ns': after, 'capture_started_monotonic_ns': before,
            'capture_duration_ms': (after - before) / 1e6, 'objects': objects,
            'object_resolution_evidence': evidence, 'markers': markers, 'registers': registers,
            'source_executable': str(source), 'engine': str(engine), 'api_base_url': base,
            'address_space': 'DOSBox MEM_BlockRead flat address space',
            'limitations': 'CPU-step snapshot, not a logical simulation boundary; boot may precede world loading.'}


def configuration(game, cue, video, port, run):
    return f'''[sdl]
fullscreen = false
window_size = 1280x960
output = {'texture' if video == 'hidden' else 'opengl'}
[dosbox]
machine = svga_s3
memsize = 16
[cpu]
core = auto
cpu_cycles = 3000
cpu_cycles_protected = max
[render]
aspect = on
[dos]
shell_history_file =
[capture]
capture_dir = {run}/capture
[midi]
mididevice = none
[sblaster]
sbtype = sb16
sbbase = 220
irq = 7
dma = 1
hdma = 5
[voodoo]
voodoo = on
voodoo_memsize = 4
voodoo_threads = auto
[webserver]
webserver_enabled = on
webserver_bind_address = 127.0.0.1
webserver_port = {port}
[autoexec]
@echo off
mount c "."
imgmount d "{cue}" -t iso
c:
cd SR
NATIVE3D.EXE
exit
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', required=True, type=Path)
    parser.add_argument('--game-root', required=True, type=Path)
    parser.add_argument('--disc-cue', type=Path)
    parser.add_argument('--data-dir', required=True, type=Path, help='Persistent isolated ScreamerMetal data, never the working wrapper save folder')
    parser.add_argument('--session-dir', type=Path, help='Shared per-GUI-session folder; publishes layout.json and engine-status.json')
    parser.add_argument('--parent-pid', type=int, help='GUI process to monitor in addition to the direct launcher parent')
    parser.add_argument('--port', type=int, default=9091)
    parser.add_argument('--video', choices=('hidden', 'window'), default='hidden')
    parser.add_argument('--audio', choices=('on', 'dummy'), default='on')
    parser.add_argument('--max-seconds', type=float, default=0, help='0 runs until requested stop; use a finite value for diagnostics')
    parser.add_argument('--startup-timeout', type=float, default=70)
    parser.add_argument('--extractor', type=Path, help='Optional external extract_track.py; run on validated track/condition/model changes')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    profile.require(1 <= args.port <= 65535 and args.max_seconds >= 0 and args.startup_timeout > 0, 'Invalid port or duration')
    data = args.data_dir.expanduser().resolve()
    profile.require('Screamer Native' not in data.parts, 'Use a separate ScreamerMetal data folder, not working wrapper saves')
    profile.require(not any(c in str(data) for c in ('"', '\r', '\n')), 'Unsupported quote/newline in data path')
    owner_path = data / '.screamer-metal-owner.json'
    if data.exists() and any(data.iterdir()):
        profile.require(owner_path.exists(), 'Existing nonempty data folder is not owned by ScreamerMetal')
        owner = json.loads(owner_path.read_text())
        profile.require(owner.get('application') == OWNER and owner.get('source_sha256') == profile.EXPECTED_SHA, 'Data-folder ownership/profile mismatch')
    epoch = uuid.uuid4().hex
    run = args.session_dir.expanduser().resolve() if args.session_dir else data / 'runs' / epoch
    profile.require(not any(c in str(run) for c in ('"', '\r', '\n')), 'Unsupported quote/newline in session path')
    profile.require(not (run / 'layout.json').exists(), 'Session already has a published layout; use a new GUI session directory')
    args.output = run / ('.preflight-' + epoch)
    engine, game_root, source, cue, original, patched, le_objects, fixups, _, _ = profile.preflight(args)
    if args.check_only:
        print(json.dumps({'check_only': True, 'data_dir': str(data), 'epoch_would_be': epoch,
                          'runtime_sha256': hashlib.sha256(patched).hexdigest(), 'audio': args.audio,
                          'video': args.video, 'physics_wait_ticks': 3}, indent=2))
        return 0
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(('127.0.0.1', args.port))
    data.mkdir(parents=True, exist_ok=True)
    lock = (data / '.running.lock').open('a+b')
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    if not owner_path.exists():
        atomic_json(owner_path, {'application': OWNER, 'schema_version': 1,
                                'source_sha256': profile.EXPECTED_SHA, 'created_utc': utc()})
    game = data / 'Game'
    if not game.exists():
        staging = data / ('.game-staging-' + epoch)
        staging.mkdir()
        shutil.copytree(game_root / 'SR', staging / 'SR')
        os.replace(staging, game)
    profile.require(hashlib.sha256((game / 'SR/STRT3FX.EXE').read_bytes()).hexdigest() == profile.EXPECTED_SHA,
                    'Isolated original executable changed; refusing launch')
    profile.require(hashlib.sha256((game / 'SR/GLIDE2X.OVL').read_bytes()).hexdigest() == profile.EXPECTED_OVL_SHA,
                    'Isolated DOS Glide driver changed; refusing launch')
    temporary_exe = game / 'SR' / ('.NATIVE3D-' + epoch)
    temporary_exe.write_bytes(patched)
    os.replace(temporary_exe, game / 'SR/NATIVE3D.EXE')
    run.mkdir(parents=True, exist_ok=True)
    config = run / 'dosbox.conf'
    config.write_text(configuration(game, cue, args.video, args.port, run))
    base = f'http://127.0.0.1:{args.port}'
    status_path = run / 'engine-status.json'
    status = {'schema_version': 1, 'epoch': epoch, 'state': 'starting', 'api_base_url': base,
              'launcher_pid': os.getpid(), 'engine_pid': None, 'data_dir': str(data),
              'run_dir': str(run), 'session_dir': str(run), 'layout_path': str(run / 'layout.json'),
              'ram_path': str(run / 'boot-ram.bin'), 'video': args.video, 'audio': args.audio,
              'physics_wait_ticks': 3, 'updated_utc': utc()}
    atomic_json(status_path, status)
    environment = os.environ.copy()
    environment['SCREAMER_METAL_BRIDGE'] = '1'
    if args.video == 'hidden':
        environment.update(SDL_VIDEODRIVER='dummy', SDL_RENDER_DRIVER='software')
    else:
        environment.pop('SDL_VIDEODRIVER', None)
        environment.pop('SDL_RENDER_DRIVER', None)
    if args.audio == 'dummy':
        environment['SDL_AUDIODRIVER'] = 'dummy'
    else:
        environment['SDL_AUDIODRIVER'] = 'coreaudio' if sys.platform == 'darwin' else environment.get('SDL_AUDIODRIVER', '')
        if not environment['SDL_AUDIODRIVER']:
            environment.pop('SDL_AUDIODRIVER')
    stopping = False
    def request_stop(_signal, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    parent = os.getppid()
    def parent_alive():
        if os.getppid() != parent:
            return False
        if args.parent_pid:
            try:
                os.kill(args.parent_pid, 0)
            except ProcessLookupError:
                return False
        return True
    started = time.monotonic()
    ready = False
    fields = None
    known_world = None
    stable_world = 0
    previous_key = None
    extraction = None
    reason = 'engine-exited'
    with (run / 'runtime.log').open('wb') as log:
        process = subprocess.Popen([str(engine), '--noprimaryconf', '--nolocalconf', '--conf', str(config)],
                                   cwd=game, env=environment, stdout=log, stderr=subprocess.STDOUT)
        status['engine_pid'] = process.pid
        atomic_json(status_path, status)
        print(json.dumps({'engine_state': str(status_path), 'epoch': epoch, 'engine_pid': process.pid,
                          'api_base_url': base}), flush=True)
        try:
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if stopping or not parent_alive() or (args.max_seconds and elapsed >= args.max_seconds):
                    reason = 'requested-stop' if stopping else 'parent-exited' if not parent_alive() else 'duration-limit'
                    break
                if not ready:
                    if elapsed >= args.startup_timeout:
                        reason = 'layout-startup-timeout'
                        break
                    try:
                        memory, registers, before, after = profile.read_snapshot(base, time.monotonic() + 2)
                        objects, evidence, markers = profile.resolve(memory, le_objects, fixups, require_world=False)
                        fields = addresses(objects)
                        meta = make_metadata(memory, registers, before, after, objects, evidence, markers, source, engine, epoch, base)
                        meta.update(fields=fields, engine_pid=process.pid, session_id=epoch,
                                    session_dir=str(run), runtime_guest_sha256=profile.EXPECTED_RUNTIME_SHA)
                        profile.write_new(run / 'boot-ram.bin', memory)
                        profile.write_json_new(run / 'layout.json', meta)
                        status.update(state='ready', metadata_path=str(run / 'layout.json'),
                                      ram_path=str(run / 'boot-ram.bin'), fields=fields)
                        status.pop('last_error', None)
                        ready = True
                        print('Live engine layout ready', flush=True)
                    except Exception as error:
                        status['last_error'] = str(error)[:500]
                else:
                    try:
                        phase = phase_marker(base, fields)
                        status['phase'] = phase
                        if phase['phase'] == 'race-wait':
                            world = world_state(base, fields)
                            status['world'] = world
                            if world['valid'] and world['key'] == previous_key:
                                stable_world += 1
                            else:
                                stable_world = 0
                            previous_key = world['key'] if world['valid'] else None
                            if args.extractor and stable_world >= 2 and world['key'] != known_world and extraction is None:
                                memory, registers, before, after = profile.read_snapshot(base, time.monotonic() + 2)
                                objects, evidence, markers = profile.resolve(memory, le_objects, fixups)
                                if world_state(base, fields)['key'] == world['key']:
                                    folder = run / 'worlds' / (world['key'] + '-' + uuid.uuid4().hex[:8])
                                    folder.mkdir(parents=True)
                                    meta = make_metadata(memory, registers, before, after, objects, evidence, markers, source, engine, epoch, base)
                                    meta['world'] = world
                                    profile.write_new(folder / 'guest-ram.bin', memory)
                                    profile.write_json_new(folder / 'metadata.json', meta)
                                    status['world_capture'] = {'key': world['key'], 'ram': str(folder / 'guest-ram.bin'), 'metadata': str(folder / 'metadata.json')}
                                    known_world = world['key']
                                    if args.extractor:
                                        extractor = profile.checked_path(args.extractor, 'Extractor')
                                        extraction_log = (folder / 'extractor.log').open('wb')
                                        job = subprocess.Popen([sys.executable, str(extractor), '--ram', str(folder / 'guest-ram.bin'),
                                            '--metadata', str(folder / 'metadata.json'), '--output', str(folder / 'assets'),
                                            '--textures', '--executable', str(source)], stdout=extraction_log, stderr=subprocess.STDOUT)
                                        extraction = (job, extraction_log, folder, world['key'])
                        if extraction and extraction[0].poll() is not None:
                            job, job_log, folder, key = extraction
                            job_log.close()
                            status['assets'] = {'key': key, 'directory': str(folder / 'assets'), 'exit_code': job.returncode}
                            extraction = None
                    except Exception as error:
                        status['last_error'] = str(error)[:500]
                status['updated_utc'] = utc()
                atomic_json(status_path, status)
                time.sleep(0.25 if ready else 0.5)
        finally:
            if extraction:
                extraction[0].terminate()
                try:
                    extraction[0].wait(timeout=2)
                except subprocess.TimeoutExpired:
                    extraction[0].kill()
                    extraction[0].wait(timeout=2)
                extraction[1].close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            status.update(state='stopped', stop_reason=reason, engine_exit=process.returncode, updated_utc=utc())
            atomic_json(status_path, status)
            lock.close()
            print(json.dumps({'state': 'stopped', 'reason': reason, 'engine_exit': process.returncode}), flush=True)
    return 0 if ready else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(f'Engine launch failed: {error}', file=sys.stderr)
        raise SystemExit(1)
