"""Synthetic retained Glide records must keep original S2 blend equations."""
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_track import LINKS, TrackExtractor
from extractor_profile import DEFAULT_PROFILE
from guest_memory import Snapshot
from test_extract_track import ExtractionFixture


class OriginalBlendEquations(unittest.TestCase):
    def test_original_source_color_key_alpha_and_grey_cones(self):
        for mode, grey, expected in ((3, False, 'source_color'), (6, False, 'alpha'),
                                     (7, False, 'alpha'), (7, True, 'modulate2x')):
            with self.subTest(mode=mode, grey=grey), tempfile.TemporaryDirectory() as folder:
                _, ram, metadata = ExtractionFixture().fixture()
                def word(at, value): struct.pack_into('<I', ram, at, value)
                material = 0xe0 if mode == 3 else 0x100 if mode == 6 else 0x120
                routine = next(address for address, value in DEFAULT_PROFILE['setup_modes'].items() if value == mode)
                word(0x406000, material)
                word(LINKS['dispatch'] + material, routine)
                word(0x406004, 0x100)
                word(0x406100, 1)
                word(0x406108, 0)
                record = LINKS['textures']
                word(record, 1)
                word(record + 0x18, 7)
                word(record + 0x1c, 7)
                word(record + 0x20, 3)
                word(record + 0x24, 10 if mode == 3 or grey else 12)
                word(record + 0x28, 0x408000)
                word(record + 0x34, int(grey))
                struct.pack_into('<4H', ram, 0x408000, 0, 0x8f00, 0x8f00, 0)
                metadata['ram_sha256'] = hashlib.sha256(ram).hexdigest()
                scene = TrackExtractor(Snapshot(bytes(ram), metadata), with_textures=True).extract(
                    Path(folder) / 'scene', {'synthetic_fixture': True})
                batch = scene['batches'][0]
                self.assertEqual(batch['blend_mode'], expected)
                self.assertTrue(batch['blend'])
                self.assertEqual(batch['alpha_test'], mode == 3)
                texture = scene['textures'][batch['texture']]
                if mode == 3:
                    self.assertTrue(texture['chroma_alpha_encoded'])
                    self.assertEqual(texture['variant'], 'chroma-key')
                else:
                    self.assertEqual(texture['variant'], 'original-alpha')
                    self.assertTrue((Path(folder) / 'scene' / texture['rgba_file']).is_file())


if __name__ == '__main__':
    unittest.main(verbosity=2)
