"""Synthetic source-format and original conversion vectors; no game assets."""
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from original_3dfx import RawAssets, archive_entry, lzw, palette4444
from rally import car_choices, export_night


def texture_assets(folder, kind, pixels, palette=None):
    # Minimal synthetic original 32-byte material, one frame and a 256-byte
    # source scanline. These are format fixtures, never original artwork.
    mlb = bytearray(64 + 256)
    struct.pack_into('<5I', mlb, 0, kind, 32, len(pixels), 1, 0)
    struct.pack_into('<3I', mlb, 32, 1, 0, 64)
    mlb[64:64 + len(pixels)] = bytes(pixels)
    colors = list(palette or [0xffff] * 256)
    hic = bytearray(8 + 512)
    struct.pack_into('<256H', hic, 8, *colors)
    return RawAssets(b'\0' * 200, mlb, hic, folder, single_model=True)


class OriginalTextureTests(unittest.TestCase):
    def test_authored_grey_light_multiplies_destination_instead_of_alpha(self):
        with tempfile.TemporaryDirectory() as folder:
            assets = texture_assets(folder, 0x120, [0, 0x30, 0x3f, 0x41])
            material = assets.material(0)
            image = assets.textures[assets.texture(material)]
            self.assertEqual(material['blend_mode'], 'modulate2x')
            # Original converter treats *all* low nibbles as grey once the
            # 0x30 range is present. Index0 is authored ~half-grey, not clear.
            rgba = (Path(folder) / image['rgba_file']).read_bytes()
            self.assertEqual(rgba, bytes([140,138,140,255, 140,138,140,255,
                                          255,251,255,255, 148,146,148,255]))
            self.assertTrue(image['grey_blend'])

    def test_original_alpha_and_special_color_ranges_are_straight_rgba(self):
        with tempfile.TemporaryDirectory() as folder:
            assets = texture_assets(folder, 0x120, [0, 0x01, 0x11, 0x21, 0x41, 0x61])
            assets.special_colors = (0x123, 0x456, 0x789)
            image = assets.textures[assets.texture(assets.material(0))]
            rgba = (Path(folder) / image['rgba_file']).read_bytes()
            self.assertEqual(rgba[:20], bytes([0,0,0,0, 119,136,153,17,
                                               17,34,51,17, 68,85,102,17, 255,255,255,17]))
            self.assertEqual(image['blend_mode'], 'alpha')
            self.assertEqual(rgba[20:], bytes([255,255,255,255]))

    def test_type100_retains_original_translucent_high_indices(self):
        with tempfile.TemporaryDirectory() as folder:
            assets = texture_assets(folder, 0x100, [0, 1, 0xf0])
            image = assets.textures[assets.texture(assets.material(0))]
            rgba = (Path(folder) / image['rgba_file']).read_bytes()
            self.assertEqual(rgba, bytes([0,0,0,0, 255,255,255,255, 255,255,255,102]))
            self.assertEqual(palette4444(0x07e0), 0xf0f0)

    def test_invalid_texture_extent_fails_before_output(self):
        with tempfile.TemporaryDirectory() as folder:
            assets = texture_assets(folder, 0x120, [0])
            raw = bytearray(assets.mlb[:65])
            struct.pack_into('<I', raw, 12, 2)
            assets.mlb = bytes(raw)
            with self.assertRaises(ValueError):
                assets.material(0)

    def test_bounded_lzw_rejects_overflow_and_undefined_codes(self):
        # Three fixed9-bit codes: clear, literal65, end.
        packed = (256 | (65 << 9) | (257 << 18)).to_bytes(4, 'little')
        self.assertEqual(lzw(packed, 1), b'A')
        bad = (256 | (400 << 9)).to_bytes(3, 'little')
        with self.assertRaises(ValueError):
            lzw(bad, 1)
        with self.assertRaises(ValueError):
            lzw(b'', 16 * 1024**2 + 1)

    def test_dat_entry_cannot_overlap_its_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'synthetic.dat'
            name = b'AUTO1.3DX'.ljust(16, b'\0')
            entry = bytes(value ^ 0x3a for value in name) + struct.pack('<4I', 1, 99, 99, 0)
            path.write_bytes(entry + struct.pack('<I', 32))
            with self.assertRaises(ValueError):
                archive_entry(path, 'AUTO1.3DX')


