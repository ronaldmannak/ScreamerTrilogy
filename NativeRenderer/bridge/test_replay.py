"""Pose/projection/interpolation tests using synthetic STRT3FX-shaped RAM."""

import hashlib
import struct
import unittest

from guest_memory import MemoryReadError, Snapshot, SnapshotError
from replay import build_replay, camera_from_pose, read_instances, rotation


def fixture(timestamp, position=(100, 200, 300), angles=(0, 8, 0), car_x=500):
    data = bytearray(4 * 1024 * 1024)
    code, auto_data = 0x100000, 0x200000

    def link(address):
        return code + address - 0x20000 if address < 0x120000 else auto_data + address - 0x120000

    owner, camera, instance = 0x2F0000, 0x2F0A64, 0x310000
    struct.pack_into("<I", data, link(0x1296BC), owner)
    struct.pack_into("<6i", data, camera, *angles, *position)
    scene = link(0x12F860)
    data[scene:scene + 8] = b"CAR00\0\0\0"
    struct.pack_into("<I", data, scene + 0xC, instance)
    struct.pack_into("<I", data, scene + 0x18, 0)
    struct.pack_into("<I", data, scene + 28 + 0x18, 0xFFFFFFFF)
    struct.pack_into("<II7i", data, instance, 2, 0, car_x, 20, 30, 0, 8, 0, 100)
    struct.pack_into("<I", data, link(0x1473A0), timestamp // 1000000)
    metadata = {"physical_ram_base": 0, "ram_size": len(data),
                "ram_sha256": hashlib.sha256(data).hexdigest(),
                "executable_sha256": "9eac6e12ab309389bdda019cfa695bfbbc791fbda1a4634464a444fce35165d1",
                "monotonic_ns": timestamp, "pointer_bias": 0,
                "objects": [
                    {"index": 2, "link_base": 0x20000, "physical_base": code, "virtual_size": 0xCEDC0},
                    {"index": 6, "link_base": 0x120000, "physical_base": auto_data, "virtual_size": 0x77B10},
                ]}
    return Snapshot(data, metadata)


class ReplayTests(unittest.TestCase):
    def test_identity_camera_eye_and_world_to_view_axes(self):
        camera = camera_from_pose([100, 200, 300], [0, 0, 0])
        self.assertEqual(camera["position"], [100.0, 200.0, 428.0])
        self.assertEqual(camera["rotation"], [-1.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, -1.0])

    def test_quarter_heading_matches_right_handed_rotation_definition(self):
        expected = [0, 0, -1, 0, 1, 0, 1, 0, 0]
        for actual, wanted in zip(rotation([0, 512, 0]), expected):
            self.assertAlmostEqual(actual, wanted, places=12)

    def test_fixed_main_camera_used_and_scene_ids_stable(self):
        replay = build_replay([fixture(1_000_000_000)])
        sample = replay["samples"][0]
        self.assertEqual(sample["camera"]["source_view"], "main-view")
        self.assertEqual(sample["camera"]["origin"], [100, 200, 300])
        self.assertEqual(sample["instances"][0]["id"], "scene:0")
        self.assertEqual(sample["instances"][0]["name"], "CAR00")
        self.assertEqual(sample["instances"][0]["position"], [500.0, 20.0, 30.0])
        self.assertEqual(sample["t"], 0)

    def test_two_captures_resample_without_advancing_game_or_angle_wrap_jump(self):
        snapshots = [fixture(1_000_000_000, angles=(0, 8, 0), car_x=500),
                     fixture(1_100_000_000, position=(120, 200, 300), angles=(0, 2040, 0), car_x=600)]
        hashes = [memory.sha256 for memory in snapshots]
        replay = build_replay(iter(snapshots), 60)
        self.assertEqual(replay["captured_sample_count"], 2)
        self.assertEqual(replay["sample_count"], 7)
        middle = replay["samples"][3]
        self.assertAlmostEqual(middle["t"], .05)
        self.assertFalse(middle["captured"])
        self.assertAlmostEqual(middle["camera"]["origin"][0], 110)
        self.assertAlmostEqual(middle["camera"]["angles"][1], 0)
        self.assertAlmostEqual(middle["instances"][0]["position"][0], 550)
        self.assertEqual(hashes, [memory.sha256 for memory in snapshots])
        # Recomputed matrices remain orthogonal; raw element-wise matrix lerp
        # would not preserve this invariant.
        matrix = middle["camera"]["rotation"]
        for row in range(3):
            self.assertAlmostEqual(sum(matrix[3*row + k] ** 2 for k in range(3)), 1)

    def test_duplicate_or_reversed_timestamps_rejected(self):
        for stamps in [(2, 2), (2, 1)]:
            with self.subTest(stamps=stamps), self.assertRaisesRegex(SnapshotError, "timestamps"):
                build_replay([fixture(stamps[0]), fixture(stamps[1])])

    def test_resampling_is_bounded(self):
        snapshots = [fixture(0), fixture(10_000_000_000)]
        for hz in [0, 241, float("nan"), True]:
            with self.subTest(hz=hz), self.assertRaises(SnapshotError):
                build_replay(snapshots, hz)

    def test_missing_scene_terminator_is_rejected(self):
        memory = fixture(1)
        data = bytearray(memory.data)
        scene = memory.link(0x12F860)
        # Remove the sole terminator; all remaining entries are zero.
        struct.pack_into("<I", data, scene + 28 + 0x18, 0)
        metadata = dict(memory.metadata, ram_sha256=hashlib.sha256(data).hexdigest())
        with self.assertRaisesRegex(MemoryReadError, "terminator"):
            read_instances(Snapshot(data, metadata))


if __name__ == "__main__":
    unittest.main(verbosity=2)
