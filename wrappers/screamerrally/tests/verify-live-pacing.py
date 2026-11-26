#!/usr/bin/env python3
"""Read-only Rally START65H timing observer for DOSBox Staging 0.83.1 HTTP API.

No guest writes, input injection, process launch, or GUI interaction.
Example: python3 verify-live-pacing.py --base-url http://127.0.0.1:9091 --seconds 15
"""

import argparse
import datetime
import json
import math
import statistics
import struct
import time
import urllib.request
import urllib.parse


def get_memory(base_url, address, length, timeout=5):
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/v1/memory/{address}/{length}",
        headers={"Accept": "application/octet-stream"}, method="GET")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        data = response.read()
    if len(data) != length:
        raise ValueError(f"Short memory read: {len(data)} != {length}")
    return data


def locate(memory):
    candidates = []
    for ticks in (1, 2, 3):
        suffix = bytes([0x83, 0xF8, ticks, 0x7C, 0xF6, 0x58, 0xC3])
        start = 0
        while True:
            cmp_at = memory.find(suffix, start)
            if cmp_at < 0:
                break
            start = cmp_at + 1
            helper = cmp_at - 6
            if helper < 0 or memory[helper:helper + 2] != b"\x50\xa1":
                continue
            tick_pointer = struct.unpack_from("<I", memory, helper + 2)[0]
            if tick_pointer != helper + 0x36:
                continue  # Reject an unrelocated executable-file copy.
            menu_call = helper + 0x3F4DC - 0x402CC
            race_call = helper + 0x3F57E - 0x402CC
            if min(menu_call, race_call) < 0:
                continue
            valid = True
            smooth_pointers = []
            for call in (menu_call, race_call):
                if memory[call] != 0xE8 or call + 5 + struct.unpack_from("<i", memory, call + 1)[0] != helper or memory[call + 5] != 0xA1:
                    valid = False
                    break
                smooth_pointers.append(struct.unpack_from("<I", memory, call + 6)[0])
            if not valid or smooth_pointers[0] != smooth_pointers[1]:
                continue
            store = memory.find(b"\xd9\x1d", race_call + 10, race_call + 0x50)
            if store < 0:
                continue
            smooth = smooth_pointers[0]
            raw = struct.unpack_from("<I", memory, store + 2)[0]
            if raw != smooth + 4 or smooth + 20 > len(memory):
                continue
            candidates.append({"helper": helper, "tick_pointer": tick_pointer,
                               "smooth_pointer": smooth, "raw_pointer": raw,
                               "real_clock_pointer": smooth + 12,
                               "simulation_clock_pointer": smooth + 16})
    if len(candidates) != 1:
        raise ValueError(f"Expected one loaded relocated Rally timing helper; found {len(candidates)}")
    return candidates[0]


def summarize(samples):
    first, last = samples[0], samples[-1]
    elapsed = last["wall_seconds"] - first["wall_seconds"]
    real_delta = last["real_clock"] - first["real_clock"]
    sim_delta = last["simulation_clock"] - first["simulation_clock"]
    clocks_monotonic = all(b["real_clock"] >= a["real_clock"] and b["simulation_clock"] >= a["simulation_clock"] for a, b in zip(samples, samples[1:]))
    summary = {"samples": len(samples), "sample_window_seconds": elapsed,
               "ticks_per_step": sorted({s["ticks_per_step"] for s in samples}),
               "clocks_monotonic": clocks_monotonic,
               "real_clock_delta": real_delta, "simulation_clock_delta": sim_delta}
    for name in ("raw_dt", "smoothed_dt"):
        values = [s[name] for s in samples]
        summary[name] = {"min": min(values), "median": statistics.median(values),
                         "mean": statistics.mean(values), "max": max(values)}
    if clocks_monotonic and elapsed > 0 and real_delta > 0:
        summary.update(real_clock_per_wall_second=real_delta / elapsed,
                       simulation_clock_per_wall_second=sim_delta / elapsed,
                       simulation_clock_per_real_clock=sim_delta / real_delta)
    return summary


def observe(base_url, seconds=15, interval=0.25, wait_seconds=20):
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            addresses = locate(get_memory(base_url, 0, 16 * 1024 * 1024))
            break
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.5)
    samples = []
    start = time.monotonic()
    while time.monotonic() - start <= seconds:
        code = get_memory(base_url, addresses["helper"], 64)
        data = get_memory(base_url, addresses["smooth_pointer"], 20)
        smooth, raw, _, real_clock, simulation_clock = struct.unpack("<5f", data)
        if not all(math.isfinite(v) for v in (smooth, raw, real_clock, simulation_clock)):
            raise ValueError("Non-finite timing data")
        samples.append({"wall_seconds": time.monotonic() - start,
                        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "ticks_per_step": code[8],
                        "pending_tick_counter": struct.unpack_from("<I", code, 0x36)[0],
                        "raw_dt": raw, "smoothed_dt": smooth,
                        "real_clock": real_clock, "simulation_clock": simulation_clock})
        time.sleep(interval)
    return {"addresses": {k: hex(v) for k, v in addresses.items()},
            "summary": summarize(samples), "samples": samples,
            "scope": "Read-only timing fields. Automatic scene state is not a visually observed race."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:9091")
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--interval", type=float, default=0.25)
    parser.add_argument("--wait-seconds", type=float, default=20)
    args = parser.parse_args()
    url = urllib.parse.urlsplit(args.base_url)
    if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"} or url.path not in {"", "/"} or url.query or url.fragment or url.username or url.password:
        parser.error("Use an HTTP loopback origin only")
    if args.seconds <= 0 or args.interval <= 0 or args.wait_seconds < 0:
        parser.error("Invalid timing interval")
    print(json.dumps(observe(args.base_url, args.seconds, args.interval, args.wait_seconds), indent=2))
