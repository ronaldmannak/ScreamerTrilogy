#!/usr/bin/env python3
"""Build a self-contained Classic/Upgraded Screamer app from owned local data."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess

GAMES = {
    'screamer': ('Screamer', 'local.screamer.metal-player'),
    'screamer2': ('Screamer 2', 'local.screamer2.metal-player'),
}
GLIDE_SHA = '6981a7bd77445be7b360ca367af1e527927db396546db15b69803b16a67676a9'


def run(*arguments):
    subprocess.run(list(map(str, arguments)), check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('game', choices=GAMES)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--version', default='0.3.7')
    parser.add_argument('--build-number', type=int, default=12)
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--classic-app', type=Path, required=True, help='Owned stable Classic app to embed')
    parser.add_argument('--game-root', type=Path, required=True)
    parser.add_argument('--scene', type=Path, required=True)
    parser.add_argument('--cars', type=Path)
    parser.add_argument('--all-scenes', type=Path, help='Owned exported track1..track6 scenes for S1')
    parser.add_argument('--glide', type=Path, help='Owned genuine DOS Glide driver, required for S2')
    parser.add_argument('--python-prefix', type=Path, default=Path('/opt/homebrew/opt/python@3.14'))
    args = parser.parse_args()
    if args.build_number < 1: parser.error('Build number must be positive')
    root = Path(__file__).resolve().parent.parent
    game_source = root / 'Games' / args.game
    if not (game_source / 'Runtime/Session.py').is_file():
        parser.error('Missing game-specific runtime source')
    if args.game == 'screamer' and (not args.all_scenes or not all(
            (args.all_scenes / f'track{number}/scene.json').is_file() for number in range(1, 7))):
        parser.error('S1 requires --all-scenes with all six validated owned track exports')
    driver = None
    if args.game == 'screamer2':
        driver = (args.glide or args.game_root / 'GLIDE2X.OVL').read_bytes()
        if hashlib.sha256(driver).hexdigest() != GLIDE_SHA:
            parser.error('Expected the verified owned DOS Glide driver')
    title, bundle_id = GAMES[args.game]
    command = ['python3', root / 'NativePreview/build-native.py', '--app-name', title,
               '--bundle-id', bundle_id, '--scene-dir', args.scene, '--output', args.output]
    if args.cars:
        command += ['--cars-dir', args.cars]
    run(*command)
    app = args.output / (title + '.app')
    resources = app / 'Contents/Resources'
    # Runtime is a reviewed source-only tree; game/capture/build data live elsewhere.
    shutil.copytree(game_source / 'Runtime', resources / 'Live',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'test_*.py'))
    shutil.copytree(args.game_root, resources / 'game')
    if args.all_scenes:
        shutil.copytree(args.all_scenes, resources / 'S1Scenes',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    if driver:
        (resources / 'game/GLIDE2X.OVL').write_bytes(driver)
    icon = args.game_root.parent / 'GameIcon.icns'
    if icon.is_file():
        shutil.copy2(icon, resources / 'GameIcon.icns')
    licenses = resources / 'Licenses'
    licenses.mkdir()
    for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy2(root / name, licenses / name)
    shutil.copy2(root / 'Tools/Engine/LICENSE-DOSBOX', licenses / 'LICENSE-DOSBOX')
    (resources / 'LiveConfig.json').write_text(json.dumps({
        'enabled': True, 'game': args.game, 'render_4k': False,
        'physics_wait_ticks': 2, 'render_fps': 60, 'allow_partial_hud': True}) + '\n')
    info_path = app / 'Contents/Info.plist'
    info = plistlib.loads(info_path.read_bytes())
    info.update(CFBundleName=title, CFBundleDisplayName=title,
                CFBundleShortVersionString=args.version, CFBundleVersion=str(args.build_number))
    if icon.is_file():
        info['CFBundleIconFile'] = 'GameIcon.icns'
    info_path.write_bytes(plistlib.dumps(info))
    run('python3', root / 'Tools/Packaging/bundle_runtime.py', '--app', app,
        '--engine', args.engine, '--python-prefix', args.python_prefix)
    run('python3', root / 'Tools/Packaging/bundle_selection.py', '--app', app,
        '--classic-app', args.classic_app, '--game', args.game,
        '--version', args.version, '--build-number', args.build_number)
    run('codesign', '--force', '--sign', '-', '--timestamp=none', app)
    run('codesign', '--verify', '--deep', '--strict', app)
    print(app)


if __name__ == '__main__':
    main()
