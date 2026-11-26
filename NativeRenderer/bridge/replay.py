"""Read-only camera/scene poses from immutable, validated STRT3FX RAM snapshots.

This is a pose-extraction prototype, not a substitute for a simulation-boundary
feed. It does not call guest code, restore RAM, advance physics or drive input.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path

from guest_memory import MemoryReadError, Snapshot, SnapshotError


CAMERA_POINTER = 0x81E0C
VIEW_CAMERAS = 0x1296BC
CAMERA_STRUCTURE_OFFSET = 0xA64
SCENE = 0x12F860
SCENE_ENTRY_SIZE = 28
MAX_SCENE_ENTRIES = 1024
ANIMATION_CLOCK = 0x1473A0


def rotation(angles):
    """Rick's float local->world R=Ry(-heading)*Rx(pitch)*Rz(roll), row-major."""
    a0, a1, a2 = [angle * math.tau / 2048.0 for angle in angles]
    s0, c0 = math.sin(a0), math.cos(a0)
    s1, c1 = math.sin(a1), math.cos(a1)
    s2, c2 = math.sin(a2), math.cos(a2)
    return [c2*c1 - s2*s1*s0, -c2*s1*s0 - s2*c1, -c0*s1,
            s2*c0, c2*c0, -s0,
            s2*c1*s0 + c2*s1, c2*c1*s0 - s2*s1, c1*c0]


def camera_from_pose(position, angles):
    matrix = rotation(angles)
    # sr-runtime/native/frame.rs::camera: eye=pc+128 Rc[:,2], rot=-Rc^T.
    return {
        "position": [float(position[i]) + 128.0 * matrix[3*i + 2] for i in range(3)],
        "origin": [float(value) for value in position],
        "angles": [float(value) % 2048.0 for value in angles],
        "rotation": [-matrix[3*i + k] for k in range(3) for i in range(3)],
        "projection": {"width": 640, "height": 480, "fx": 256.0, "fy": 307.2,
                       "cx": 319.0, "cy": 312.0, "near": 128.0},
        "projection_source": "unmodified main-race reference; not a live viewport capture",
    }


def read_camera(memory):
    """Prefer fixed main-view state over a current pointer that may be the mirror."""
    candidates = []
    try:
        main = memory.pointer(memory.link(VIEW_CAMERAS, 4))
        if main:
            candidates.append((main + CAMERA_STRUCTURE_OFFSET, "main-view"))
    except SnapshotError:
        pass
    try:
        candidates.append((memory.pointer(memory.link(CAMERA_POINTER, 4)), "current-view-fallback"))
    except SnapshotError:
        pass
    for address, view in candidates:
        if not address or not memory.readable(address, 24):
            continue
        angles = [memory.i32(address + 4*i) for i in range(3)]
        # The game normally stores whole 11-bit angles. A broad signed bound
        # rejects accidental pointers while allowing harmless whole-turn values.
        if any(abs(value) > 2048 * 1024 for value in angles):
            continue
        position = [memory.i32(address + 12 + 4*i) for i in range(3)]
        camera = camera_from_pose(position, angles)
        camera.update({"source_view": view, "guest_address": address})
        return camera
    raise MemoryReadError("No readable STRT3FX camera pose; snapshot may precede scene setup")


def read_instances(memory):
    """Sparse root poses with stable scene:<entry> IDs, not wheel/particle fidelity."""
    table = memory.link(SCENE, SCENE_ENTRY_SIZE)
    result, rejected = [], []
    terminated = False
    for entry in range(MAX_SCENE_ENTRIES):
        address = table + entry * SCENE_ENTRY_SIZE
        if not memory.readable(address, SCENE_ENTRY_SIZE):
            raise MemoryReadError("Scene table ends outside captured RAM before its terminator")
        index = memory.rd32(address + 0x18)
        if index == 0xFFFFFFFF:
            terminated = True
            break
        instance = memory.pointer(address + 0xC)
        if not instance or not memory.readable(instance, 0x40):
            rejected.append(entry)
            continue
        model = memory.rd32(instance)
        if model >= 4096:
            rejected.append(entry)
            continue
        flags = memory.rd32(instance + 4)
        name = memory.bytes(address, 8).split(b"\0", 1)[0].decode("ascii", "replace")
        position = [float(memory.i32(instance + 8 + 4*i)) for i in range(3)]
        angles = [float(memory.i32(instance + 0x14 + 4*i) % 2048) for i in range(3)]
        result.append({"id": f"scene:{entry}", "name": name, "model": model,
                       "guest_address": instance, "flags": flags, "billboard": bool(flags & 0x8000),
                       "position": position, "angles": angles, "rotation": rotation(angles),
                       "animation": memory.i32(instance + 0x20)})
    if not terminated:
        raise MemoryReadError(f"Scene table has no terminator within {MAX_SCENE_ENTRIES} entries")
    return result, rejected


