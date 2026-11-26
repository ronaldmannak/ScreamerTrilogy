# SPDX-License-Identifier: GPL-3.0-only
"""Synthetic original-bank contracts; no copyrighted fixture or game execution."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import s2
from s2 import NightWorld, export_fog, export_night, objects


def grid_fixture():
    grid = bytearray(b'\xff' * 2048 + bytes(32 + 64))
    struct.pack_into('<I', grid, 0, 1024)
    struct.pack_into('<I', grid, 1024, 2048)
    struct.pack_into('<I', grid, 2048, 2080)
    struct.pack_into('<I', grid, 2048 + 0x14, 1)
    struct.pack_into('<2I6i', grid, 2080, 7, 0, 10, 20, 30, 0, 0, 0)
    return grid


class FakeAssets:
    def __init__(self):
        self.textures = [{'path': 'textures/light.png', 'width': 1, 'height': 1}]
        self.light = {'offset': 96, 'type': 0x120, 'blend_mode': 'alpha'}

    def model(self, index):
        assert index == 7
        return {'parts': 1, 'levels': [[0], [20], [40]]}

    def part(self, model, offset):
        assert offset == 20
        return {'name': 'authored-lamp', 'vertices': [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                'uv': [[0, 0], [256, 0], [0, 256]],
                'polygons': [{'material': 96, 'color': 0, 'indices': [0, 1, 2]}]}

    def placement(self, model, slot):
        return [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [1, 2, 3]

    def material(self, offset):
        assert offset == 96
        return self.light

    def texture(self, material, animation, reflection_phase):
        # The real decoder determines the 0x120 family while reading its pixels.
        material['blend_mode'] = 'modulate2x'
        return 0


class OriginalS2Contracts(unittest.TestCase):
    def test_raw_grid_placements_and_material_blend_survive_export(self):
        with tempfile.TemporaryDirectory() as folder:
            scene = NightWorld(FakeAssets(), grid_fixture(), folder,
                               provenance={'ram_sha256': 'a' * 64}).export()
            self.assertEqual(scene['instances'][0]['id'], 'cell:0:0:0:0')
            self.assertEqual(scene['instances'][0]['model'], 7)
            self.assertEqual(scene['statistics']['parts_lod_1'], 1)
            vertices = struct.unpack('<27f', (Path(folder) / 'vertices.bin').read_bytes())
            self.assertEqual(vertices[:5], (11, 22, 33, 0, 0))
            self.assertEqual(vertices[9:14], (12, 22, 33, 1, 0))
            self.assertEqual(struct.unpack('<3I', (Path(folder) / 'indices.bin').read_bytes()), (0, 1, 2))
            batch = scene['batches'][0]
            self.assertTrue(batch['blend'])
            self.assertEqual(batch['blend_mode'], 'modulate2x')
            self.assertEqual(batch['source_material_type'], 0x120)

    def test_original_reflections_retain_authored_normals_and_all_environment_frames(self):
        class Reflections(FakeAssets):
            environment = None
            def __init__(self):
                super().__init__()
                self.light.update(type=0xa0, frames=[100, 200], blend_mode='opaque')
                self.textures *= 2
            def part(self, model, offset):
                part = super().part(model, offset)
                part.update(flags=0x2000, normals=[[0., 0., 1.]] * 3)
                return part
            def texture(self, material, animation, reflection_phase):
                return int(reflection_phase >= 32768)
        with tempfile.TemporaryDirectory() as folder:
            scene = NightWorld(Reflections(), grid_fixture(), folder).export()
            batch = scene['batches'][0]
            self.assertEqual(batch['texgen'], 'original-reflection')
            self.assertEqual(batch['reflection_textures'], [0, 1])
            self.assertFalse(batch['blend'])
            self.assertEqual(struct.unpack('<9f', (Path(folder) / 'normals.bin').read_bytes()),
                             (0., 0., 1.) * 3)

    def test_source_color_sprites_keep_the_original_transparent_key(self):
        class SourceColor(FakeAssets):
            def __init__(self):
                super().__init__()
                self.light.update(type=0xe0, blend_mode='source_color')
            def texture(self, material, animation, reflection_phase):
                return 0
        with tempfile.TemporaryDirectory() as folder:
            batch = NightWorld(SourceColor(), grid_fixture(), folder).export()['batches'][0]
            self.assertEqual(batch['blend_mode'], 'source_color')
            self.assertTrue(batch['alpha_test'])
            self.assertTrue(batch['blend'])

    def test_globally_animated_textures_use_the_immutable_capture_clock(self):
        class CapturedPhase(FakeAssets):
            def texture(self, material, animation, reflection_phase):
                self.animation = animation
                return super().texture(material, animation, reflection_phase)
        grid = grid_fixture()
        struct.pack_into('<i', grid, 2080 + 0x20, -1)
        assets = CapturedPhase()
        with tempfile.TemporaryDirectory() as folder:
            NightWorld(assets, grid, folder, clock=0x12345).export()
        self.assertEqual(assets.animation, 0x2345 << 2)

    def test_out_of_bounds_grid_and_object_budget_are_rejected(self):
        for offset, value in ((0, 0xfffffff0), (2048, 0xfffffff0), (2048 + 0x14, 100001)):
            grid = grid_fixture()
            struct.pack_into('<I', grid, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                list(objects(grid))

    def test_tracks_without_original_night_banks_never_use_tinted_day_assets(self):
        class Capture:
            def link(self, address, size): return address
            def rd32(self, address): return 0
        for track in (4, 6):
            with self.subTest(track=track), tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / 'night'
                value = export_night(folder, track, '', '', target, capture=Capture(),
                                     read_entry=None, export_sky=None)
                self.assertFalse(value['night']['available'])
                self.assertEqual(value['original'], 'day')
                self.assertFalse(target.exists())

    def test_native_fog_does_not_require_unused_software_depth_map(self):
        class Capture:
            def link(self, address, size): return address
            def rd32(self, address): return 2
        def absent_entry(*args): raise ValueError('Synthetic archive has no software depth map')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'S2_3DFX.EXE').write_bytes(b'non-game synthetic executable fixture')
            with patch.object(s2, 'EXE_SHA256', s2.sha((root / 'S2_3DFX.EXE').read_bytes())):
                for track in range(6):
                    with self.subTest(track=track):
                        result = export_fog(root, track, root / 'world/scene.json', root / 'cars/scene.json',
                                            root / 'fog', capture=Capture(), read_entry=absent_entry)
                        fog = result['fog']
                        self.assertEqual(result['original'], 'fog')
                        self.assertTrue(fog['available'])
                        self.assertFalse(fog['software_depth_map']['available'])
                        self.assertFalse(fog['sky']['enabled'])
                        self.assertEqual(fog['sky']['flat_rgb'], [184, 188, 184])
                        self.assertEqual(fog['sky']['ground_rgb'], [184, 188, 184])
                        self.assertEqual(fog['glide_fog']['color_rgb'], [184, 184, 184])
                        self.assertEqual(len(fog['glide_fog']['table']), 64)
                        self.assertEqual(fog['glide_fog']['far_distance'], 25000)
                        self.assertNotIn('far_plane', fog['glide_fog'])
                        self.assertEqual(fog['world_scene'], str((root / 'world/scene.json').resolve()))
                        self.assertFalse((root / 'fog').exists())

    def test_fog_from_night_decodes_day_banks_and_preserves_scene_paths(self):
        class Capture:
            def link(self, address, size): return address
            def rd32(self, address): return 1
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'S2_3DFX.EXE').write_bytes(b'non-game synthetic executable fixture')
            paths = {'world_scene': str(root / 'fog/world/scene.json'), 'cars_scene': str(root / 'fog/cars/scene.json')}
            with patch.object(s2, 'EXE_SHA256', s2.sha((root / 'S2_3DFX.EXE').read_bytes())), \
                    patch.object(s2, '_export_bank', return_value=paths) as export:
                result = export_fog(root, 0, '', '', root / 'fog', capture=Capture(), read_entry=lambda *a: (b'', {}))
                self.assertEqual(result['original'], 'night')
                self.assertEqual(export.call_args.kwargs['condition'], 0)
                self.assertEqual(result['fog']['world_scene'], paths['world_scene'])
                self.assertEqual(result['fog']['cars_scene'], paths['cars_scene'])
                self.assertNotIn('sky_texture', result['fog'])

    def test_original_bonus_track_bypasses_fog(self):
        class Capture:
            def link(self, address, size): return address
            def rd32(self, address): return 0
        value = export_fog('', 6, '', '', '', capture=Capture(), read_entry=None)
        self.assertFalse(value['fog']['available'])
        self.assertIn('bonus', value['fog']['reason'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
