#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Import user-owned DOS game data without executing the game or its installer.

The downloaded app stays immutable. Only a completed, verified data directory is
published into Application Support. Import staging is removed on failure/cancel.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import uuid

sys.dont_write_bytecode = True
import artwork

SCHEMA = 'screamer-import/v1'
GLIDE_SHA = '6981a7bd77445be7b360ca367af1e527927db396546db15b69803b16a67676a9'
PROFILES = {
    'screamer': {
        'title': 'Screamer', 'marker': 'STARTH.EXE',
        'cue': 'SCREAM.DAT', 'image': 'SCREAM.gog',
        'required_dirs': ['GFX', 'DATA', 'TABS', 'CONFIG'],
        'hashes': {
            'STARTH.EXE': '1246afc95463f96598d5fee764fc99c847b6d3e0bf8ca2268bd362c664bb28a3',
            'DOS4GW.EXE': '0c54f552e7367f1568d6c72062d2755dfcc34cb6591b988f56d2aa19e371ccf3',
            'GFX/GRAF.DAT': '7ed551be3e8c83ff65dbaef73d68d8cf97471861f022f6da6e482d332a396e06',
        },
    },
    'screamer2': {
        'title': 'Screamer 2', 'marker': 'S2_3DFX.EXE',
        'cue': 'GAME.DAT', 'image': 'GAME.GOG',
        'required_dirs': ['GFX', 'DATA', 'TABS', 'CONFIG'],
        'hashes': {
            'START65H.EXE': '05f576866f26602be303343c5e9104132616f464b71ed6ae958e99a668e5c7c8',
            'S2_3DFX.EXE': 'e6c24c84650938f2baee5f4b571baa45bb09a93ba12dd24e3e1d2cefd9b6f3ec',
            'DOS4GW.EXE': 'b8265123ac8a189637448618409ef3ecd2e9f3e1a47062c685a02240f688dec1',
            'GFX/GRAF2.DAT': 'b02de9034630bb1265551299b9793fae7870d44bafc887d171877b6d358262d2',
        },
    },
    'screamerrally': {
        'title': 'Screamer Rally', 'marker': 'SR/STRT3FX.EXE',
        'cue': 'cd/srally.cue', 'image': 'cd/srally.img',
        'required_dirs': ['SR/GFX', 'SR/DATA', 'SR/TABS', 'SR/CONFIG'],
        'hashes': {
            'SR/START65H.EXE': '0785e38567c475f25663e4022ec125e447a799004e34efa59758b50cfd84901d',
            'SR/STRT3FX.EXE': '9eac6e12ab309389bdda019cfa695bfbbc791fbda1a4634464a444fce35165d1',
            'SR/DOS4GW.EXE': 'b8265123ac8a189637448618409ef3ecd2e9f3e1a47062c685a02240f688dec1',
            'SR/GLIDE2X.OVL': GLIDE_SHA,
            'SR/GFX/GRAF2.DAT': '170a0f1b96c144c016b239966bf13a7dead197730e89a67d22b91ce5acad79cd',
        },
    },
}
# Disc data is verified once while importing; startup checks its recorded size.
DISC_HASHES = {
    'screamer': 'f0cb1f0057f9c93f9c53e26864222707772a68ef4bbe16e08fa9053153b901a0',
    'screamer2': '63684e75dd66380b7c1d4e099f3571430d2468dd827c884cdd9ecdaccede0f23',
    'screamerrally': 'd27bc54aee4627087fb06b631a80f96460b0f42ea04e1831423a3b9b340488d1',
}
MAX_FILES, MAX_BYTES = 30000, 20 * 1024**3
_child = None


