"""Adversarial bounds/profile/map tests; synthetic data, no emulator or game files."""

import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from guest_memory import MemoryReadError, Snapshot, SnapshotError


class GuestMemoryTests(unittest.TestCase):
    def setUp(self):
        self.data = bytearray(512)
        struct.pack_into("<I", self.data, 3, 0xFEDCBA98)
        struct.pack_into("<h", self.data, 7, -2345)
        struct.pack_into("<f", self.data, 9, 1.25)
        self.metadata = {
            "physical_ram_base": 0x1000,
            "ram_size": len(self.data),
            "ram_sha256": hashlib.sha256(self.data).hexdigest(),
            "executable_sha256": "9eac6e12ab309389bdda019cfa695bfbbc791fbda1a4634464a444fce35165d1",
            "monotonic_ns": 1234567890123,
            "pointer_bias": 0,
            "objects": [
                {"index": 2, "link_base": 0x20000, "physical_base": 0x1000, "virtual_size": 0x100},
                {"index": 6, "link_base": 0x120000, "physical_base": 0x1100, "virtual_size": 0x100},
            ],
        }

    def snapshot(self, **updates):
        metadata = copy.deepcopy(self.metadata)
        metadata.update(updates)
        return Snapshot(self.data, metadata)

    def test_unaligned_little_endian_and_signed_values(self):
        memory = self.snapshot()
        self.assertEqual(memory.rd32(0x1003), 0xFEDCBA98)
        self.assertEqual(memory.i32(0x1003), -19088744)
        self.assertEqual(memory.rd16(0x1003), 0xBA98)
        self.assertEqual(memory.rd8(0x1004), 0xBA)
        self.assertEqual(memory.i16(0x1007), -2345)
        self.assertEqual(memory.f32(0x1009), 1.25)

    def test_reads_reject_underflow_overflow_negative_and_non_integer_ranges(self):
        memory = self.snapshot()
        for address, length in [(0xFFF, 1), (0x11FF, 2), (0x1201, 0), (0x1000, -1),
                                (0x1000, 1 << 32), (-1, 1), (True, 1), (0x1000, True),
                                (0x1000, 1.5), ("0x1000", 1)]:
            with self.subTest(address=address, length=length):
                self.assertFalse(memory.readable(address, length))
                with self.assertRaises(MemoryReadError):
                    memory.bytes(address, length)
        self.assertTrue(memory.readable(0x1200, 0))
        self.assertEqual(memory.bytes(0x1200, 0), b"")
        with self.assertRaises(MemoryReadError):
            memory.rd32(0x11FD)

    def test_explicit_object_relocation_and_inverse(self):
        memory = self.snapshot()
        self.assertEqual(memory.link(0x20003, 4), 0x1003)
        self.assertEqual(memory.link(0x1200FF), 0x11FF)
        self.assertEqual(memory.to_link(0x1003, 4), 0x20003)
        with self.assertRaises(MemoryReadError):
            memory.link(0x200FF, 2)  # RAM exists, but crosses its LE object boundary.
        with self.assertRaises(MemoryReadError):
            memory.link(0x30000)
        with self.assertRaises(MemoryReadError):
            memory.to_link(0x10FF, 2)

    def test_pointer_translation_keeps_null_and_rejects_integer_wrap(self):
        memory = self.snapshot(pointer_bias=0x1000)
        self.assertEqual(memory.translate_pointer(0x80), 0x1080)
        self.assertEqual(memory.translate_pointer(0), 0)
        with self.assertRaises(SnapshotError):
            memory.translate_pointer(0xFFFFFFFF)
        with self.assertRaises(SnapshotError):
            self.snapshot(pointer_bias=-0x1000).translate_pointer(0x80)

    def test_pointer_read_uses_the_validated_bias(self):
        struct.pack_into("<I", self.data, 0x20, 0x80)
        memory = self.snapshot(pointer_bias=0x1000, ram_sha256=hashlib.sha256(self.data).hexdigest())
        self.assertEqual(memory.pointer(0x1020), 0x1080)

    def test_hash_detects_changed_ram(self):
        self.data[-1] = 1
        with self.assertRaisesRegex(SnapshotError, "SHA-256"):
            self.snapshot()

    def test_profile_and_length_fail_closed(self):
        for changes in [{"executable_sha256": "0" * 64}, {"executable_sha256": None},
                        {"ram_size": 511}, {"ram_sha256": "invalid"}, {"monotonic_ns": True}]:
            with self.subTest(changes=changes), self.assertRaises(SnapshotError):
                self.snapshot(**changes)

    def test_mapping_overlap_and_duplicate_indices_rejected(self):
        for field, value in [("physical_base", 0x1080), ("link_base", 0x20080), ("index", 2)]:
            objects = copy.deepcopy(self.metadata["objects"])
            objects[1][field] = value
            with self.subTest(field=field), self.assertRaises(SnapshotError):
                self.snapshot(objects=objects)

    def test_mapping_cannot_escape_snapshot_or_wrap_address_space(self):
        for changes in [{"physical_base": 0x11FF}, {"link_base": 0xFFFFFFF0}, {"virtual_size": 0}]:
            objects = copy.deepcopy(self.metadata["objects"])
            objects[1].update(changes)
            with self.subTest(changes=changes), self.assertRaises(SnapshotError):
                self.snapshot(objects=objects)

    def test_aliases_support_hex_strings_but_conflicts_rejected(self):
        objects = copy.deepcopy(self.metadata["objects"])
        for item in objects:
            item["runtime_base"] = hex(item.pop("physical_base"))
            item["size"] = hex(item.pop("virtual_size"))
        self.assertEqual(self.snapshot(objects=objects).link(0x120000), 0x1100)
        objects[0]["physical_base"] = 0x1111
        with self.assertRaisesRegex(SnapshotError, "Conflicting"):
            self.snapshot(objects=objects)

    def test_snapshot_copies_mutable_input_and_metadata(self):
        memory = self.snapshot()
        self.data[3] = 0
        self.metadata["objects"][0]["physical_base"] = 0
        self.assertEqual(memory.rd32(0x1003), 0xFEDCBA98)
        self.assertEqual(memory.link(0x20000), 0x1000)

    def test_file_load_validates_size_and_json(self):
        with tempfile.TemporaryDirectory(prefix="rally-memory-unit-") as temporary:
            ram = Path(temporary) / "ram.bin"
            metadata = Path(temporary) / "snapshot.json"
            ram.write_bytes(self.data)
            metadata.write_text(json.dumps(self.metadata))
            self.assertEqual(Snapshot.load(ram, metadata).rd32(0x1003), 0xFEDCBA98)
            with self.assertRaisesRegex(SnapshotError, "at most"):
                Snapshot.load(ram, metadata, max_bytes=511)
            metadata.write_text("{broken json")
            with self.assertRaisesRegex(SnapshotError, "JSON"):
                Snapshot.load(ram, metadata)


if __name__ == "__main__":
    unittest.main(verbosity=2)
