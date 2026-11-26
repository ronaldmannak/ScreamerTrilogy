#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Synthetic-data import regression checks; no original game payloads required."""
import copy
import hashlib
import json
import shutil
from pathlib import Path
import struct
import subprocess
import time
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import import_game as importer


def sha(data):
    return hashlib.sha256(data).hexdigest()


def archive(name, payload):
    encoded = name.encode().ljust(16, b'\0')
    record = bytes(value ^ 0x3a for value in encoded) + struct.pack('<4I', 0, len(payload), len(payload), 0)
    return payload + record + struct.pack('<I', len(record))


def image(game):
    if game == 'screamer':
        header = bytearray(128)
        header[0], header[2], header[3], header[65] = 10, 1, 8, 1
        struct.pack_into('<H', header, 66, 1)
        return bytes(header) + b'\x01\x0c' + bytes(768)
    return struct.pack('<6I', int.from_bytes(b'VK56', 'little'), 256, 1, 1, 1, 0) + bytes(512) + b'\x01'


class Imports(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='screamer-import-unit-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.profiles = copy.deepcopy(importer.PROFILES)
        self.discs = {}
        self.driver = b'owned synthetic DOS Glide driver for tests only'
        self.addCleanup(patch.stopall)
        patch.object(importer, 'PROFILES', self.profiles).start()
        patch.object(importer, 'DISC_HASHES', self.discs).start()
        patch.object(importer, 'GLIDE_SHA', sha(self.driver)).start()
        self.resources = self.root / 'Resources'
        self.resources.mkdir()
        self.destination = self.root / 'Application Support' / 'Content'

    def fixture(self, game, include_driver=True):
        source = self.root / game / 'Owned.app' / 'Contents/Resources/game'
        source.mkdir(parents=True)
        profile = self.profiles[game]
        art_name = 'GFX/GRAF.DAT' if game == 'screamer' else 'GFX/GRAF2.DAT' if game == 'screamer2' else 'SR/GFX/GRAF2.DAT'
        selected = importer.artwork.SELECTED[game]
        for relative in profile['hashes']:
            payload = archive(selected, image(game)) if relative == art_name else self.driver if relative.endswith('GLIDE2X.OVL') else ('test-only-' + relative).encode()
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            profile['hashes'][relative] = sha(payload)
        for relative in profile['required_dirs']:
            path = source / relative
            path.mkdir(parents=True, exist_ok=True)
            (path / 'SYNTHETIC.TXT').write_text('synthetic test data, never original game content')
        cue, disc = source / profile['cue'], source / profile['image']
        cue.parent.mkdir(parents=True, exist_ok=True)
        cue.write_text('FILE "' + disc.name + '" BINARY\n TRACK 01 MODE1/2352\n INDEX 01 00:00:00\n')
        disc.write_bytes(b'SYNTHETIC DISC DATA ' + game.encode())
        self.discs[game] = sha(disc.read_bytes())
        if game == 'screamer2' and include_driver:
            (source / 'GLIDE2X.OVL').write_bytes(self.driver)
        return source

    @staticmethod
    def fake_scenes(game, staging, resources):
        if game == 'screamer':
            for number in range(1, 7):
                scene = staging / 'S1Scenes' / ('track' + str(number))
                scene.mkdir(parents=True)
                (scene / 'scene.json').write_text('{"synthetic":true}')

    def import_fixture(self, game, source, glide=None):
        with patch.object(importer, 'generate_scenes', self.fake_scenes):
            return importer.import_game(game, source, self.destination, self.resources, glide)

    def test_all_games_import_and_validate_without_touching_source(self):
        for game in self.profiles:
            with self.subTest(game=game):
                source = self.fixture(game)
                before = importer.inventory(source)
                self.destination = self.root / ('support-' + game) / 'Content'
                manifest = self.import_fixture(game, source.parents[2])
                self.assertTrue(manifest['completed'])
                self.assertEqual(importer.validate(game, self.destination, deep=True), manifest)
                self.assertEqual(importer.inventory(source), before)
                self.assertNotIn('source', manifest)
                self.assertTrue((self.destination / 'SelectionBackground.png').read_bytes().startswith(b'\x89PNG'))

    def test_missing_glide_can_be_supplied_from_owned_rally_folder(self):
        source = self.fixture('screamer2', include_driver=False)
        with self.assertRaises(importer.ImportFailure) as error:
            self.import_fixture('screamer2', source)
        self.assertEqual(error.exception.code, 'missing_glide')
        self.assertFalse(self.destination.exists())
        rally = self.root / 'Owned Rally.app/Contents/Resources/game/SR'
        rally.mkdir(parents=True)
        (rally / 'GLIDE2X.OVL').write_bytes(self.driver)
        self.import_fixture('screamer2', source, rally.parents[3])
        self.assertEqual((self.destination / 'game/GLIDE2X.OVL').read_bytes(), self.driver)

    def test_explicit_glide_can_replace_unsupported_source_driver_locally(self):
        source = self.fixture('screamer2')
        (source / 'GLIDE2X.OVL').write_bytes(b'unsupported source driver')
        driver = self.root / 'GLIDE2X.OVL'
        driver.write_bytes(self.driver)
        self.import_fixture('screamer2', source, driver)
        self.assertEqual((source / 'GLIDE2X.OVL').read_bytes(), b'unsupported source driver')
        self.assertEqual((self.destination / 'game/GLIDE2X.OVL').read_bytes(), self.driver)

    def test_wrong_game_rejected_without_destination(self):
        source = self.fixture('screamer')
        with self.assertRaises(importer.ImportFailure):
            self.import_fixture('screamer2', source)
        self.assertFalse(self.destination.exists())

    def test_missing_required_file_rejected_before_staging(self):
        source = self.fixture('screamer')
        (source / 'DOS4GW.EXE').unlink()
        with self.assertRaises(importer.ImportFailure):
            self.import_fixture('screamer', source)
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.destination.parent.glob('*.importing-*')))

    def test_symbolic_link_rejected(self):
        source = self.fixture('screamer')
        outside = self.root / 'PRIVATE.TXT'
        outside.write_text('must not be imported')
        (source / 'leak.txt').symlink_to(outside)
        with self.assertRaises(importer.ImportFailure):
            self.import_fixture('screamer', source)
        self.assertFalse(self.destination.exists())

    def test_cue_traversal_and_absolute_paths_rejected(self):
        source = self.fixture('screamer')
        for name in ('../SCREAM.gog', '/private/SCREAM.gog', 'C:\\SCREAM.gog'):
            with self.subTest(name=name):
                (source / 'SCREAM.DAT').write_text('FILE "' + name + '" BINARY\n')
                with self.assertRaises(importer.ImportFailure):
                    self.import_fixture('screamer', source)
                self.assertFalse(self.destination.exists())

    def test_failed_export_preserves_existing_successful_import(self):
        source = self.fixture('screamer')
        self.import_fixture('screamer', source)
        before = importer.inventory(self.destination)
        with patch.object(importer, 'generate_scenes', side_effect=importer.ImportFailure('cancelled', 'cancelled')):
            with self.assertRaises(importer.ImportFailure):
                importer.import_game('screamer', source, self.destination, self.resources)
        self.assertEqual(importer.inventory(self.destination), before)
        self.assertFalse(list(self.destination.parent.glob('.Content.importing-*')))
        importer.validate('screamer', self.destination)

    def test_completed_import_requires_all_tracks(self):
        source = self.fixture('screamer')
        self.import_fixture('screamer', source)
        (self.destination / 'S1Scenes/track6/scene.json').unlink()
        with self.assertRaises(importer.ImportFailure):
            importer.validate('screamer', self.destination)

    def test_executable_change_even_same_size_is_rejected_on_fast_validation(self):
        source = self.fixture('screamer')
        self.import_fixture('screamer', source)
        executable = self.destination / 'game/STARTH.EXE'
        executable.write_bytes(b'X' * executable.stat().st_size)
        with self.assertRaises(importer.ImportFailure):
            importer.validate('screamer', self.destination)

    def test_manifest_traversal_rejected(self):
        source = self.fixture('screamer')
        self.import_fixture('screamer', source)
        path = self.destination / 'manifest.json'
        value = json.loads(path.read_text())
        value['files']['../private.txt'] = {'size': 1, 'sha256': 'bad'}
        path.write_text(json.dumps(value))
        with self.assertRaises(importer.ImportFailure):
            importer.validate('screamer', self.destination)

    def test_empty_import_does_not_validate(self):
        self.destination.mkdir(parents=True)
        with self.assertRaises(importer.ImportFailure):
            importer.validate('screamer', self.destination)

    def test_app_game_symbolic_link_does_not_escape_selected_app(self):
        source = self.fixture('screamer')
        app = self.root / 'Other.app'
        resources = app / 'Contents/Resources'
        resources.mkdir(parents=True)
        (resources / 'game').symlink_to(source)
        with self.assertRaises(importer.ImportFailure):
            self.import_fixture('screamer', app)
        self.assertFalse(self.destination.exists())

    def test_app_resource_ancestor_symbolic_link_rejected(self):
        source = self.fixture('screamer')
        app = self.root / 'Linked Resources.app'
        contents = app / 'Contents'
        contents.mkdir(parents=True)
        (contents / 'Resources').symlink_to(source.parent)
        with self.assertRaises(importer.ImportFailure):
            self.import_fixture('screamer', app)
        self.assertFalse(self.destination.exists())

    def test_sigterm_cancels_and_reaps_export_child(self):
        ready = self.root / 'export-ready'
        child_code = 'from pathlib import Path; import time; Path(' + repr(str(ready)) + ').write_text(\"ready\"); time.sleep(30)'
        code = ('import sys, signal\n'
                + 'sys.path.insert(0, ' + repr(str(Path(importer.__file__).parent)) + ')\n'
                + 'import import_game as m\n'
                + 'signal.signal(signal.SIGTERM, m.cancelled)\n'
                + 'try: m.run_tool([sys.executable, \"-c\", ' + repr(child_code) + '])\n'
                + 'except m.ImportFailure as e: print(e.code); sys.exit(2)\n')
        process = subprocess.Popen([sys.executable, '-B', '-c', code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline and process.poll() is None:
                time.sleep(.01)
            self.assertTrue(ready.exists(), 'Disposable export child did not start')
            process.terminate()
            stdout, stderr = process.communicate(timeout=8)
            self.assertEqual(process.returncode, 2, stderr)
            self.assertEqual(stdout.strip(), 'cancelled', stderr)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)

    @unittest.skipUnless(Path('/usr/bin/pkgbuild').exists() and Path('/usr/sbin/pkgutil').exists(), 'macOS package tools required')
    def test_pkg_expansion_imports_data_without_running_installer_scripts(self):
        source = self.fixture('screamer2')
        payload = self.root / 'package-payload'
        payload.mkdir()
        shutil.copytree(source.parents[2], payload / 'Owned.app')
        scripts = self.root / 'package-scripts'
        scripts.mkdir()
        marker = self.root / 'INSTALLER-WAS-EXECUTED'
        postinstall = scripts / 'postinstall'
        postinstall.write_text('#!/bin/sh\n: > \"' + str(marker) + '\"\n')
        postinstall.chmod(0o755)
        package = self.root / 'Owned.pkg'
        subprocess.run(['/usr/bin/pkgbuild', '--root', str(payload), '--scripts', str(scripts), '--identifier', 'local.screamer.synthetic-import-test', '--version', '1', str(package)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.import_fixture('screamer2', package)
        self.assertFalse(marker.exists(), 'Installer script ran during data import')
        importer.validate('screamer2', self.destination, deep=True)

    def test_source_root_symbolic_link_rejected(self):
        source = self.fixture('screamer')
        alias = self.root / 'alias'
        alias.symlink_to(source)
        with self.assertRaises(importer.ImportFailure):
            self.import_fixture('screamer', alias)


if __name__ == '__main__':
    unittest.main()
