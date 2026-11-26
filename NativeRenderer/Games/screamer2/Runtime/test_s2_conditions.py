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


if __name__ == '__main__':
    unittest.main(verbosity=2)
