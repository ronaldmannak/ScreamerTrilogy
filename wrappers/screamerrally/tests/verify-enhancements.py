#!/usr/bin/env python3
"""Exercise patch selection and save preservation without running DOS game code."""
import argparse
import base64
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

EXPECTED = {
    (False, False): '0785e38567c475f25663e4022ec125e447a799004e34efa59758b50cfd84901d',
    (True, False): 'a355c5e1741800448fc558f7289f40d8aae15d72569979f7a258c1261d7402ad',
    (False, True): 'b58de9ef7b97ade8a5dc21bcd5c6c3ebae02a6023ba02a9f89e25ae6e126a2ff',
    (True, True): 'e064c520b6bc545d200e30c61c11d2273c74316052055209bf7ba57f3e62aca0',
}
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('app', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    executable = args.app / 'Contents/MacOS/GameLauncher'
    source = args.app / 'Contents/Resources/game/SR/START65H.EXE'
    original_hash = digest(source)
    assert original_hash == EXPECTED[(False, False)]
    checks = []
    with tempfile.TemporaryDirectory(prefix='rally-patch-tests-') as temp:
        root = Path(temp)
        data = root / 'saves with spaces'
        def prepare(wide, distance, success=True, target=executable, data_dir=data):
            command = [str(target), '--prepare-only', '--data-dir', str(data_dir),
                       '--widescreen' if wide else '--original-aspect',
                       '--extended-distance' if distance else '--standard-distance']
            result = subprocess.run(command, capture_output=True, text=True, timeout=15)
            assert (result.returncode == 0) == success, result.stdout + result.stderr
            return result
        prepare(False, False)
        game = data / 'Game/SR'
        sentinels = [game / 'SAVE-PRESERVE.DAT', game / 'SCREAMER.CFG', game / 'CONFIG/CONTROLS.CFG', game / 'START65H.EXE']
        sentinels[0].write_bytes(b'Existing player progress\x00\xff\n')
        before = {str(p): digest(p) for p in sentinels}
        for wide, distance in [(False, False), (True, False), (False, True), (True, True), (True, True), (False, False), (True, False), (False, True)]:
            prepare(wide, distance)
            config = (data / 'dosbox.conf').read_text()
            selected = game / ('RALLYMAC.EXE' if wide or distance else 'START65H.EXE')
            assert digest(selected) == EXPECTED[(wide, distance)]
            assert ('\nRALLYMAC.EXE\n' in config) == (wide or distance)
            assert ('\nSTART65H.EXE\n' in config) == (not wide and not distance)
            assert ('aspect = stretch' in config) == wide
            assert ('shader = rally-widescreen' in config) == wide
            assert ('window_size = 1280x720' in config) == wide
            assert not any(marker in config for marker in ['@PROGRAM@', '@SHADER@', '@ASPECT@', '@WINDOW_SIZE@', '@DISC_CUE@'])
            assert {str(p): digest(p) for p in sentinels} == before
        assert not (data / 'settings.json').exists(), 'CLI overrides must not persist preferences'
        checks.append('All four selections and repeated/toggled launches match independently calculated executable hashes; original executable, controls and save sentinel preserved')
        settings = {'widescreen': True, 'extended_distance': True, 'show_options': True}
        settings_path = data / 'settings.json'
        settings_path.write_text(json.dumps(settings))
        subprocess.run([str(executable), '--prepare-only', '--data-dir', str(data)], check=True, capture_output=True, timeout=15)
        assert digest(game / 'RALLYMAC.EXE') == EXPECTED[(True, True)]
        assert json.loads(settings_path.read_text()) == settings
        prepare(False, False)
        assert '\nSTART65H.EXE\n' in (data/'dosbox.conf').read_text()
        assert json.loads(settings_path.read_text()) == settings
        checks.append('Remembered preferences honored headlessly; CLI override is temporary and OFF/OFF selects original after enhanced launch')
        tracked = [settings_path, data/'dosbox.conf', game/'RALLYMAC.EXE', *sentinels]
        state = {str(p): digest(p) for p in tracked}
        with (data / '.running.lock').open('r+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert 'already running' in prepare(True, True, success=False).stderr
        assert {str(p): digest(p) for p in tracked} == state
        checks.append('Concurrent launch refused before preferences, executable, config or save mutation')
        # Test negative patch cases against the same implementation compiled as
        # a standalone local CLI. Mutating a signed app fixture would cause macOS
        # to refuse it before these guards can execute.
        project = Path(__file__).resolve().parent.parent
        include = project if (project/'launcher.m').exists() else project/'src'
        harness = root/'check-corrupt-patch'
        subprocess.run(['xcrun','clang','-arch','arm64','-mmacosx-version-min=12.0',
                        '-fobjc-arc','-O2','-Wall','-Wextra','-Werror',
                        '-framework','AppKit','-framework','Foundation','-I',str(include),
                        str(Path(__file__).with_name('check-corrupt-patch.m')),'-o',str(harness)],
                       check=True,capture_output=True)
        fixture = root/'patch-input'
        (fixture/'SR').mkdir(parents=True)
        broken = fixture/'SR/START65H.EXE'
        content = bytearray(source.read_bytes()); content[0x8564e] ^= 1; broken.write_bytes(content)
        recipe = json.loads((args.app/'Contents/Resources/game-profile.json').read_text())['enhancements']
        recipe_path = root/'recipe.json'
        recipe_path.write_text(json.dumps(recipe))
        def bad_patch():
            result = subprocess.run([str(harness),str(recipe_path),str(fixture),str(data/'Game')],
                                    capture_output=True,text=True,timeout=15)
            assert result.returncode == 1, result.stdout + result.stderr
            return result.stderr
        assert 'supported version' in bad_patch()
        assert {str(p): digest(p) for p in tracked} == state
        shutil.copy2(source, broken)
        expected = bytearray(base64.b64decode(recipe['patches'][0]['expected']))
        expected[0] ^= 1
        recipe['patches'][0]['expected'] = base64.b64encode(expected).decode()
        recipe_path.write_text(json.dumps(recipe))
        assert 'original-byte check' in bad_patch()
        assert {str(p): digest(p) for p in tracked} == state
        checks.append('Unsupported source hash and bad expected bytes refused atomically; prior executable/config/preferences/saves preserved')
    assert digest(source) == original_hash
    report = dict(app=str(args.app), checks=checks, executable_hashes={f'wide={int(k[0])},distance={int(k[1])}':v for k,v in EXPECTED.items()}, result='passed')
    args.report.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
if __name__ == '__main__':
    main()
