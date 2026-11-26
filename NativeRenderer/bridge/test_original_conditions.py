"""Optional original visual variants must keep this race's live pose guards."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from asset_jobs import export_conditions, validate_conditions


class OriginalVariantPublication(unittest.TestCase):
    def scene(self, folder):
        folder.mkdir(parents=True)
        (folder / 'vertices.bin').write_bytes(bytes(36))
        (folder / 'indices.bin').write_bytes(bytes(12))
        value = {'schema': 'screamer-scene/v1', 'provenance': {'ram_sha256': 'a' * 64},
                 'vertices': {'file': 'vertices.bin', 'count': 1},
                 'indices': {'file': 'indices.bin', 'count': 3},
                 'dynamic_instances': [{'id': 'scene:157', 'model': 1590}]}
        path = folder / 'scene.json'
        path.write_text(json.dumps(value))
        return path, value

    def test_usable_night_and_exact_captured_model_identity(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            world, _ = self.scene(folder / 'world')
            cars, base = self.scene(folder / 'night/cars')
            sky = folder / 'night/sky.png'
            sky.write_bytes(b'synthetic only')
            value = {'schema': 'screamer-original-conditions/v1', 'original': 'day',
                     'night': {'available': True, 'world_scene': str(world),
                               'cars_scene': str(cars), 'sky_texture': str(sky)}}
            self.assertTrue(validate_conditions(folder, value, 'a' * 64, base)['night']['available'])
            different = copy.deepcopy(base)
            different['dynamic_instances'][0]['model'] += 1
            rejected = validate_conditions(folder, value, 'a' * 64, different)
            self.assertFalse(rejected['night']['available'])
            self.assertIn('identities', rejected['night']['reason'])
            escaped = copy.deepcopy(value)
            escaped['night']['sky_texture'] = str(folder.parent / 'sky.png')
            self.assertFalse(validate_conditions(folder, escaped, 'a' * 64, base)['night']['available'])

    def test_original_fog_validates_independently_of_missing_night(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            world, _ = self.scene(folder / 'world')
            cars, base = self.scene(folder / 'cars')
            sky = folder / 'sky.png'
            sky.write_bytes(b'synthetic only')
            fog = {'available': True, 'world_scene': str(world), 'cars_scene': str(cars), 'sky_texture': str(sky),
                   'sky': {'enabled': False}, 'glide_fog': {'color_rgb': [184,184,184], 'table': [0]*64,
                                                          'w_scale': 1, 'far_distance': 25000}}
            value = {'schema': 'screamer-original-conditions/v1', 'original': 'fog',
                     'night': {'available': False, 'reason': 'Stadium has no Night sky'}, 'fog': fog}
            result = validate_conditions(folder, value, 'a' * 64, base)
            self.assertEqual(result['original'], 'fog')
            self.assertTrue(result['fog']['available'])
            self.assertFalse(result['night']['available'])
            bad = copy.deepcopy(value)
            bad['fog']['glide_fog']['table'][2] = True
            self.assertFalse(validate_conditions(folder, bad, 'a' * 64, base)['fog']['available'])
            self.assertTrue(value['fog']['available'])  # Validation never mutates its input.

    def test_optional_asset_failure_does_not_modify_baseline(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name)
            world, _ = self.scene(folder / 'world')
            before = world.read_bytes()
            result = export_conditions(folder, None)
            self.assertFalse(result['night']['available'])
            self.assertEqual(world.read_bytes(), before)
            self.assertEqual(json.loads((folder / 'condition-variants.json').read_text()), result)


if __name__ == '__main__':
    unittest.main()
