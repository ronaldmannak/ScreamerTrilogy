"""Parser unit fixture only; never used as a viewer scene or game fallback."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_track import EXPECTED_EXE_SHA256, LINKS, TrackExtractor
from guest_memory import Snapshot
from texture_decode import dimensions, png_rgba, rgba_pixels


class ExtractionFixture(unittest.TestCase):
    def fixture(self):
        ram = bytearray(8 * 1024 * 1024)
        def u32(at, value):
            struct.pack_into('<I', ram, at, value & 0xffffffff)
        def i16s(at, values):
            struct.pack_into('<' + 'h' * len(values), ram, at, *values)
        # Explicit LE mappings make the test exercise pointer walks and link reads.
        u32(LINKS['rows'], 0x400000)
        u32(0x400000, 0x401000)
        u32(0x401000, 0x402000)
        u32(0x402000, 0x403000)
        u32(0x402014, 1)
        u32(LINKS['models'], 0x404000)
        u32(0x404000, 0x405000)
        u32(0x404004, 0xffffffff)
        model = 0x405000
        u32(model + 0x10, -1)
        u32(model + 0x14, 1)
        u32(model + 0x18, 0x100)
        u32(model + 0xb4, 0x406000)
        part = model + 0x100
        u32(part + 0xc, 0x200)
        u32(part + 0x1c, 0x300)
        u32(part + 0x24, 0x380)
        u32(part + 0x28, 0x90)
        ram[part + 0x68:part + 0x70] = b'testquad'
        i16s(part + 0x90, [0xb0, 0])
        i16s(part + 0xb0 + 2, [-1, 0, 4, 0, 6, 12, 18])
        i16s(model + 0x300, [0, 0, 0, 100, 0, 0, 100, 0, 100, 0, 0, 100, 0x7fff])
        i16s(model + 0x380, [0, 0, 0, 256, 0, 0, 256, 256, 0, 0, 256, 0])
        u32(0x406000, 0x20)
        u32(LINKS['dispatch'] + 0x20, 0xd02cc)
        for offset, value in enumerate([10, 20, 30, 0, 512, 0]):
            u32(0x403008 + 4 * offset, value)
        metadata = {'ram_sha256': hashlib.sha256(ram).hexdigest(),
                    'executable_sha256': EXPECTED_EXE_SHA256,
                    'monotonic_ns': 1, 'physical_ram_base': 0, 'ram_size': len(ram),
                    'pointer_bias': 0,
                    'objects': [{'index': 2, 'link_base': 0x20000, 'physical_base': 0x20000,
                                 'virtual_size': 0xcedc0},
                                {'index': 6, 'link_base': 0x120000, 'physical_base': 0x120000,
                                 'virtual_size': 0x77b10}]}
        return Snapshot(bytes(ram), metadata), ram, metadata

    def test_documented_quad_and_rotated_world_placement(self):
        memory, _, _ = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'fixture'
            scene = TrackExtractor(memory).extract(output, {'unit_test_fixture': True})
            self.assertEqual(scene['statistics']['cells'], 1)
            self.assertEqual(scene['statistics']['world_objects'], 1)
            self.assertEqual(scene['statistics']['triangles'], 2)
            self.assertEqual(scene['vertices']['count'], 4)
            self.assertEqual((output / 'vertices.bin').stat().st_size, 4 * 36)
            self.assertEqual(struct.unpack('<6I', (output / 'indices.bin').read_bytes()), (0, 1, 2, 0, 2, 3))
            for actual, expected in zip(scene['bounds']['min'], [-90, 20, 30]):
                self.assertAlmostEqual(actual, expected)
            for actual, expected in zip(scene['bounds']['max'], [10, 20, 130]):
                self.assertAlmostEqual(actual, expected)
            values = struct.unpack('<36f', (output / 'vertices.bin').read_bytes())
            self.assertEqual(values[3:5], (0.0, 0.0))
            self.assertEqual(values[12:14], (1.0, 0.0))
            self.assertEqual(values[5:9], (1.0, 1.0, 1.0, 1.0))

    def test_bad_polygon_reference_is_rejected(self):
        _, ram, metadata = self.fixture()
        struct.pack_into('<H', ram, 0x405000 + 0x100 + 0xb0 + 8, 7)
        metadata['ram_sha256'] = hashlib.sha256(ram).hexdigest()
        memory = Snapshot(bytes(ram), metadata)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'Invalid vertex reference'):
                TrackExtractor(memory).extract(Path(directory) / 'fixture', {})

    def test_original_texture_format_channels_and_palette(self):
        self.assertEqual(rgba_pixels(bytes([1]), 5, [0, 0xff0000] + [0] * 254), b'\xff\0\0\xff')
        self.assertEqual(rgba_pixels(struct.pack('<2H', 0xf800, 0x001f), 10),
                         b'\xff\0\0\xff\0\0\xff\xff')
        self.assertEqual(rgba_pixels(struct.pack('<H', 0x8f04), 12), b'\xff\0\x44\x88')
        self.assertEqual(dimensions(0, 0), (256, 32))
        self.assertEqual(dimensions(1, 5), (32, 128))

    def test_png_preserves_actual_rgba_bytes(self):
        pixels = b'\xff\0\0\xff\0\xff\0\x80'
        png = png_rgba(2, 1, pixels)
        self.assertEqual(png[:8], b'\x89PNG\r\n\x1a\n')
        at, compressed = 8, bytearray()
        while at < len(png):
            size = struct.unpack_from('>I', png, at)[0]
            if png[at + 4:at + 8] == b'IDAT':
                compressed.extend(png[at + 8:at + 8 + size])
            at += size + 12
        self.assertEqual(zlib.decompress(compressed), b'\0' + pixels)


if __name__ == '__main__':
    unittest.main()
