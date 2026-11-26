#!/usr/bin/env python3
"""Embed the owned classic app and a separate prelaunch options helper."""
import argparse
import json
from pathlib import Path
import plistlib
import shutil
import subprocess


def run(*args):
    subprocess.run(list(map(str, args)), check=True)



def selection_profile(display_name, game):
    title = display_name.removesuffix(' Metal')
    return {'game': game, 'title': title, 'support_name': title + ' Metal',
            'classic': 'Classic/Game.app', 'upgraded': 'RallyMetalPreview'}


def bundle_selection(app, classic_app, game, source=None, version="0.3.7", build_number=12):
    source = source or Path(__file__).resolve().parents[2] / 'Launcher/Launcher.m'
    classic_app = classic_app.resolve(strict=True)
    classic_executable = classic_app / 'Contents/MacOS/GameLauncher'
    artwork = classic_app / 'Contents/Resources/SelectionBackground.png'
    if not classic_executable.is_file() or not artwork.is_file():
        raise ValueError('Classic app must contain GameLauncher and original SelectionBackground.png')
    expected = {'screamer': 'STARTH.EXE', 'screamer2': 'START65H.EXE',
                'screamerrally': 'SR/START65H.EXE'}
    profile = json.loads((classic_app / 'Contents/Resources/game-profile.json').read_text())
    if profile.get('key') != game or profile.get('program') != expected[game]:
        raise ValueError('Classic app does not match the selected original game profile')
    run('codesign', '--verify', '--deep', '--strict', classic_app)
    contents = app / 'Contents'
    resources = contents / 'Resources'
    classic = resources / 'Classic'
    if classic.exists():
        raise ValueError('Use a fresh app; refusing to replace its embedded Classic app')
    classic.mkdir()
    # APFS clones keep the three owned CD images local without copying all bytes.
    run('cp', '-cR', classic_app, classic / 'Game.app')
    shutil.copy2(artwork, resources / artwork.name)
    info_path = contents / 'Info.plist'
    info = plistlib.loads(info_path.read_bytes())
    profile = selection_profile(info['CFBundleDisplayName'], game)
    title = profile['title']
    (resources / 'SelectionConfig.json').write_text(json.dumps(profile, indent=2) + '\n')
    executable = contents / 'MacOS/GameLauncher'
    run('xcrun', 'clang', '-arch', 'arm64', '-mmacosx-version-min=12.0',
        '-fobjc-arc', '-O2', '-Wall', '-Wextra', '-Werror',
        '-framework', 'AppKit', '-framework', 'Foundation', source, '-o', executable)
    helper = contents / 'Helpers/Game Selection.app/Contents'
    (helper / 'MacOS').mkdir(parents=True)
    (helper / 'Resources').mkdir()
    shutil.copy2(executable, helper / 'MacOS/GameSelection')
    helper_info = {
        'CFBundleName': title + ' Options', 'CFBundleDisplayName': title + ' Options',
        'CFBundleExecutable': 'GameSelection',
        'CFBundleIdentifier': info['CFBundleIdentifier'] + '.selection',
        'CFBundlePackageType': 'APPL', 'CFBundleVersion': str(build_number),
        'CFBundleShortVersionString': version, 'LSMinimumSystemVersion': '12.0',
        'LSRequiresNativeExecution': True, 'NSHighResolutionCapable': True,
        'NSPrincipalClass': 'NSApplication',
    }
    icon = resources / 'GameIcon.icns'
    if icon.is_file():
        shutil.copy2(icon, helper / 'Resources/GameIcon.icns')
        helper_info['CFBundleIconFile'] = icon.name
    (helper / 'Info.plist').write_bytes(plistlib.dumps(helper_info))
    for target in (executable, helper.parent):
        run('codesign', '--force', '--sign', '-', '--timestamp=none', target)
    info.update(CFBundleExecutable='GameLauncher',
                CFBundleShortVersionString=version, CFBundleVersion=str(build_number))
    info_path.write_bytes(plistlib.dumps(info))
    # The former main executable was signed against the previous Info.plist.
    # Once it becomes a private tool, sign it again before sealing the new app.
    run('codesign', '--force', '--sign', '-', '--timestamp=none',
        contents / 'MacOS/RallyMetalPreview')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--classic-app', type=Path, required=True)
    parser.add_argument('--game', choices=('screamer', 'screamer2', 'screamerrally'), required=True)
    parser.add_argument('--version', default='0.3.7')
    parser.add_argument('--build-number', type=int, default=12)
    args = parser.parse_args()
    if args.build_number < 1: parser.error('Build number must be positive')
    bundle_selection(args.app, args.classic_app, args.game, version=args.version, build_number=args.build_number)