def read_sample(memory, first_monotonic_ns):
    camera = read_camera(memory)
    instances, rejected = read_instances(memory)
    clock = memory.rd32(memory.link(ANIMATION_CLOCK, 4))
    return {"t": (memory.monotonic_ns - first_monotonic_ns) / 1e9,
            "captured": True, "camera": camera, "instances": instances,
            "source": {"monotonic_ns": memory.monotonic_ns,
                       "captured_utc": memory.metadata.get("captured_utc"),
                       "ram_sha256": memory.sha256, "animation_clock": clock,
                       "rejected_scene_entries": rejected}}


def shortest_angles(a, b, alpha):
    return [(x + (((y - x + 1024.0) % 2048.0) - 1024.0) * alpha) % 2048.0
            for x, y in zip(a, b)]


def interpolate_sample(a, b, t):
    """No extrapolation; recompute rotations after shortest-angle interpolation."""
    if not a["t"] <= t <= b["t"] or b["t"] <= a["t"]:
        raise SnapshotError("Interpolation time is not inside a positive capture interval")
    alpha = (t - a["t"]) / (b["t"] - a["t"])
    if alpha <= 0:
        return copy.deepcopy(a)
    if alpha >= 1:
        return copy.deepcopy(b)
    ca, cb = a["camera"], b["camera"]
    origin = [(1-alpha)*x + alpha*y for x, y in zip(ca["origin"], cb["origin"])]
    camera = camera_from_pose(origin, shortest_angles(ca["angles"], cb["angles"], alpha))
    camera["source_view"] = "interpolated"
    older = {item["id"]: item for item in a["instances"]}
    instances = []
    for item in b["instances"]:
        previous = older.get(item["id"])
        if not previous or previous["model"] != item["model"] or item["billboard"]:
            # New, replaced or camera-facing objects are omitted between
            # captures; this is only a root-transform proof for stable IDs.
            continue
        current = copy.deepcopy(item)
        current["position"] = [(1-alpha)*x + alpha*y for x, y in zip(previous["position"], item["position"])]
        current["angles"] = shortest_angles(previous["angles"], item["angles"], alpha)
        current["rotation"] = rotation(current["angles"])
        instances.append(current)
    return {"t": t, "captured": False, "camera": camera, "instances": instances,
            "source": {"bracket_times": [a["t"], b["t"]], "alpha": alpha}}


def build_replay(snapshots, resample_hz=None):
    iterator = iter(snapshots)
    reference = next(iterator, None)
    if reference is None:
        raise SnapshotError("At least one snapshot is required")
    # Streaming callers retain only the reference/current RAM images, not the
    # entire sequence. Compact pose samples are the only accumulated state.
    samples = [read_sample(reference, reference.monotonic_ns)]
    previous_time = reference.monotonic_ns
    for current in iterator:
        if len(samples) >= 256:
            raise SnapshotError("This bounded prototype accepts at most 256 snapshots")
        if current.monotonic_ns <= previous_time:
            raise SnapshotError("Capture timestamps must be strictly increasing")
        if current.executable_sha256 != reference.executable_sha256 or current.objects != reference.objects:
            raise SnapshotError("Executable/object mapping changed between snapshots; start a new replay")
        samples.append(read_sample(current, reference.monotonic_ns))
        previous_time = current.monotonic_ns
    captured_samples = samples
    if resample_hz is not None:
        if not isinstance(resample_hz, (float, int)) or isinstance(resample_hz, bool) or not 1 <= resample_hz <= 240:
            raise SnapshotError("resample_hz must lie between 1 and 240")
        count = math.floor(samples[-1]["t"] * resample_hz) + 1
        instance_bound = max(len(sample["instances"]) for sample in samples)
        if count > 10000 or count * max(instance_bound, 1) > 250000:
            raise SnapshotError("Resampled replay exceeds the bounded frame/instance budget")
        output, bracket = [], 0
        for i in range(count):
            t = i / resample_hz
            while bracket + 1 < len(samples) and samples[bracket + 1]["t"] < t:
                bracket += 1
            if bracket + 1 < len(samples):
                output.append(interpolate_sample(samples[bracket], samples[bracket + 1], t))
            else:
                output.append(copy.deepcopy(samples[-1]))
        if output[-1]["t"] < samples[-1]["t"]:
            output.append(copy.deepcopy(samples[-1]))
        samples = output
    return {"schema": "screamer-replay/v1", "coordinates": "game-x-left-y-up-z-back",
            "rotation_layout": "row-major; camera world-to-view, instances local-to-world",
            "time_unit": "seconds", "executable_sha256": reference.executable_sha256,
            "captured_sample_count": len(captured_samples), "sample_count": len(samples),
            "resample_hz": resample_hz, "captured_samples": captured_samples,
            "scope": "offline read-only pose interpolation; no live simulation-boundary synchronization, wheel/particle or billboard fidelity",
            "samples": samples}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", nargs=2, action="append", metavar=("RAM", "METADATA"), required=True)
    parser.add_argument("--resample-hz", type=float)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshots = (Snapshot.load(ram, metadata) for ram, metadata in args.snapshot)
    replay = build_replay(snapshots, args.resample_hz)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(replay, indent=2, allow_nan=False) + "\n")
    print(f"Wrote {replay['sample_count']} pose samples from {replay['captured_sample_count']} immutable captures: {args.output}")


if __name__ == "__main__":
    main()
