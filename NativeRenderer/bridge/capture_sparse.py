"""Bounded read-only loopback capture of a main camera and six car root poses.

Each GET range is atomic in DOSBox Staging, but the group of field reads is
not a single atomic simulation snapshot. Acquisition windows are recorded.
No emulator is launched, guest memory written, or input event generated.
"""

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import struct
import time
import urllib.parse
import urllib.request

from guest_memory import Snapshot, SnapshotError
from replay import (CAMERA_STRUCTURE_OFFSET, SCENE, SCENE_ENTRY_SIZE, VIEW_CAMERAS,
                    camera_from_pose, interpolate_sample, read_camera, read_instances, rotation)


class ReadOnlyClient:
    def __init__(self, base_url, timeout=2.0):
        parsed = urllib.parse.urlsplit(base_url)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username or parsed.password or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment):
            raise SnapshotError("Capture URL must be a plain HTTP loopback origin")
        self.base_url, self.timeout = base_url.rstrip("/"), timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.byte_count = self.request_count = 0

    def read(self, address, size):
        if not 0 <= address < (1 << 32) or not 0 < size <= 65536 or address + size > (1 << 32):
            raise SnapshotError("HTTP read lies outside the bounded 64KiB guest range")
        request = urllib.request.Request(f"{self.base_url}/api/v1/memory/{address}/{size}",
                                         headers={"Accept": "application/octet-stream"}, method="GET")
        with self.opener.open(request, timeout=self.timeout) as response:
            data = response.read(size + 1)
        if len(data) != size:
            raise SnapshotError(f"HTTP range returned {len(data)} bytes instead of {size}")
        self.byte_count += size
        self.request_count += 1
        return data


