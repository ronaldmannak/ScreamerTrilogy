"""Night publication must retain the baseline capture and exact live car IDs."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent / 'bridge'))
from asset_jobs import export_conditions, validate_conditions


class PublicationContracts(unittest.TestCase):
    def fixture(self, root, *, model=9):
        root.mkdir(parents=True)
        (root / 'vertices.bin').write_bytes(bytes(36))
        (root / 'indices.bin').write_bytes(bytes(12))
        scene = {'schema': 'screamer-scene/v1', 'provenance': {'ram_sha256': 'b' * 64},
                 'vertices': {'file': 'vertices.bin', 'count': 1},
                 'indices': {'file': 'indices.bin', 'count': 3},
                 'dynamic_instances': [{'id': 'scene:17', 'model': model}]}
        path = root / 'scene.json'
        path.write_text(json.dumps(scene))
        return path, scene

    def test_night_preserves_the_exact_original_id_and_model_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            world, _ = self.fixture(directory / 'night/world')
            cars, baseline = self.fixture(directory / 'night/cars')
            sky = directory / 'night/sky.png'
            sky.write_bytes(b'png fixture')
            value = {'schema': 'screamer-original-conditions/v1', 'original': 'day',
                     'night': {'available': True, 'world_scene': str(world),
                               'cars_scene': str(cars), 'sky_texture': str(sky)}}
            self.assertTrue(validate_conditions(directory, value, 'b' * 64, baseline)['night']['available'])
            baseline['dynamic_instances'][0]['model'] = 10
            actual = validate_conditions(directory, value, 'b' * 64, baseline)
            self.assertFalse(actual['night']['available'])
            self.assertIn('identities', actual['night']['reason'])

    def test_missing_optional_original_assets_keep_baseline_files_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            path, baseline = self.fixture(directory / 'world')
            before = path.read_bytes()
            value = export_conditions(directory, None)
            self.assertFalse(value['night']['available'])
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(json.loads((directory / 'condition-variants.json').read_text()), value)

    def test_fog_keeps_day_banks_and_validates_independently_from_night(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            world, _ = self.fixture(directory / 'world')
            cars, baseline = self.fixture(directory / 'cars')
            value = {'schema': 'screamer-original-conditions/v1', 'original': 'fog',
                     'night': {'available': True, 'world_scene': '/outside-race-cache.json'},
                     'fog': {'available': True, 'world_scene': str(world), 'cars_scene': str(cars),
                             'glide_fog': {'table': [0] * 64, 'color_rgb': [184] * 3, 'w_scale': 1, 'far_distance': 25000}}}
            actual = validate_conditions(directory, value, 'b' * 64, baseline)
            self.assertFalse(actual['night']['available'])
            self.assertTrue(actual['fog']['available'])
            self.assertEqual(actual['original'], 'fog')
            self.assertEqual(actual['fog']['world_scene'], str(world))

    def test_corrupt_fog_table_is_disabled_without_replacing_baseline(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            world, _ = self.fixture(directory / 'world')
            cars, baseline = self.fixture(directory / 'cars')
            value = {'schema': 'screamer-original-conditions/v1', 'original': 'day',
                     'night': {'available': False}, 'fog': {'available': True, 'world_scene': str(world),
                     'cars_scene': str(cars), 'glide_fog': {'table': [False] + [0] * 63,
                     'color_rgb': [184] * 3, 'w_scale': 1, 'far_distance': 25000}}}
            self.assertFalse(validate_conditions(directory, value, 'b' * 64, baseline)['fog']['available'])
            self.assertEqual(json.loads(cars.read_text()), baseline)


if __name__ == '__main__':
    unittest.main(verbosity=2)
