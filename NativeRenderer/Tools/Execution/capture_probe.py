#!/usr/bin/env python3
"""Bounded isolated STRT3FX load and read-only RAM capture; no input API."""

from pathlib import Path
import argparse
import base64
import collections
import datetime
import hashlib
import json
import os
import shutil
import socket
import sys
import struct
import subprocess
import time
import urllib.request

EXPECTED_SHA = '9eac6e12ab309389bdda019cfa695bfbbc791fbda1a4634464a444fce35165d1'
EXPECTED_OVL_SHA = '6981a7bd77445be7b360ca367af1e527927db396546db15b69803b16a67676a9'
EXPECTED_RUNTIME_SHA = '2fd67bfeb387558da4952dcd8442864e869e67ca5ef39793526cafd34358b9d4'
RAM_BYTES = 16 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write_new(path, data):
    """Never replace a previously published capture, even within one run."""
    with path.open('xb') as output:
        output.write(data)


def write_json_new(path, value):
    write_new(path, (json.dumps(value, indent=2) + '\n').encode('utf-8'))


def u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def parse_le(data):
    le = u32(data, 0x3c)
    require(data[le:le + 4] == b'LE\0\0', 'Expected a DOS/4GW LE executable')
    page_size = u32(data, le + 0x28)
    data_start = u32(data, le + 0x80)
    object_table = le + u32(data, le + 0x40)
    page_map = le + u32(data, le + 0x48)
    objects = []
    physical_pages = {}
    for index in range(u32(data, le + 0x44)):
        size, base, flags, first, count, _ = struct.unpack_from('<6I', data, object_table + index * 24)
        obj = {'index': index + 1, 'link_base': base, 'virtual_size': size, 'flags': flags, 'pages': []}
        for p in range(count):
            entry = page_map + (first - 1 + p) * 4
            physical = int.from_bytes(data[entry:entry + 3], 'big')
            page_flags = data[entry + 3]
            obj['pages'].append((physical, page_flags))
            if physical and page_flags == 0:
                physical_pages[physical - 1] = (index + 1, p * page_size)
        objects.append(obj)
    records = []
    fp = le + u32(data, le + 0x68)
    fr = le + u32(data, le + 0x6c)
    for page in range(u32(data, le + 0x14)):
        pos, end = fr + u32(data, fp + page * 4), fr + u32(data, fp + (page + 1) * 4)
        while pos < end:
            src, flags = data[pos:pos + 2]
            pos += 2
            if src & 0x20:
                count = data[pos]
                pos += 1
                single = None
            else:
                count = None
                single = struct.unpack_from('<h', data, pos)[0]
                pos += 2
            width = 2 if flags & 0x40 else 1
            target_obj = int.from_bytes(data[pos:pos + width], 'little')
            pos += width
            target_offset = None
            if flags & 3 == 0 and src & 15 != 2:
                width = 4 if flags & 0x10 else 2
                target_offset = int.from_bytes(data[pos:pos + width], 'little')
                pos += width
            if flags & 4:
                pos += 4 if flags & 0x20 else 2
            if count is not None:
                offsets = [struct.unpack_from('<h', data, pos + i * 2)[0] for i in range(count)]
                pos += count * 2
            else:
                offsets = [single]
            if page not in physical_pages:
                continue
            source_obj, object_page_offset = physical_pages[page]
            if src & 15 == 7 and flags & 7 == 0 and target_offset is not None:
                for offset in offsets:
                    records.append({'source_object': source_obj, 'source_offset': object_page_offset + offset,
                                    'target_object': target_obj, 'target_offset': target_offset})
    return objects, records, page_size, data_start


