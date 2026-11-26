"""Capture guards tested with synthetic RAM and no network connection."""

import hashlib
import struct
import unittest

from capture_sparse import ReadOnlyClient, capture
from guest_memory import Snapshot, SnapshotError
from replay import SCENE
from test_replay import fixture


def car_fixture():
    memory = fixture(1)
    data = bytearray(memory.data)
    scene = memory.link(SCENE)
    data[scene:scene + 8] = b"auto1\0\0\0"
    return Snapshot(data, dict(memory.metadata, ram_sha256=hashlib.sha256(data).hexdigest()))


class FakeClient:
    def __init__(self, memory, bad_marker=False, changed_car=False):
        self.memory = memory
        self.bad_marker, self.changed_car = bad_marker, changed_car
        self.byte_count = self.request_count = 0

    def read(self, address, size):
        self.byte_count += size
        self.request_count += 1
        if self.bad_marker and size == 13:
            return b"\xff" * 13
        data = self.memory.bytes(address, size)
        if self.changed_car and address == self.memory.link(SCENE):
            changed = bytearray(data)
            struct.pack_into("<I", changed, 0xC, 0x300000)
            return bytes(changed)
        return data


class SparseCaptureTests(unittest.TestCase):
    def test_only_plain_loopback_origins_accepted(self):
        for value in ["http://example.com", "https://127.0.0.1", "http://127.0.0.1/path",
                      "http://user:password@localhost", "http://localhost?query=1"]:
            with self.subTest(value=value), self.assertRaises(SnapshotError):
                ReadOnlyClient(value)
        ReadOnlyClient("http://127.0.0.1:9091")  # Constructor performs no I/O.

    def test_read_ranges_fail_before_network_io(self):
        client = ReadOnlyClient("http://127.0.0.1:9091")
        for address, size in [(-1, 1), (0, 0), (0, 65537), (0xFFFFFFFF, 2)]:
            with self.subTest(address=address, size=size), self.assertRaises(SnapshotError):
                client.read(address, size)
        self.assertEqual(client.request_count, 0)

    def test_changed_code_marker_aborts_capture(self):
        memory = car_fixture()
        with self.assertRaisesRegex(SnapshotError, "code marker"):
            capture(memory, FakeClient(memory, bad_marker=True), .05, 60)

    def test_changed_car_pointer_aborts_capture(self):
        memory = car_fixture()
        with self.assertRaisesRegex(SnapshotError, "instance address"):
            capture(memory, FakeClient(memory, changed_car=True), .05, 60)


if __name__ == "__main__":
    unittest.main(verbosity=2)