class ImportFailure(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def fail(code, message):
    raise ImportFailure(code, message)


def require(condition, message, code='invalid_source'):
    if not condition:
        fail(code, message)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def checked_path(value):
    path = Path(value).expanduser().absolute()
    require(not path.is_symlink(), 'Choose the original file or folder, rather than a symbolic link.')
    require(not any(c in str(path) for c in ('\n', '\r', '\x00')), 'The selected path contains unsupported characters.')
    return path.resolve()


def relative_name(value):
    require(isinstance(value, str) and value and '\\' not in value and '\x00' not in value,
            'An imported path is invalid.', 'invalid_content')
    relative = PurePosixPath(value)
    require(not relative.is_absolute() and all(part not in ('..', '.') for part in relative.parts),
            'An imported path escapes the game folder.', 'invalid_content')
    return relative


def child_case(root, relative):
    """Resolve a DOS path case-insensitively, rejecting ambiguous or linked entries."""
    current = Path(root)
    for part in relative_name(relative).parts:
        require(current.is_dir(), f'Missing game folder: {relative}')
        matches = [p for p in current.iterdir() if p.name.casefold() == part.casefold()]
        require(len(matches) == 1, f'Missing or ambiguous game file: {relative}')
        current = matches[0]
        require(not current.is_symlink(), f'Symbolic links are not supported in game data: {relative}')
    return current


def has_marker(root, game):
    try:
        return child_case(root, PROFILES[game]['marker']).is_file()
    except (OSError, ImportFailure):
        return False


def discover(root, game):
    require(root.is_dir(), 'Select an installed game .app or the extracted DOS game folder.')
    # Prioritize explicit GOG/wrapper layouts, then a bounded search for expanded
    # GOG package payloads. Never follow links or scan outside the selected tree.
    for relative in ('', 'Contents/Resources/game', 'game'):
        candidate = root
        linked = False
        for part in PurePosixPath(relative).parts:
            candidate = candidate / part
            linked = linked or candidate.is_symlink()
        if not linked and candidate.is_dir() and has_marker(candidate, game):
            return candidate.resolve()
    queue, visited, found = [(root, 0)], 0, []
    while queue:
        folder, depth = queue.pop(0)
        visited += 1
        require(visited <= 1200, 'The selected folder is too broad. Select the game installation itself.')
        if has_marker(folder, game):
            found.append(folder)
            continue
        if depth < 7:
            for entry in sorted(folder.iterdir()):
                if entry.is_dir() and not entry.is_symlink() and entry.name not in ('.git', '__pycache__'):
                    queue.append((entry, depth + 1))
    require(len(found) == 1, 'No single supported installation of ' + PROFILES[game]['title'] +
            ' was found. Select its .app or extracted DOS game folder.')
    return found[0]


def run_tool(command):
    global _child
    try:
        _child = subprocess.Popen(list(map(str, command)), stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, start_new_session=True)
        stdout, stderr = _child.communicate(timeout=600)
        require(_child.returncode == 0,
                'Could not prepare the selected files: ' + stderr.decode(errors='replace')[-1500:])
        return stdout
    except BaseException as error:
        if _child is not None and _child.poll() is None:
            try:
                os.killpg(_child.pid, signal.SIGTERM)
                _child.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(_child.pid, signal.SIGKILL)
                _child.communicate(timeout=5)
            except ProcessLookupError:
                pass
        if isinstance(error, subprocess.TimeoutExpired):
            fail('timeout', 'Preparing the selected files took too long. Select an extracted game folder instead.')
        raise
    finally:
        _child = None


@contextlib.contextmanager
def source_tree(source):
    """Expand owned GOG packages as data; never run their installer scripts."""
    source = checked_path(source)
    require(source.exists(), 'The selected source does not exist.')
    if source.is_dir():
        yield source
        return
    require(source.suffix.lower() in ('.pkg', '.dmg'),
            'Select a game .app, extracted installation folder, GOG .pkg or GOG .dmg. Raw disc images alone are not supported.')
    with tempfile.TemporaryDirectory(prefix='screamer-import-source-') as temporary:
        temp = Path(temporary)
        if source.suffix.lower() == '.pkg':
            target = temp / 'expanded'
            run_tool(['/usr/sbin/pkgutil', '--expand-full', source, target])
            yield target
        else:
            mount = temp / 'mount'
            mount.mkdir()
            attached = False
            try:
                run_tool(['/usr/bin/hdiutil', 'attach', '-readonly', '-nobrowse',
                          '-noautoopen', '-mountpoint', mount, source])
                attached = True
                # Common GOG DMGs contain a .pkg instead of a ready .app.
                packages = [p for p in mount.iterdir() if p.suffix.lower() == '.pkg' and not p.is_symlink()]
                if len(packages) == 1:
                    expanded = temp / 'expanded'
                    run_tool(['/usr/sbin/pkgutil', '--expand-full', packages[0], expanded])
                    yield expanded
                else:
                    yield mount
            finally:
                if attached or mount.is_mount():
                    # Cleanup must work even after the UI terminates the importer.
                    subprocess.run(['/usr/bin/hdiutil', 'detach', str(mount)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)


def check_tree(root):
    files, total = [], 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        base = Path(directory)
        require(len(base.relative_to(root).parts) <= 48, 'The game folder is nested too deeply.')
        entries = dirs + names
        require(len({name.casefold() for name in entries}) == len(entries),
                'The game folder contains ambiguous DOS filenames.')
        for name in entries:
            require(name not in ('.', '..') and not any(c in name for c in ('\r', '\n', '\\', '\x00')),
                    'The game folder contains an unsupported filename.')
            path = base / name
            mode = path.lstat().st_mode
            require(stat.S_ISREG(mode) or stat.S_ISDIR(mode),
                    'The game folder contains a symbolic link or special file: ' + str(path.relative_to(root)))
        for name in names:
            path = base / name
            total += path.stat().st_size
            files.append(path)
            require(len(files) <= MAX_FILES and total <= MAX_BYTES, 'The selected game folder is too large.')
    return files


def cue_files(cue):
    require(cue.stat().st_size <= 1024 * 1024, 'The CD cue sheet is too large.')
    text = cue.read_text(encoding='utf-8-sig')
    files = []
    for line in text.splitlines():
        if not re.match(r'^\s*FILE\b', line, re.I):
            continue
        match = re.fullmatch(r'\s*FILE\s+"([^"\r\n]+)"\s+BINARY\s*', line, re.I)
        require(match is not None, 'The CD cue sheet contains an unsupported FILE entry.')
        name = match.group(1)
        require('/' not in name and '\\' not in name and ':' not in name and name not in ('.', '..'),
                'The CD cue sheet must reference an image in the same folder.')
        files.append(name)
    require(len(files) == 1, 'The supported CD cue sheet must reference one disc image.')
    return files[0]


def find_glide(source):
    path = checked_path(source)
    if path.is_file():
        require(path.name.casefold() == 'glide2x.ovl', 'Select the owned GLIDE2X.OVL driver.')
        return path
    for relative in ('GLIDE2X.OVL', 'SR/GLIDE2X.OVL', 'Contents/Resources/game/GLIDE2X.OVL',
                     'Contents/Resources/game/SR/GLIDE2X.OVL', 'game/SR/GLIDE2X.OVL'):
        try:
            found = child_case(path, relative)
            if found.is_file():
                return found
        except ImportFailure:
            pass
    fail('missing_glide', 'This folder does not contain the supported owned GLIDE2X.OVL driver.')


def preflight(game, source, glide=None, verify_disc=True):
    profile = PROFILES[game]
    root = discover(source, game)
    files = check_tree(root)
    required = {}
    for relative, expected in profile['hashes'].items():
        path = child_case(root, relative)
        require(path.is_file() and digest(path) == expected,
                'Unsupported or damaged ' + relative + '. Import requires the recognized original game version.')
        required[relative] = path
    for relative in profile['required_dirs']:
        directory = child_case(root, relative)
        require(directory.is_dir() and any(directory.iterdir()), 'Missing or empty required game folder: ' + relative)
    cue, image = child_case(root, profile['cue']), child_case(root, profile['image'])
    require(cue.is_file() and image.is_file() and image.stat().st_size > 0, 'The original CD cue and image are required.')
    reference = cue_files(cue)
    require(reference.casefold() == image.name.casefold(), 'The cue sheet references a different disc image.')
    if verify_disc:
        require(digest(image) == DISC_HASHES[game], 'The disc image does not match the supported original release.')
    required[profile['cue']], required[profile['image']] = cue, image
    if game == 'screamer2':
        driver = find_glide(glide) if glide else None
        if driver is None:
            try:
                driver = child_case(root, 'GLIDE2X.OVL')
            except ImportFailure:
                pass
        require(driver is not None, 'Screamer 2 Upgraded needs an owned GLIDE2X.OVL driver. Select it or a Screamer Rally installation.', 'missing_glide')
        require(driver.is_file() and digest(driver) == GLIDE_SHA,
                'The selected GLIDE2X.OVL is not the supported original DOS Glide driver.', 'missing_glide')
        required['GLIDE2X.OVL'] = driver
    return root, files, required


def normalize_required(root, target, required):
    """Give required DOS paths the exact spelling expected by the runtime."""
    for relative, original in required.items():
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if original.is_relative_to(root):
            copied = target / original.relative_to(root)
            if copied != destination and copied.exists():
                # Case-sensitive filesystems need canonical aliases; retain other
                # original file names because data archives reference them.
                shutil.copyfile(copied, destination)
        else:
            shutil.copyfile(original, destination)
        destination.chmod(0o644)


def generate_scenes(game, data, resources):
    if game != 'screamer':
        return
    exporter = resources / 'Live/Tools/export_scene.py'
    require(exporter.is_file(), 'The app is missing its Screamer scene exporter.', 'broken_app')
    for track in range(1, 7):
        run_tool([sys.executable, '-B', '-s', exporter, '--game-root', data / 'game',
                  '--output', data / 'S1Scenes' / ('track' + str(track)), '--track', str(track)])


def inventory(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            result[relative] = {'size': path.stat().st_size, 'sha256': digest(path)}
    return result


def validate(game, destination, deep=False):
    destination = checked_path(destination)
    require(destination.is_dir(), 'Import your owned game files to get started.', 'import_required')
    manifest_path = destination / 'manifest.json'
    require(manifest_path.is_file() and not manifest_path.is_symlink() and manifest_path.stat().st_size < 16 * 1024**2,
            'The import has no valid completion record. Import the game again.', 'invalid_content')
    manifest = json.loads(manifest_path.read_text())
    require(manifest.get('schema') == SCHEMA and manifest.get('game') == game and manifest.get('completed') is True,
            'The imported files belong to another game or an incomplete import.', 'invalid_content')
    recorded = manifest.get('files')
    require(isinstance(recorded, dict) and 0 < len(recorded) <= MAX_FILES,
            'The import file list is invalid.', 'invalid_content')
    for relative, metadata in recorded.items():
        name = relative_name(relative)
        path = destination.joinpath(*name.parts)
        require(not any(parent.is_symlink() for parent in [path, *path.parents] if parent != destination.parent),
                'An imported file was replaced with a symbolic link.', 'invalid_content')
        require(isinstance(metadata, dict) and path.is_file() and path.stat().st_size == metadata.get('size'),
                'An imported file is missing or changed: ' + relative, 'invalid_content')
        if deep:
            require(digest(path) == metadata.get('sha256'), 'An imported file changed: ' + relative, 'invalid_content')
    profile = PROFILES[game]
    expected_hashes = dict(profile['hashes'])
    if game == 'screamer2':
        expected_hashes['GLIDE2X.OVL'] = GLIDE_SHA
    for relative, expected in expected_hashes.items():
        path = destination / 'game' / relative
        require(path.is_file() and digest(path) == expected, 'An imported executable or required archive changed: ' + relative, 'invalid_content')
    for relative in (profile['cue'], profile['image']):
        require('game/' + relative in recorded, 'The imported CD image is missing from the completion record.', 'invalid_content')
    require(cue_files(destination / 'game' / profile['cue']).casefold() == Path(profile['image']).name.casefold(),
            'The imported cue sheet changed.', 'invalid_content')
    require('SelectionBackground.png' in recorded, 'The imported loading background is missing.', 'invalid_content')
    if game == 'screamer':
        for track in range(1, 7):
            require(f'S1Scenes/track{track}/scene.json' in recorded,
                    'An imported Screamer track is missing.', 'invalid_content')
    return manifest


def import_game(game, source, destination, resources, glide=None):
    destination = checked_path(destination)
    resources = checked_path(resources)
    destination.parent.mkdir(parents=True, exist_ok=True)
    require(not destination.is_symlink(), 'The import destination must not be a symbolic link.', 'invalid_content')
    lock_path = destination.parent / ('.' + destination.name + '.import-lock')
    with lock_path.open('a+b') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail('import_busy', 'Another import is already running for this game.')
        staging = destination.parent / ('.' + destination.name + '.importing-' + uuid.uuid4().hex)
        backup = destination.parent / ('.' + destination.name + '.previous-' + uuid.uuid4().hex)
        try:
            with source_tree(source) as tree:
                root, files, required = preflight(game, tree, glide)
                require(destination != root and destination not in root.parents and root not in destination.parents,
                        'The destination must be separate from the original game files.')
                staging.mkdir(mode=0o700)
                target = staging / 'game'
                target.mkdir()
                for path in files:
                    relative = path.relative_to(root)
                    output = target / relative
                    output.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, output)
                    output.chmod(0o644)
                normalize_required(root, target, required)
                # Keep the cue sheet local to the copied image on case-sensitive
                # volumes; arbitrary external paths were rejected in preflight.
                cue = staging / 'game' / PROFILES[game]['cue']
                text = cue.read_text(encoding='utf-8-sig')
                text = re.sub(r'(?im)^(\s*FILE\s+)"[^"]+"',
                              lambda match: match.group(1) + '"' + Path(PROFILES[game]['image']).name + '"', text)
                cue.write_text(text)
                artwork.extract(game, target, staging / 'SelectionBackground.png')
                generate_scenes(game, staging, resources)
                manifest = {'schema': SCHEMA, 'game': game, 'completed': True, 'files': inventory(staging)}
                (staging / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
                validate(game, staging, deep=True)
            # Filesystem renames keep old completed imports recoverable if the
            # second rename fails. Interrupts are deferred across this tiny swap.
            previous_handler = signal.signal(signal.SIGTERM, signal.SIG_IGN)
            try:
                if destination.exists():
                    require(destination.is_dir(), 'The import destination is not a folder.', 'invalid_content')
                    destination.rename(backup)
                try:
                    staging.rename(destination)
                except BaseException:
                    if backup.exists() and not destination.exists():
                        backup.rename(destination)
                    raise
            finally:
                signal.signal(signal.SIGTERM, previous_handler)
            if backup.exists():
                shutil.rmtree(backup)
            return manifest
        finally:
            if staging.exists():
                shutil.rmtree(staging)


def cancelled(signum, frame):
    del signum, frame
    # run_tool owns its child cleanup; signalling twice can race a dying process
    # group on macOS. Outside run_tool the copy/extract operation has no child.
    raise ImportFailure('cancelled', 'Import cancelled. Your original files and previous import were left unchanged.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', required=True, choices=tuple(PROFILES))
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--resources', type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--glide', type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--validate', action='store_true')
    modes.add_argument('--probe', action='store_true')
    parser.add_argument('--deep', action='store_true', help='Hash every imported file during validation')
    args = parser.parse_args(argv)
    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGINT, cancelled)
    result = {'ok': False, 'game': args.game, 'content_root': str(args.destination.absolute()),
              'error_code': None, 'message': ''}
    try:
        if args.validate:
            validate(args.game, args.destination, args.deep)
            result.update(ok=True, message='The imported game files are ready.')
        else:
            require(args.source is not None, 'Choose the owned game files to import.')
            if args.probe:
                with source_tree(args.source) as source:
                    preflight(args.game, source, args.glide)
                result.update(ok=True, message='The selected game files are supported.')
            else:
                require(args.resources is not None, 'The app resource folder is required.', 'broken_app')
                import_game(args.game, args.source, args.destination, args.resources, args.glide)
                result.update(ok=True, message='Your game files were imported successfully.')
    except ImportFailure as error:
        result.update(error_code=error.code, message=str(error))
    except (OSError, ValueError, KeyError, EOFError) as error:
        result.update(error_code='invalid_source', message='Could not import the selected files: ' + str(error))
    print(json.dumps(result), flush=True)
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