class CarIdentityTests(unittest.TestCase):
    def test_rally_uses_original_scene_join_instead_of_mesh_table_model_id(self):
        class Capture:
            def link(self, address, size=4): return address
            def rd32(self, address):
                for index in range(6):
                    if address == 0x1435cc + index * 44: return index % 2
                    if address == 0x1435d0 + index * 44: return index % 4
                    if address == 0x1296c8 + index * 0xcc8 + 0xbf0: return 150 + index * 2
                raise AssertionError(hex(address))
        roots = [{'id': f'scene:{150 + i * 2}', 'model': 1590 + i} for i in range(6)]
        result = car_choices(Capture(), roots, 'rally')
        self.assertEqual(result['scene:160'], (1, 2))
        self.assertEqual(set(result), {root['id'] for root in roots})
        roots[-1]['id'] = 'scene:999'
        with self.assertRaises(ValueError):
            car_choices(Capture(), roots, 'rally')

    def test_s2_matches_auto_number_configuration_and_preserves_mesh_identity(self):
        class Capture:
            def link(self, address, size=4): return address
            def rd32(self, address):
                self.last = address
                return 2
        memory = Capture()
        root = {'id': 'scene:41', 'model': 628, 'name': 'auto3'}
        self.assertEqual(car_choices(memory, [root], 'screamer2'), {'scene:41': (2, 3)})
        self.assertEqual(memory.last, 0x151690 + 2 * 44)
        self.assertEqual(root['model'], 628)

    def test_stadium_original_fog_survives_missing_night_and_needs_no_dpt_file(self):
        class Capture:
            def link(self, address, size=4): return address
            def rd32(self, address): return 0
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / 'STRT3FX.EXE').write_bytes(b'synthetic profile fixture')
            with patch('rally.sha', return_value='9eac6e12ab309389bdda019cfa695bfbbc791fbda1a4634464a444fce35165d1'), \
                 patch('rally.archive_entry', return_value=(bytes(256 * 256 * 4), {})) as read:
                result = export_night(root, 6, root / 'world', root / 'cars', root / 'cache', capture=Capture())
            self.assertFalse(result['night']['available'])
            self.assertTrue(result['fog']['available'])
            self.assertFalse(result['fog']['sky']['enabled'])
            self.assertEqual(result['fog']['sky']['flat_rgb'], [184,188,184])
            self.assertEqual(result['fog']['sky']['ground_rgb'], [184,188,184])
            self.assertEqual(result['fog']['glide_fog']['far_distance'], 25000)
            self.assertEqual(read.call_args[0][1], 'MAP70.BCK')
            self.assertEqual(read.call_count, 1)  # No software DEPTH*.DPT read.

    def test_original_night_fog_uses_day_car_banks_and_restorable_day_sky(self):
        class Capture:
            def link(self, address, size=4): return address
            def rd32(self, address):
                return 1 if address == 0x1435c4 else 80
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / 'STRT3FX.EXE').write_bytes(b'synthetic profile fixture')
            def export_cars(game_root, base, output, **options):
                return str(Path(output) / 'scene.json')
            with patch('rally.sha', return_value='9eac6e12ab309389bdda019cfa695bfbbc791fbda1a4634464a444fce35165d1'), \
                 patch('rally.archive_entry', return_value=(bytes(256 * 256 * 4), {})), \
                 patch('rally.export_night_cars', side_effect=export_cars) as cars:
                result = export_night(root, 2, root / 'world', root / 'cars', root / 'cache', capture=Capture())
            self.assertEqual(result['original'], 'night')
            self.assertTrue(result['fog']['available'])
            self.assertTrue(result['night']['available'])
            self.assertEqual(cars.call_args_list[0].kwargs['condition'], 0)
            self.assertEqual(result['fog']['cars_scene'], result['day']['cars_scene'])
            self.assertTrue(result['day']['sky']['enabled'])

    def test_stadium_does_not_fall_back_to_tinted_day_art(self):
        class Capture:
            def link(self, address, size=4): return address
            def rd32(self, address): return 0
        result = export_night('/absent', 6, '/absent/world', '/absent/cars', '/absent/cache', capture=Capture())
        self.assertFalse(result['night']['available'])
        self.assertNotIn('cars_scene', result['night'])


if __name__ == '__main__':
    unittest.main()
