"""Public packaging must not accept old app payloads or captured scenes."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load('build_public')
verifier = load('verify_public')
selection = load('bundle_selection')


class PublicPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.app = self.base / 'Public.app'
        self.resources = self.app / 'Contents/Resources'
        self.resources.mkdir(parents=True)
        (self.resources / 'SelectionConfig.json').write_text(json.dumps({'requires_import': True, 'game': 'screamer'}))
        builder.bootstrap_scene(self.resources / 'Scene')

    def tearDown(self):
        self.temporary.cleanup()

    def test_public_names_are_plain_and_support_folders_are_stable(self):
        for game, title in [('screamer', 'Screamer'), ('screamer2', 'Screamer 2'),
                            ('screamerrally', 'Screamer Rally')]:
            with self.subTest(game=game):
                product = builder.product_metadata(game)
                self.assertEqual(product['filename'], title + '.app')
                self.assertEqual(product['display_name'], title)
                self.assertEqual(product['support_name'], title + ' Metal')

    def test_private_selection_keeps_old_support_folder_after_rename(self):
        for game, title in [('screamer', 'Screamer'), ('screamer2', 'Screamer 2'),
                            ('screamerrally', 'Screamer Rally')]:
            with self.subTest(game=game):
                renamed = selection.selection_profile(title, game)
                previous = selection.selection_profile(title + ' Metal', game)
                self.assertEqual(renamed, previous)
                self.assertEqual(renamed['title'], title)
                self.assertEqual(renamed['support_name'], title + ' Metal')

    def test_owned_data_builder_titles_are_plain(self):
        import ast
        path = ROOT.parents[1] / 'Games/build_game.py'
        definitions = ast.parse(path.read_text()).body
        games = next(ast.literal_eval(node.value) for node in definitions
                     if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'GAMES' for t in node.targets))
        self.assertEqual(games['screamer'][0], 'Screamer')
        self.assertEqual(games['screamer2'][0], 'Screamer 2')
        rally = (ROOT.parents[1] / 'build_playable.py').read_text()
        strings = [node.value for node in ast.walk(ast.parse(rally)) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
        self.assertIn('Screamer Rally.app', strings)
        self.assertNotIn('Screamer Rally Metal.app', strings)

    def test_authored_placeholder_is_allowed(self):
        report = verifier.verify_public(self.app)
        self.assertFalse(report['original_game_payloads_found'])
        self.assertEqual(report['file_count'], 4)

    def test_original_game_files_are_rejected(self):
        for name in ('STARTH.EXE', 'SCREAM.gog', 'GLIDE2X.OVL', 'SelectionBackground.png', 'GameIcon.icns'):
            with self.subTest(name=name):
                path = self.resources / name
                path.write_bytes(b'not a real game file')
                with self.assertRaises(ValueError):
                    verifier.verify_public(self.app)
                path.unlink()

    def test_renamed_asset_directories_are_rejected(self):
        for name in ('game', 'Cars', 'S1Scenes', 'Replay', 'textures', 'Captures'):
            with self.subTest(name=name):
                path = self.resources / name
                path.mkdir()
                with self.assertRaises(ValueError):
                    verifier.verify_public(self.app)
                path.rmdir()

    def test_captured_mesh_cannot_replace_bootstrap(self):
        (self.resources / 'Scene/vertices.bin').write_bytes(b'captured mesh')
        with self.assertRaisesRegex(ValueError, 'differs from authored'):
            verifier.verify_public(self.app)

    def test_extra_bootstrap_assets_are_rejected(self):
        (self.resources / 'Scene/sky.png').write_bytes(b'texture')
        with self.assertRaisesRegex(ValueError, 'unexpected files'):
            verifier.verify_public(self.app)

    def test_external_symlink_is_rejected(self):
        outside = self.base / 'private'
        outside.write_text('private')
        (self.resources / 'outside').symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'escapes'):
            verifier.verify_public(self.app)

    def test_minimum_macos_matches_newest_private_binary(self):
        macos = self.app / 'Contents/MacOS'
        macos.mkdir()
        for name in ('GameLauncher', 'dosbox'):
            (macos / name).write_bytes(bytes.fromhex('cffaedfe') + b'authored-test')
        def otool(arguments, **unused):
            version = '27.2' if Path(arguments[-1]).name == 'dosbox' else '12.0'
            return mock.Mock(stdout='Load command 1\n cmd LC_BUILD_VERSION\n platform 1\n minos ' + version + '\n')
        with mock.patch.object(builder.subprocess, 'run', side_effect=otool):
            result = builder.minimum_macos(self.app)
        self.assertEqual(result['minimum_macos'], '27.2')
        self.assertEqual(len(result['binaries']), 2)

    def test_minimum_macos_updates_nested_app_declarations(self):
        import plistlib
        info = self.app / 'Contents/Info.plist'
        info.write_bytes(plistlib.dumps({'LSMinimumSystemVersion': '12.0'}))
        nested = self.resources / 'Classic/Game.app/Contents/Info.plist'
        nested.parent.mkdir(parents=True)
        nested.write_bytes(plistlib.dumps({'LSMinimumSystemVersion': '12.0'}))
        builder.declare_minimum_macos(self.app, '27.2')
        self.assertEqual(plistlib.loads(info.read_bytes())['LSMinimumSystemVersion'], '27.2')
        self.assertEqual(plistlib.loads(nested.read_bytes())['LSMinimumSystemVersion'], '27.2')

    def test_engine_resources_are_allowlisted(self):
        source = self.base / 'input-resources'
        (source / 'shaders/interpolation').mkdir(parents=True)
        (source / 'shaders/interpolation/sharp.glsl').write_text('// runtime shader')
        for name in ('game', 'Scene', 'Cars', 'Classic', 'Python', 'S1Scenes'):
            (source / name).mkdir()
            (source / name / 'private.data').write_text('must not copy')
        (source / 'SelectionBackground.png').write_text('must not copy')
        output = self.base / 'resources-out'
        builder.filtered_engine_resources(source, output)
        self.assertEqual(sorted(p.name for p in output.iterdir()), ['shaders'])
        self.assertTrue((output / 'shaders/interpolation/sharp.glsl').is_file())


if __name__ == '__main__':
    unittest.main()