def map_file(objects, page_size, data_start, va):
    obj = next(o for o in objects if o['link_base'] <= va < o['link_base'] + o['virtual_size'])
    relative = va - obj['link_base']
    physical, flags = obj['pages'][relative // page_size]
    require(physical and flags == 0, 'Patch target is not backed by a legal file page')
    return data_start + (physical - 1) * page_size + relative % page_size


def read_snapshot(base_url, deadline):
    request = urllib.request.Request(base_url + f'/api/v1/memory/0/{RAM_BYTES}',
                                     headers={'Accept': 'application/json'}, method='GET')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    before = time.monotonic_ns()
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Probe time budget expired')
    with opener.open(request, timeout=min(10, remaining)) as response:
        result = json.load(response)
    memory = base64.b64decode(result['memory']['data'], validate=True)
    require(result['memory']['addr'] == 0 and len(memory) == RAM_BYTES, 'Unexpected memory snapshot bounds')
    return memory, result['registers'], before, time.monotonic_ns()


def resolve(memory, objects, records, require_world=True):
    signature_tail = bytes.fromhex('83f8037cf658c3')
    matches = []
    start = 0
    while True:
        cmp_at = memory.find(signature_tail, start)
        if cmp_at < 0:
            break
        start = cmp_at + 1
        helper = cmp_at - 6
        if helper >= 0 and memory[helper:helper + 2] == b'\x50\xa1' and u32(memory, helper + 2) == helper + 0x36:
            matches.append(helper)
    require(len(matches) == 1, f'Expected one loaded relocated STRT3FX wait helper, got {matches}')
    code_base = matches[0] - (0x504dc - 0x20000)
    bases = {2: code_base}
    evidence = {}
    for target in objects:
        votes = collections.Counter()
        refs = collections.defaultdict(list)
        for record in records:
            if record['source_object'] != 2 or record['target_object'] != target['index']:
                continue
            location = code_base + record['source_offset']
            if not 0 <= location <= len(memory) - 4:
                continue
            actual = u32(memory, location)
            candidate = actual - record['target_offset']
            if candidate >= 0 and candidate + target['virtual_size'] <= len(memory) and candidate % 16 == 0:
                votes[candidate] += 1
                refs[candidate].append({'physical_operand': location, 'target_offset': record['target_offset']})
        if votes:
            candidate, count = votes.most_common(1)[0]
            if target['index'] == 2:
                require(candidate == code_base, 'Conflicting code-object relocation evidence')
            if count >= 2 or target['index'] == 2:
                bases[target['index']] = candidate
                evidence[str(target['index'])] = {'matching_fixups': count, 'alternatives': len(votes),
                                                  'examples': refs[candidate][:5]}
    require(6 in bases, 'Data object could not be resolved')
    def physical(va):
        obj = next(o for o in objects if o['link_base'] <= va < o['link_base'] + o['virtual_size'])
        return bases[obj['index']] + va - obj['link_base']
    markers = {}
    for name, va in [('rows', 0x123720), ('models', 0x147390), ('scene', 0x12f860),
                     ('camera', 0x81e0c), ('texture_records', 0x1479d4)]:
        address = physical(va)
        markers[name] = {'link_address': va, 'physical_address': address, 'u32': u32(memory, address),
                         'first_28_bytes_hex': memory[address:address + 28].hex()}
    valid_pointer = lambda name: 0x10000 <= markers[name]['u32'] < len(memory) - 256
    if require_world:
        require(all(valid_pointer(name) for name in ('rows', 'models')), f'World not ready: {markers}')
    loaded = [{'index': o['index'], 'link_base': o['link_base'], 'physical_base': bases[o['index']],
               'virtual_size': o['virtual_size']} for o in objects if o['index'] in bases]
    return loaded, evidence, markers



def checked_path(path, label):
    resolved = path.expanduser().resolve(strict=True)
    require(not any(c in str(resolved) for c in ('"', '\r', '\n')), f'{label} contains an unsupported quote or newline')
    return resolved


def preflight(args):
    engine = checked_path(args.engine, 'Engine path')
    game_root = checked_path(args.game_root, 'Game root')
    require(engine.is_file() and os.access(engine, os.X_OK), 'Engine must be an executable DOSBox Staging 0.83.1 binary')
    require(game_root.is_dir(), 'Game root must be a directory containing SR and cd')
    source_path = checked_path(game_root / 'SR/STRT3FX.EXE', 'Game executable')
    ovl_path = checked_path(game_root / 'SR/GLIDE2X.OVL', 'DOS Glide driver')
    disc_cue = checked_path(args.disc_cue or game_root / 'cd/srally.cue', 'Disc cue')
    require(disc_cue.is_file(), 'Disc cue must be a file')
    source = source_path.read_bytes()
    require(hashlib.sha256(source).hexdigest() == EXPECTED_SHA, 'Unsupported STRT3FX.EXE SHA-256; no files or process were changed')
    require(hashlib.sha256(ovl_path.read_bytes()).hexdigest() == EXPECTED_OVL_SHA, 'Unsupported GLIDE2X.OVL SHA-256; this tool requires the verified DOS driver')
    objects, records, page_size, data_start = parse_le(source)
    offset = map_file(objects, page_size, data_start, 0x504e2)
    require(offset == 0x556e2 and source[offset:offset + 3] == bytes.fromhex('83f801'), 'Timing patch offset/bytes do not match the supported profile')
    context = map_file(objects, page_size, data_start, 0x504dc)
    require(source[context:context + 13] == bytes.fromhex('50a11205030083f8017cf658c3'), 'Timing helper context does not match')
    patched = bytearray(source)
    patched[offset:offset + 3] = bytes.fromhex('83f803')
    require(hashlib.sha256(patched).hexdigest() == EXPECTED_RUNTIME_SHA, 'Timing-only output hash does not match')
    require([i for i, (a, b) in enumerate(zip(source, patched)) if a != b] == [0x556e4], 'Unexpected changes outside the one-byte timer immediate')
    root = args.output.expanduser().resolve()
    require(not any(c in str(root) for c in ('"', '\r', '\n')), 'Output path contains an unsupported quote or newline')
    require(not root.exists(), 'Output directory already exists; select a new per-session path to preserve captures')
    return engine, game_root, source_path, disc_cue, source, patched, objects, records, offset, root


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', required=True, type=Path, help='External DOSBox Staging 0.83.1 executable')
    parser.add_argument('--game-root', required=True, type=Path, help='Owned game directory containing SR/STRT3FX.EXE, SR/GLIDE2X.OVL and cd/srally.cue')
    parser.add_argument('--output', required=True, type=Path, help='New, nonexistent directory for this immutable capture session')
    parser.add_argument('--disc-cue', type=Path, help='External disc cue override; otherwise GAME_ROOT/cd/srally.cue')
    parser.add_argument('--port', type=int, default=9091, help='Loopback-only diagnostic port (default: 9091)')
    parser.add_argument('--hold-seconds', type=float, default=0, help='Keep read-only endpoint available after capture, 0..45 seconds; total run budget 90 seconds')
    parser.add_argument('--check-only', action='store_true', help='Validate paths, hashes and in-memory timing patch without creating output or starting DOSBox')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Port must be between 1 and 65535')
    if not 0 <= args.hold_seconds <= 45:
        parser.error('--hold-seconds must be between 0 and 45')
    return args


def main():
    args = parse_args()
    engine, game_root, source_path, disc_cue, source, patched, objects, records, offset, root = preflight(args)
    if args.check_only:
        print(json.dumps({'check_only': True, 'source_sha256': EXPECTED_SHA,
                          'runtime_sha256': EXPECTED_RUNTIME_SHA, 'glide_driver_sha256': EXPECTED_OVL_SHA,
                          'patch_raw_offset': offset, 'changed_byte_raw_offset': 0x556e4,
                          'expected_hex': '83f801', 'replacement_hex': '83f803',
                          'output_would_be': str(root)}, indent=2))
        return 0
    # Reserve the caller-selected port before starting a new guest, so an occupied
    # diagnostic endpoint cannot be mistaken for this process's emulator.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(('127.0.0.1', args.port))
    root.mkdir(parents=True, exist_ok=False)
    base_url = f'http://127.0.0.1:{args.port}'
    game = root / 'Game'
    game.mkdir()
    shutil.copytree(game_root / 'SR', game / 'SR')
    (game / 'SR/NATIVE3D.EXE').write_bytes(patched)
    config = f'''[sdl]\nfullscreen = false\nwindow_size = 640x480\noutput = texture\n[dosbox]\nmachine = svga_s3\nmemsize = 16\n[cpu]\ncore = auto\ncpu_cycles = 3000\ncpu_cycles_protected = max\n[render]\naspect = on\n[dos]\nshell_history_file =\n[capture]\ncapture_dir = {root}/capture\n[midi]\nmididevice = none\n[sblaster]\nsbtype = sb16\nirq = 7\n[voodoo]\nvoodoo = on\nvoodoo_memsize = 4\nvoodoo_threads = auto\n[webserver]\nwebserver_enabled = on\nwebserver_bind_address = 127.0.0.1\nwebserver_port = {args.port}\n[autoexec]\n@echo off\nmount c "."\nimgmount d "{disc_cue}" -t iso\nc:\ncd SR\nNATIVE3D.EXE\nexit\n'''
    (root / 'dosbox.conf').write_text(config)
    environment = os.environ.copy()
    environment.update(SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy', SDL_RENDER_DRIVER='software')
    started = time.monotonic()
    captured = False
    with (root / 'runtime.log').open('wb') as log:
        process = subprocess.Popen([str(engine), '--noprimaryconf', '--nolocalconf', '--conf', str(root / 'dosbox.conf')],
                                   cwd=game, env=environment, stdout=log, stderr=subprocess.STDOUT)
        print('Started own isolated 3dfx probe PID', process.pid, flush=True)
        previous_error = None
        preliminary_saved = False
        published_complete = False
        try:
            while time.monotonic() - started < 70:
                if process.poll() is not None:
                    print('Engine exited early', process.returncode, flush=True)
                    break
                try:
                    memory, registers, before, after = read_snapshot(base_url, started + 90)
                    loaded, evidence, markers = resolve(memory, objects, records)
                    text = (root / 'runtime.log').read_text(errors='replace')
                    camera_ready = 0x10000 <= markers['camera']['u32'] < len(memory) - 256
                    video_ready = 'VOODOO:' in text and 'graphics mode 00h' in text
                    complete = camera_ready and video_ready
                    prefix = '' if complete else 'initial-'
                    metadata = {'schema_version': 1, 'executable_sha256': EXPECTED_SHA,
                                'runtime_executable_sha256': hashlib.sha256(patched).hexdigest(),
                                'ram_sha256': hashlib.sha256(memory).hexdigest(), 'physical_ram_base': 0,
                                'ram_size': len(memory), 'pointer_bias': 0,
                                'captured_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                'monotonic_ns': after, 'capture_started_monotonic_ns': before,
                                'capture_duration_ms': (after - before) / 1e6,
                                'objects': loaded, 'object_resolution_evidence': evidence,
                                'markers': markers, 'registers': registers,
                                'guest_patch': {'raw_offset': offset, 'expected_hex': '83f801', 'replacement_hex': '83f803'},
                                'source_executable': str(source_path), 'engine': str(engine),
                                'source_game_root': str(game_root), 'api_base_url': base_url,
                                'address_space': 'DOSBox MEM_BlockRead flat address space',
                                'camera_ready': camera_ready, 'voodoo_display_ready': video_ready,
                                'phase': 'automatic scene setup; no visual/input verification',
                                'limitations': 'Atomic CPU-step snapshot, not guaranteed logical end-of-frame; no GUI/input automation; Voodoo texture RAM excluded.'}
                    if complete or not preliminary_saved:
                        write_new(root / (prefix + 'guest-ram.bin'), memory)
                        write_json_new(root / (prefix + 'snapshot-metadata.json'), metadata)
                        published_complete = complete
                        print(json.dumps({'captured': True, 'complete': complete,
                                          'ram': str(root / (prefix + 'guest-ram.bin')),
                                          'metadata': str(root / (prefix + 'snapshot-metadata.json')), 'objects': loaded,
                                          'markers': markers, 'capture_duration_ms': metadata['capture_duration_ms']}), flush=True)
                        preliminary_saved = True
                    if not complete:
                        raise AssertionError(f'World loaded; awaiting camera={camera_ready}, Voodoo display={video_ready}')
                    sequence = root / 'sequence'
                    sequence.mkdir(exist_ok=True)
                    frames = []
                    for frame in range(3):
                        if frame:
                            time.sleep(0.3)
                            memory, registers, before, after = read_snapshot(base_url, started + 90)
                            loaded, evidence, markers = resolve(memory, objects, records)
                            metadata = dict(metadata)
                            metadata.update(ram_sha256=hashlib.sha256(memory).hexdigest(),
                                            captured_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                            monotonic_ns=after, capture_started_monotonic_ns=before,
                                            capture_duration_ms=(after - before) / 1e6,
                                            objects=loaded, object_resolution_evidence=evidence,
                                            markers=markers, registers=registers)
                        ram_path = sequence / f'frame-{frame:03d}.bin'
                        meta_path = sequence / f'frame-{frame:03d}.json'
                        write_new(ram_path, memory)
                        write_json_new(meta_path, metadata)
                        frames.append({'ram': ram_path.name, 'metadata': meta_path.name,
                                       'monotonic_ns': metadata['monotonic_ns']})
                    write_json_new(sequence / 'index.json', {'same_session': True,
                        'engine_pid': process.pid, 'requested_spacing_seconds': 0.3,
                        'frames': frames})
                    print('Three same-session snapshots ready:', sequence / 'index.json', flush=True)
                    print(f'Read-only endpoint {base_url}; holding up to {args.hold_seconds:g}s within the 90s run budget', flush=True)
                    hold_until = min(started + 90, time.monotonic() + args.hold_seconds)
                    while time.monotonic() < hold_until and process.poll() is None:
                        time.sleep(0.25)
                    captured = True
                    break
                except Exception as error:
                    if published_complete:
                        # Keep the advertised snapshot immutable and stop rather
                        # than retrying over its files after a sequence error.
                        raise
                    message = str(error)
                    if message != previous_error:
                        print('Waiting:', message[:1000], flush=True)
                        previous_error = message
                time.sleep(2)
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            (root / 'probe-result.json').write_text(json.dumps({'captured': captured, 'engine_exit': process.returncode,
                                                              'elapsed_seconds': time.monotonic() - started}) + '\n')
            print('Stopped own 3dfx probe; captured', captured, 'exit', process.returncode, flush=True)

    return 0 if captured else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(f'Probe failed: {error}', file=sys.stderr)
        raise SystemExit(1)
