#!/usr/bin/env python3
"""Validate the two production launch presets without running a game."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess
import uuid


def compile_launcher(source, destination, regression=None):
    command = ['xcrun', 'clang', '-arch', 'arm64', '-mmacosx-version-min=12.0',
               '-fobjc-arc', '-O2', '-Wall', '-Wextra', '-Werror',
               '-framework', 'AppKit', '-framework', 'Foundation']
    if regression:
        command += ['-DLAUNCHER_SOURCE_FILE="' + str(source) + '"', str(regression)]
    else:
        command += [str(source)]
    subprocess.run(command + ['-o', str(destination)], check=True)


def check_dispatch(binary, output):
    """Use an isolated bundle and --dry-run; inert stubs are never executed."""
    app = output / 'Dispatch Check.app'
    contents = app / 'Contents'
    resources, macos = contents / 'Resources', contents / 'MacOS'
    resources.mkdir(parents=True)
    macos.mkdir()
    launcher = macos / 'GameLauncher'
    launcher.write_bytes(binary.read_bytes())
    launcher.chmod(0o755)
    (contents / 'Info.plist').write_bytes(plistlib.dumps({
        'CFBundleExecutable': 'GameLauncher', 'CFBundleIdentifier': 'local.screamer.selection-test',
        'CFBundlePackageType': 'APPL', 'CFBundleName': 'Dispatch Check'}))
    (resources / 'SelectionConfig.json').write_text(json.dumps({
        'game': 'screamer', 'title': 'Screamer',
        'support_name': 'Screamer Selection Regression ' + str(uuid.uuid4())}))
    classic = resources / 'Classic/Game.app/Contents/MacOS/GameLauncher'
    classic.parent.mkdir(parents=True)
    classic.symlink_to('/usr/bin/true')
    upgraded = macos / 'RallyMetalPreview'
    upgraded.symlink_to('/usr/bin/true')
    cases = [([], 'upgraded', upgraded, ['--window-resolution', '--widescreen', '--extended-distance']),
             (['--upgraded'], 'upgraded', upgraded, ['--window-resolution', '--widescreen', '--extended-distance']),
             (['--classic'], 'classic', classic, ['--no-settings', '--original-aspect', '--distance-level', '0'])]
    results = []
    for arguments, mode, executable, expected in cases:
        completed = subprocess.run([str(launcher), '--dry-run', *arguments],
                                   check=True, text=True, capture_output=True, timeout=10)
        actual = json.loads(completed.stdout)
        assert actual['executable'] == str(executable), actual
        assert actual['arguments'] == expected, actual
        assert actual['settings'] == {'mode': mode}, actual
        results.append({'mode': mode, 'arguments': actual['arguments'], 'passed': True})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--classic-root', type=Path, default=Path('/Applications'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--launcher-source', type=Path,
                        help='Production Launcher.m path; useful when running staged tests')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    source = (args.launcher_source or root.parent / 'Launcher.m').resolve(strict=True)
    args.output.mkdir(parents=True, exist_ok=False)
    binary = args.output / 'check'
    compile_launcher(source, binary, root / 'SelectionRegression.m')
    launcher = args.output / 'production-launcher'
    compile_launcher(source, launcher)
    dispatch = check_dispatch(launcher, args.output)
    games = [('screamer', 'Screamer'), ('screamer2', 'Screamer 2'),
             ('screamerrally', 'Screamer Rally')]
    results = []
    for game, title in games:
        resources = args.output / game
        resources.mkdir()
        original = args.classic_root / (title + '.app/Contents/Resources/SelectionBackground.png')
        (resources / original.name).symlink_to(original.resolve(strict=True))
        (resources / 'SelectionConfig.json').write_text(json.dumps({'game': game, 'title': title}))
        subprocess.run([str(binary), str(resources), str(resources / 'chosen.json'),
                        str(resources / 'view.png')], check=True, timeout=15)
        results.append({'game': game, 'passed': True, 'artwork': str(original),
                        'previews': ['view-classic.png', 'view.png']})
    report = {'passed': True, 'games': results, 'dispatch': dispatch,
              'checks': ['Exactly two modes with no extra graphics controls',
                         'Mode descriptions change and wrapping copy fits',
                         'Legacy graphics preferences ignored; saved mode preserved',
                         'Accepted settings persist only mode',
                         'Cancel and Quit leave pending choices unchanged',
                         'Upgraded always uses window pixels, widescreen, and full track',
                         'Classic always uses original aspect and draw distance',
                         'Controls inside view bounds'],
              'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'scope': 'Production AppKit selection view and dry-run dispatch only; no game process, game input, or desktop screen capture'}
    (args.output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
