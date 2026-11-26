"""Negative checks for profile confusion and corrupt export buffers."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from extract_track import TrackExtractor
from extractor_profile import DEFAULT_PROFILE, load_profile
import test_extract_track as fixtures
from validate_scene import validate_scene


class ProfileChecks(unittest.TestCase):
    def write_profile(self, directory, value):
        path = Path(directory) / 'profile.json'
        path.write_text(json.dumps(value))
        return path

    def test_material_dispatch_has_unique_eight_mode_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            loaded = load_profile(self.write_profile(directory, DEFAULT_PROFILE))
            self.assertEqual(loaded['setup_modes'][0xd7c50], 1)
            self.assertEqual(set(loaded['setup_modes'].values()), set(range(8)))

    def test_profile_rejects_boolean_link_and_ambiguous_material_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            value = copy.deepcopy(DEFAULT_PROFILE)
            value['links']['models'] = True
            with self.assertRaisesRegex(ValueError, '32-bit'):
                load_profile(self.write_profile(directory, value))
            value = copy.deepcopy(DEFAULT_PROFILE)
            value['setup_modes'][0xd7c50] = 0
            with self.assertRaisesRegex(ValueError, 'uniquely'):
                load_profile(self.write_profile(directory, value))

    def test_snapshot_cannot_be_decoded_with_different_game_profile(self):
        memory, _, _ = fixtures.ExtractionFixture().fixture()
        profile = copy.deepcopy(DEFAULT_PROFILE)
        profile['executable_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'does not match'):
            TrackExtractor(memory, profile=profile)

    def test_buffer_validator_detects_tampering(self):
        memory, _, _ = fixtures.ExtractionFixture().fixture()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'scene'
            TrackExtractor(memory, with_textures=True).extract(output, {'unit_test_fixture': True})
            result = validate_scene(output / 'scene.json')
            self.assertTrue(result['valid'])
            self.assertEqual(result['triangles'], 2)
            path = output / 'indices.bin'
            data = bytearray(path.read_bytes()); data[0] ^= 1; path.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                validate_scene(output / 'scene.json')


if __name__ == '__main__':
    unittest.main()