def capture(template, client, duration, rate):
    if not 0 < duration <= 10 or not 1 <= rate <= 60 or duration * rate > 600:
        raise SnapshotError("Capture must be at most10s,1..60Hz and600 samples")
    owner_slot = template.link(VIEW_CAMERAS, 4)
    owner = template.pointer(owner_slot)
    camera_address = owner + CAMERA_STRUCTURE_OFFSET
    camera = read_camera(template)
    if not owner or camera["source_view"] != "main-view" or camera["guest_address"] != camera_address:
        raise SnapshotError("Template has no validated fixed main-view camera")
    all_instances, rejected = read_instances(template)
    cars = [item for item in all_instances if item["name"].startswith("auto") and not item["billboard"]]
    if not 1 <= len(cars) <= 16:
        raise SnapshotError("Template does not contain a bounded known car set")
    scene = template.link(SCENE)
    table_size = (max(int(item["id"].split(":")[1]) for item in cars) + 1) * SCENE_ENTRY_SIZE
    if table_size > 65536:
        raise SnapshotError("Scene pointer guard exceeds range limit")
    marker_address = template.link(0x504DC, 13)
    marker = template.bytes(marker_address, 13)
    if client.read(marker_address, 13) != marker:
        raise SnapshotError("Live relocated code marker differs from template; capture aborted")
    samples, windows, missed = [], [], 0
    start = time.monotonic()
    next_due = start
    first_ns = None
    while time.monotonic() - start < duration and len(samples) < 600:
        now = time.monotonic()
        if now < next_due:
            time.sleep(next_due - now)
        before = time.monotonic_ns()
        actual_owner = template.translate_pointer(struct.unpack("<I", client.read(owner_slot, 4))[0])
        if actual_owner != owner:
            raise SnapshotError("Main camera object changed; take a new atomic template")
        camera_bytes = client.read(camera_address, 24)
        angles = list(struct.unpack_from("<3i", camera_bytes))
        position = list(struct.unpack_from("<3i", camera_bytes, 12))
        if any(abs(value) > 2048 * 1024 for value in angles):
            raise SnapshotError("Live camera angles fail the profile sanity bound")
        pose = camera_from_pose(position, angles)
        pose.update({"source_view": "main-view", "guest_address": camera_address})
        table = client.read(scene, table_size)
        instances = []
        for original in cars:
            entry = int(original["id"].split(":")[1])
            pointer = template.translate_pointer(struct.unpack_from("<I", table, entry*SCENE_ENTRY_SIZE + 0xC)[0])
            if pointer != original["guest_address"]:
                raise SnapshotError("Car instance address changed; take a new atomic template")
            raw = client.read(pointer, 36)
            model, flags = struct.unpack_from("<2I", raw)
            if model != original["model"] or flags & 0x8000:
                raise SnapshotError("Car model/billboard state changed during sparse capture")
            item = copy.deepcopy(original)
            item["position"] = [float(value) for value in struct.unpack_from("<3i", raw, 8)]
            item["angles"] = [float(value % 2048) for value in struct.unpack_from("<3i", raw, 20)]
            item["rotation"] = rotation(item["angles"])
            item["flags"] = flags
            item["animation"] = struct.unpack_from("<i", raw, 32)[0]
            instances.append(item)
        after = time.monotonic_ns()
        midpoint = (before + after) // 2
        if first_ns is None:
            first_ns = midpoint
        windows.append((after - before) / 1e6)
        samples.append({"t": (midpoint - first_ns) / 1e9, "captured": True,
                        "camera": pose, "instances": instances,
                        "source": {"monotonic_ns": midpoint, "acquisition_start_ns": before,
                                   "acquisition_end_ns": after, "atomic_whole_pose": False}})
        next_due += 1.0 / rate
        if next_due < time.monotonic():
            skipped = math.floor((time.monotonic() - next_due) * rate)
            missed += skipped
            next_due += skipped / rate
    if client.read(marker_address, 13) != marker:
        raise SnapshotError("Live code marker changed by the end of capture")
    if len(samples) < 2:
        raise SnapshotError("Capture did not yield two pose samples")
    return samples, {"target_rate_hz": rate, "requested_duration_seconds": duration,
                     "capture_span_seconds": samples[-1]["t"], "captured_samples": len(samples),
                     "effective_rate_hz": (len(samples)-1)/samples[-1]["t"],
                     "mean_acquisition_ms": statistics.mean(windows), "max_acquisition_ms": max(windows),
                     "missed_schedule_slots": missed, "http_requests": client.request_count,
                     "payload_bytes": client.byte_count, "car_count": len(cars)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:9091")
    parser.add_argument("--ram", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=2)
    parser.add_argument("--rate-hz", type=float, default=33)
    parser.add_argument("--resample-hz", type=float, default=60)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.resample_hz <= 240:
        parser.error("--resample-hz must be1..240")
    template = Snapshot.load(args.ram, args.metadata)
    client = ReadOnlyClient(args.base_url)
    captured, statistics = capture(template, client, args.seconds, args.rate_hz)
    samples, bracket = [], 0
    for i in range(math.floor(captured[-1]["t"] * args.resample_hz) + 1):
        t = i / args.resample_hz
        while bracket + 1 < len(captured) and captured[bracket + 1]["t"] < t:
            bracket += 1
        samples.append(interpolate_sample(captured[bracket], captured[bracket + 1], t)
                       if bracket + 1 < len(captured) else copy.deepcopy(captured[-1]))
    if samples[-1]["t"] < captured[-1]["t"]:
        samples.append(copy.deepcopy(captured[-1]))
    replay = {"schema": "screamer-replay/v1", "coordinates": "game-x-left-y-up-z-back",
              "rotation_layout": "row-major; camera world-to-view, instances local-to-world",
              "time_unit": "seconds", "executable_sha256": template.executable_sha256,
              "captured_utc": datetime.now(timezone.utc).isoformat(),
              "template_ram_sha256": template.sha256, "capture_statistics": statistics,
              "captured_sample_count": len(captured), "sample_count": len(samples),
              "resample_hz": args.resample_hz, "captured_samples": captured, "samples": samples,
              "scope": "read-only sparse loopback fields; ranges atomic individually, whole pose not atomic or synchronized to a guest simulation boundary; offline60Hz interpolation of captured root motion"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(replay, indent=2, allow_nan=False) + "\n")
    print(json.dumps(statistics, indent=2))
    print(args.output)


if __name__ == "__main__":
    main()
