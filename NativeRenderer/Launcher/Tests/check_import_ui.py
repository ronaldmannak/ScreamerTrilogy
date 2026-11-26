#!/usr/bin/env python3
"""Exercise first-launch UI and missing-import dispatch without game data/input."""
import argparse
import json
from pathlib import Path
import plistlib
import subprocess
from check_selection import compile_launcher


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parent
    source = root.parent / 'Launcher.m'
    regression, production = args.output / 'check-ui', args.output / 'GameLauncher'
    compile_launcher(source, regression, root / 'FirstLaunchRegression.m')
    compile_launcher(source, production)
    results = []
    for game, title in [('screamer', 'Screamer'), ('screamer2', 'Screamer 2'),
                        ('screamerrally', 'Screamer Rally')]:
        app = args.output / (title + '.app')
        resources, macos = app / 'Contents/Resources', app / 'Contents/MacOS'
        resources.mkdir(parents=True)
        macos.mkdir()
        profile = {'game': game, 'title': title, 'requires_import': True,
                   'support_name': title + ' Import UI Test'}
        (resources / 'SelectionConfig.json').write_text(json.dumps(profile))
        (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({
            'CFBundleExecutable': 'GameLauncher', 'CFBundleIdentifier': 'local.screamer.import-ui-test',
            'CFBundlePackageType': 'APPL', 'CFBundleName': title}))
        launcher = macos / 'GameLauncher'
        launcher.write_bytes(production.read_bytes())
        launcher.chmod(0o755)
        support = args.output / (game + '-support')
        content = support / 'Content'
        completed = subprocess.run([str(launcher), '--dry-run', '--support-directory', str(support)],
                                   check=True, capture_output=True, text=True, timeout=10)
        result = json.loads(completed.stdout)
        assert result == {'import_required': True, 'game': game, 'content_root': str(content)}, result
        assert not support.exists(), 'Dry run must not create support data'
        mixed = subprocess.run([str(launcher), '--dry-run', '--import-source', str(resources),
                                '--support-directory', str(support)], capture_output=True, timeout=10)
        assert mixed.returncode != 0 and not support.exists(), 'Dry run must never trigger an import'
        preview = args.output / (game + '-first-launch.png')
        subprocess.run([str(regression), str(resources), str(content), str(preview)], check=True, timeout=15)
        assert not content.exists()
        results.append({'game': game, 'import_required': True, 'cancel_preserved_data': True,
                        'controls_fit': True, 'cancel_stops_active_task': True, 'preview': preview.name})
    report = {'passed': True, 'games': results,
              'scope': 'Production import UI and dry-run dispatch; no original assets, engine or game input'}
    (args.output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
