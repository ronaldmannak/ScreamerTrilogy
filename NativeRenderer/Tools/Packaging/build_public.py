#!/usr/bin/env python3
"""Build game-data-free Apple Silicon apps; users import their own games on launch.

This builder accepts only runtime/compiler inputs, never a game directory or an
existing playable .app. Original artwork, disks and captured geometry cannot be
copied by a public build. Run verify_public.py before distributing its output.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import plistlib
import re
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = ROOT.parent
GAMES = {
    'screamer': ('Screamer', 'local.screamer.metal-player'),
    'screamer2': ('Screamer 2', 'local.screamer2.metal-player'),
    'screamerrally': ('Screamer Rally', 'local.screamer-rally.metal-player'),
}
# DOSBox resources are open-source runtime inputs. Never recursively copy an
# arbitrary Resources directory: it may belong to an already populated game app.
ENGINE_RESOURCE_DIRS = ('mapping', 'freedos-cpi', 'freedos-keyboard', 'mapperfiles',
                        'shaders', 'disk-noises', 'translations', 'shader-presets')
ENGINE_RESOURCE_FILES = ('mapping-freedos.org', 'mapping-wikipedia.org', 'mapping-unicode.org')
SOURCE_SUFFIXES = {'.py', '.json', '.md', '.txt', '.plist'}



def product_metadata(game):
    title, identifier = GAMES[game]
    return {'filename': title + '.app', 'display_name': title,
            'support_name': title + ' Metal', 'bundle_identifier': identifier}


def run(*arguments):
    subprocess.run(list(map(str, arguments)), check=True)


def clone(source, target):
    run('cp', '-cR', source, target)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def write_plist(path, value):
    path.write_bytes(plistlib.dumps(value))


def sign(path):
    run('codesign', '--force', '--sign', '-', '--timestamp=none', path)


def compile_launcher(source, output):
    run('xcrun', 'clang', '-arch', 'arm64', '-mmacosx-version-min=12.0',
        '-fobjc-arc', '-O2', '-Wall', '-Wextra', '-Werror',
        '-framework', 'AppKit', '-framework', 'Foundation', source, '-o', output)


def copy_source_tree(source, target):
    """Copy source-only runtime trees, explicitly excluding developer/test files."""
    target.mkdir(parents=True)
    for path in sorted(source.rglob('*')):
        if '__pycache__' in path.parts or path.is_symlink() or not path.is_file():
            continue
        if path.name.startswith(('test_', 'tests')) or path.name.startswith('.'):
            continue
        if path.suffix not in SOURCE_SUFFIXES and not path.name.startswith(('LICENSE', 'COPYING')):
            raise ValueError(f'Unexpected non-source runtime input: {path.relative_to(ROOT)}')
        output = target / path.relative_to(source)
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, output)


def bootstrap_scene(destination):
    """An authored untextured loading triangle, independent of every game."""
    destination.mkdir()
    vertices = [(-1., -1., 0.), (1., -1., 0.), (0., 1., 0.)]
    (destination / 'vertices.bin').write_bytes(b''.join(
        struct.pack('<9f', *xyz, 0., 0., .04, .04, .06, 1.) for xyz in vertices))
    (destination / 'indices.bin').write_bytes(struct.pack('<3I', 0, 1, 2))
    write_json(destination / 'scene.json', {
        'schema': 'screamer-public-bootstrap/v1', 'title': 'Starting game',
        'provenance': 'Authored loading placeholder; no original game content.',
        'vertices': {'file': 'vertices.bin'}, 'indices': {'file': 'indices.bin'},
        'bounds': {'min': [-1, -1, 0], 'max': [1, 1, 0]},
        'textures': [], 'batches': [{'first_index': 0, 'index_count': 3, 'texture': -1}],
    })


def original_profiles():
    # Read the source constants without running the old game-data-bearing builder.
    path = REPOSITORY / 'wrappers/screamerrally/build-native.py'
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'PROFILES' for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError('Classic source profiles missing')


def helper_bundle(destination, executable, *, name, identifier, version, build, accessory=False):
    contents = destination / 'Contents'
    (contents / 'MacOS').mkdir(parents=True)
    (contents / 'Resources').mkdir()
    shutil.copy2(executable, contents / 'MacOS/GameSelection')
    info = {
        'CFBundleName': name, 'CFBundleDisplayName': name,
        'CFBundleExecutable': 'GameSelection', 'CFBundleIdentifier': identifier,
        'CFBundlePackageType': 'APPL', 'CFBundleVersion': str(build),
        'CFBundleShortVersionString': version, 'LSMinimumSystemVersion': '12.0',
        'LSRequiresNativeExecution': True, 'NSHighResolutionCapable': True,
        'NSPrincipalClass': 'NSApplication',
    }
    if accessory:
        info['LSUIElement'] = True
    write_plist(contents / 'Info.plist', info)
    sign(destination)


def classic_bundle(resources, macos, game, title, version, build, engine_resources):
    app = resources / 'Classic/Game.app'
    contents = app / 'Contents'
    target = contents / 'Resources'
    target.mkdir(parents=True)
    (contents / 'MacOS').mkdir()
    shutil.copy2(macos / 'dosbox', contents / 'MacOS/dosbox')
    clone(macos / 'lib', contents / 'MacOS/lib')
    for entry in engine_resources.iterdir():
        if entry.is_dir():
            shutil.copytree(entry, target / entry.name)
        else:
            shutil.copy2(entry, target / entry.name)
    wrapper = REPOSITORY / 'wrappers' / game
    profile = {'key': game, **original_profiles()[game]}
    profile['enhancements'] = json.loads((wrapper / (game + '-patches.json')).read_text())
    write_json(target / 'game-profile.json', profile)
    shutil.copy2(wrapper / 'THIRD-PARTY-NOTICES.txt', target / 'Enhancement-notices.txt')
    shutil.copy2(ROOT / 'Tools/Engine/LICENSE-DOSBOX', target / 'LICENSE-DOSBOX')
    (target / 'shaders').mkdir(exist_ok=True)
    shutil.copy2(wrapper / 'shaders/trilogy-widescreen.glsl', target / 'shaders/trilogy-widescreen.glsl')
    # This is the original wrapper's source-defined configuration, without data.
    (target / 'game.conf.in').write_text(f'''# Game paths are filled from the user's local import on every launch.
[sdl]
fullscreen = @FULLSCREEN@
fullscreen_mode = standard
window_size = @WINDOW_SIZE@
output = opengl
[dosbox]
machine = svga_s3
memsize = 16
[cpu]
core = auto
cpu_cycles = 3000
cpu_cycles_protected = max
[render]
aspect = @ASPECT@
viewport = fit
integer_scaling = off
shader = @SHADER@
[sblaster]
sbtype = sb16
sbbase = 220
irq = {profile['irq']}
dma = 1
hdma = 5
[autoexec]
@echo off
mount c "."
imgmount d "@DISC_CUE@" -t iso
c:
@PROGRAM@
exit
''')
    executable = contents / 'MacOS/GameLauncher'
    compile_launcher(wrapper / 'launcher.m', executable)
    info = {
        'CFBundleName': title, 'CFBundleDisplayName': title,
        'CFBundleExecutable': 'GameLauncher', 'CFBundleIdentifier': 'local.screamer-native.' + game,
        'CFBundlePackageType': 'APPL', 'CFBundleVersion': str(build),
        'CFBundleShortVersionString': version, 'LSMinimumSystemVersion': '12.0',
        'LSRequiresNativeExecution': True, 'NSHighResolutionCapable': True,
        'NSPrincipalClass': 'NSApplication',
    }
    write_plist(contents / 'Info.plist', info)
    helper = contents / 'Helpers/Game Options.app'
    helper_bundle(helper, executable, name=title + ' Options', identifier=info['CFBundleIdentifier'] + '.options',
                  version=version, build=build, accessory=True)
    helper_info_path = helper / 'Contents/Info.plist'
    helper_info = plistlib.loads(helper_info_path.read_bytes())
    helper_info['CFBundleExecutable'] = 'GameOptions'
    (helper / 'Contents/MacOS/GameSelection').rename(helper / 'Contents/MacOS/GameOptions')
    write_plist(helper_info_path, helper_info)
    sign(helper)
    sign(app)


def runtime_sources(resources, game):
    live = resources / 'Live'
    if game in ('screamer', 'screamer2'):
        copy_source_tree(ROOT / 'Games' / game / 'Runtime', live)
    else:
        live.mkdir()
        shutil.copy2(ROOT / 'Session.py', live / 'Session.py')
        for name, source in [('Execution', 'Tools/Execution'), ('bridge', 'bridge'), ('extractor', 'extractor')]:
            copy_source_tree(ROOT / source, live / name)
        shutil.copy2(ROOT / 'hud-profile.json', live / 'hud-profile.json')
    copy_source_tree(ROOT / 'Importer', resources / 'Importer')


def filtered_engine_resources(source, destination):
    destination.mkdir()
    source = source.resolve(strict=True)
    for name in ENGINE_RESOURCE_DIRS + ENGINE_RESOURCE_FILES:
        entry = source / name
        if not entry.exists():
            continue
        if entry.is_symlink():
            raise ValueError('Runtime resource inputs must not be symlinks: ' + name)
        if entry.is_dir():
            for child in entry.rglob('*'):
                if child.is_symlink():
                    raise ValueError('Runtime resources must not contain symlinks')
            shutil.copytree(entry, destination / name)
        else:
            shutil.copy2(entry, destination / name)
    if not (destination / 'shaders/interpolation/sharp.glsl').is_file():
        raise ValueError('--engine-resources must contain the DOSBox Staging resource tree, including the sharp shader')



def minimum_macos(app):
    """The app cannot claim support older than any private Mach-O dependency."""
    magic = {bytes.fromhex(h) for h in ('cffaedfe', 'cefaedfe', 'feedfacf', 'feedface',
                                     'cafebabe', 'bebafeca', 'cafebabf', 'bfbafeca')}
    requirements = []
    for path in sorted(app.rglob('*')):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open('rb') as handle:
            if handle.read(4) not in magic:
                continue
        result = subprocess.run(['otool', '-arch', 'arm64', '-l', str(path)],
                                check=True, capture_output=True, text=True)
        versions = re.findall(r'^\s*minos\s+([\d.]+)', result.stdout, re.M)
        if not versions:
            for block in result.stdout.split('Load command '):
                if 'LC_VERSION_MIN_MACOSX' in block:
                    versions += re.findall(r'^\s*version\s+([\d.]+)', block, re.M)
        if not versions:
            raise ValueError('No macOS deployment target in private Mach-O: ' + str(path.relative_to(app)))
        minimum = max(versions, key=lambda version: tuple(map(int, version.split('.'))))
        requirements.append({'path': str(path.relative_to(app)), 'minimum_macos': minimum})
    if not requirements:
        raise ValueError('No native code in public bundle')
    minimum = max((r['minimum_macos'] for r in requirements),
                  key=lambda version: tuple(map(int, version.split('.'))))
    return {'minimum_macos': minimum, 'binaries': requirements}


def declare_minimum_macos(app, minimum):
    for path in app.rglob('Info.plist'):
        if path.parent.name == 'Contents' and path.parent.parent.suffix == '.app':
            info = plistlib.loads(path.read_bytes())
            info['LSMinimumSystemVersion'] = minimum
            write_plist(path, info)


def source_proof():
    """Record exact compiler/source inputs without publishing machine paths."""
    inputs = [ROOT / 'NativePreview/Sources/NativePreview.mm',
              ROOT / 'NativePreview/Sources/World.metal', ROOT / 'Launcher/Launcher.m',
              ROOT / 'Launcher/FirstLaunchImport.inc', Path(__file__).resolve(),
              ROOT / 'Tools/Packaging/bundle_runtime.py', ROOT / 'Tools/Packaging/verify_public.py',
              ROOT / 'Tools/Packaging/bundle_selection.py', ROOT / 'Games/build_game.py',
              ROOT / 'build_playable.py', ROOT / 'THIRD_PARTY_NOTICES.md']
    for game in GAMES:
        for name in ('launcher.m', 'options-window.inc', game + '-patches.json'):
            inputs.append(REPOSITORY / 'wrappers' / game / name)
    for path in (ROOT / 'Importer').rglob('*.py'):
        if not path.name.startswith('test_'):
            inputs.append(path)
    return [{'path': str(path.relative_to(REPOSITORY)),
             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in inputs if path.is_file()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='Fresh isolated build directory')
    parser.add_argument('--engine', type=Path, required=True, help='Built ARM64 DOSBox binary')
    parser.add_argument('--engine-resources', type=Path, required=True, help='Official DOSBox resources; only listed runtime directories are copied')
    parser.add_argument('--python-prefix', type=Path, default=Path('/opt/homebrew/opt/python@3.14'))
    parser.add_argument('--game', choices=GAMES, action='append', help='Default: all three games')
    parser.add_argument('--version', default='0.4.0')
    parser.add_argument('--build-number', type=int, default=13)
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('Building native apps requires macOS and Xcode command-line tools')
    if args.output.exists() or args.output.is_symlink():
        parser.error('--output must be a fresh directory; no working apps will be replaced')
    if args.build_number < 1:
        parser.error('--build-number must be positive')
    if not (ROOT / 'Importer/import_game.py').is_file():
        parser.error('Importer source is missing')
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True)
    engine_resources = output / 'engine-resources'
    filtered_engine_resources(args.engine_resources, engine_resources)
    # All downstream build outputs are confined to the caller's isolated output.
    component_dir = output / 'components'
    run(sys.executable, ROOT / 'NativePreview/build-native.py', '--output', component_dir,
        '--app-name', 'Public Runtime Build', '--bundle-id', 'local.screamer.public-build')
    base = component_dir / 'Public Runtime Build.app'
    resources = base / 'Contents/Resources'
    bootstrap_scene(resources / 'Scene')
    run(sys.executable, ROOT / 'Tools/Packaging/bundle_runtime.py', '--app', base,
        '--engine', args.engine, '--python-prefix', args.python_prefix,
        '--engine-resources', engine_resources)
    # Public metadata lists portable component names, not the developer's paths.
    manifest_path = resources / 'runtime-manifest.json'
    runtime_manifest = json.loads(manifest_path.read_text())
    for entry in runtime_manifest['binaries']:
        entry['source_component'] = Path(entry.pop('source')).name
    write_json(manifest_path, runtime_manifest)
    licenses = resources / 'Licenses'
    licenses.mkdir(exist_ok=True)
    for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy2(ROOT / name, licenses / name)
    shutil.copy2(ROOT / 'Tools/Engine/LICENSE-DOSBOX', licenses / 'LICENSE-DOSBOX')
    results = []
    for game in args.game or GAMES:
        title, identifier = GAMES[game]
        product = product_metadata(game)
        app = output / product['filename']
        clone(base, app)
        contents = app / 'Contents'
        resources = contents / 'Resources'
        runtime_sources(resources, game)
        classic_bundle(resources, contents / 'MacOS', game, title, args.version, args.build_number, engine_resources)
        write_json(resources / 'LiveConfig.json', {'enabled': True, 'game': game, 'render_4k': False,
                   'physics_wait_ticks': 3 if game == 'screamerrally' else 2,
                   'render_fps': 60, 'allow_partial_hud': True})
        write_json(resources / 'SelectionConfig.json', {'game': game, 'title': title,
                   'support_name': product['support_name'], 'requires_import': True,
                   'classic': 'Classic/Game.app', 'upgraded': 'RallyMetalPreview'})
        launcher = contents / 'MacOS/GameLauncher'
        compile_launcher(ROOT / 'Launcher/Launcher.m', launcher)
        helper_bundle(contents / 'Helpers/Game Selection.app', launcher, name=title + ' Setup',
                      identifier=identifier + '.selection', version=args.version, build=args.build_number)
        info_path = contents / 'Info.plist'
        info = plistlib.loads(info_path.read_bytes())
        info.update(CFBundleName=product['display_name'], CFBundleDisplayName=product['display_name'],
                    CFBundleIdentifier=identifier, CFBundleExecutable='GameLauncher',
                    CFBundleShortVersionString=args.version, CFBundleVersion=str(args.build_number))
        info.pop('CFBundleIconFile', None)
        write_plist(info_path, info)
        requirements = minimum_macos(app)
        declare_minimum_macos(app, requirements['minimum_macos'])
        write_json(output / (game + '-macos-requirements.json'), requirements)
        for nested in sorted(app.rglob('*.app'), key=lambda path: len(path.parts), reverse=True):
            sign(nested)
        sign(contents / 'MacOS/RallyMetalPreview')
        sign(app)
        run('codesign', '--verify', '--deep', '--strict', app)
        run(sys.executable, ROOT / 'Tools/Packaging/verify_public.py', app,
            '--manifest', output / (game + '-public-manifest.json'))
        results.append({'game': game, 'app': app.name, 'version': args.version,
                        'build': args.build_number, 'original_game_data': False,
                        'minimum_macos': requirements['minimum_macos']})
    write_json(output / 'public-build.json', {'schema': 'screamer-public-build/v1', 'applications': results,
                                             'source_inputs': source_proof()})
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
