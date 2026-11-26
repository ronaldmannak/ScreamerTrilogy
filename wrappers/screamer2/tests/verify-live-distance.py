#!/usr/bin/env python3
"""Read-only proof of live DOS distance constants through DOSBox Staging 0.83.1.

Example, after the operator visibly starts a Rally race:
  python3 verify-live-distance.py --profile rally --radius 130000 --phase race

Requires the separate live-distance-http.conf diagnostic overlay. All HTTP
requests are GETs to a loopback host. No guest memory is written, no process is
launched, and no screen/input automation is performed. Guest RAM is not saved.
Official protocol:
https://github.com/dosbox-staging/dosbox-staging/blob/v0.83.1/website/docs/0.83/manual/http-api.md
"""

import argparse
import datetime
import json
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


PROFILES = {
    "rally": {
        "calc_va": 0x7284E,
        "cmp_vas": [0x69FCF, 0x6A033, 0x6A0B9, 0x6A11D, 0x71892],
        "far_argument_va": 0x6AA57,
        "radii": [104000, 130000],
    },
    "screamer2": {
        "calc_va": 0x7ED4E,
        "cmp_vas": [0x764EF, 0x76553, 0x765D9, 0x7663D, 0x7DD92],
        "far_argument_va": 0x76F77,
        "radii": [104000],
    },
}


def stub(radius):
    return b"\xb9" + struct.pack("<I", radius * radius // 8) + b"\x90" * 10


def inspect_snapshot(memory, profile, radius):
    """Locate the code after LE relocation, then validate all five live sites.

    The runtime physical code base is inferred from the 15-byte patched setter.
    Relocated writer operands are checked against the actual five physical
    immediate addresses. This rejects an unrelocated executable-file copy.
    """
    candidates = []
    for actual_radius in profile["radii"]:
        signature = stub(actual_radius)
        start = 0
        while True:
            found = memory.find(signature, start)
            if found < 0:
                break
            start = found + 1
            sites = [found + va - profile["calc_va"] for va in profile["cmp_vas"]]
            writer_start = found + len(signature)
            if min(sites) < 0 or max(sites) + 6 >= len(memory):
                continue
            if writer_start + 30 > len(memory):
                continue
            if not all(memory[site] == 0x3D and memory[site + 5] == 0x73 for site in sites):
                continue
            writers = [writer_start + 6 * i for i in range(5)]
            if not all(memory[p:p + 2] == b"\x89\x0d" for p in writers):
                continue
            targets = [struct.unpack_from("<I", memory, p + 2)[0] for p in writers]
            if targets != [p + 1 for p in sites]:
                # Original LE operands are code-object offsets. The loaded DOS/4GW
                # flat addresses must identify these live physical CMP immediates.
                continue
            values = [struct.unpack_from("<I", memory, p + 1)[0] for p in sites]
            arg_address = found + profile["far_argument_va"] - profile["calc_va"]
            far_arg = struct.unpack_from("<i", memory, arg_address)[0]
            expected = radius * radius // 8
            candidates.append({
                "setter_physical_address": hex(found),
                "inferred_code_object_base": hex(found - (profile["calc_va"] - 0x10000)),
                "setter_radius": actual_radius,
                "expected_radius": radius,
                "expected_threshold": expected,
                "expected_threshold_hex": hex(expected),
                "live_cmp_immediates": [
                    {"address": hex(p + 1), "value": v, "hex": hex(v)}
                    for p, v in zip(sites, values)
                ],
                "relocated_writer_targets_match": True,
                "live_far_plane_argument": far_arg,
                "passed": actual_radius == radius and all(v == expected for v in values),
            })
    if not candidates:
        raise ValueError("No unique loaded patched code found in scanned RAM; wait for the game, confirm profile/patches and scan size.")
    if len(candidates) != 1:
        raise ValueError(f"Ambiguous loaded code: {len(candidates)} candidates; refusing a success verdict.")
    return candidates[0]


def read_url(base_url, path, timeout):
    # Never use environment HTTP proxies for a loopback emulator diagnostic.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(base_url + path, headers={"Accept": "application/octet-stream"}, method="GET")
    with opener.open(request, timeout=timeout) as response:
        return response.read()


def self_test():
    for name, profile in PROFILES.items():
        for radius in profile["radii"]:
            calc = 0x200000 + profile["calc_va"] - 0x10000
            memory = bytearray(calc + 256)
            memory[calc:calc + 15] = stub(radius)
            sites = [calc + va - profile["calc_va"] for va in profile["cmp_vas"]]
            for i, site in enumerate(sites):
                memory[site:site + 7] = b"\x3d" + struct.pack("<I", radius * radius // 8) + b"\x73\x04"
                writer = calc + 15 + i * 6
                memory[writer:writer + 6] = b"\x89\x0d" + struct.pack("<I", site + 1)
            arg = calc + profile["far_argument_va"] - profile["calc_va"]
            struct.pack_into("<i", memory, arg, -50000)
            assert inspect_snapshot(memory, profile, radius)["passed"]
            # The old bug: a scene setup resets one CMP to the nominal original.
            struct.pack_into("<I", memory, sites[2] + 1, 52000 * 52000 // 8)
            assert not inspect_snapshot(memory, profile, radius)["passed"]
            # An unrelocated file image must not pass as running code.
            struct.pack_into("<I", memory, calc + 17, profile["cmp_vas"][0] - 0x10000 + 1)
            try:
                inspect_snapshot(memory, profile, radius)
            except ValueError:
                pass
            else:
                raise AssertionError("Unrelocated image incorrectly accepted")
    print("Self-test passed: relocated image, overwritten CMP rejection, and unrelocated-copy rejection.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", choices=PROFILES)
    parser.add_argument("--radius", type=int, choices=[104000, 130000])
    parser.add_argument("--phase", default="unspecified", help="Operator-observed phase, e.g. intro, menu, China-race")
    parser.add_argument("--base-url", default="http://127.0.0.1:9090")
    parser.add_argument("--scan-bytes", type=lambda s: int(s, 0), default=16 * 1024 * 1024)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--wait-seconds", type=float, default=0, help="Retry startup/code discovery for at most this many seconds")
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.profile or args.radius is None:
        parser.error("--profile and --radius are required unless --self-test is used")
    profile = PROFILES[args.profile]
    if args.radius not in profile["radii"]:
        parser.error("Screamer 2 diagnostic supports the selected 104000-unit preset only")
    url = urllib.parse.urlsplit(args.base_url)
    if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"} or url.username or url.password or url.path not in {"", "/"} or url.query or url.fragment:
        parser.error("--base-url must be a plain HTTP loopback origin")
    if not 0 < args.scan_bytes <= 128 * 1024 * 1024:
        parser.error("--scan-bytes must be positive and no larger than the API's 128 MiB limit")
    if args.samples < 1 or args.interval < 0 or args.wait_seconds < 0 or args.timeout <= 0:
        parser.error("Invalid sample, interval, wait or timeout value")
    base_url = args.base_url.rstrip("/")
    deadline = time.monotonic() + args.wait_seconds
    for sample in range(args.samples):
        if sample:
            time.sleep(args.interval)
        while True:
            try:
                memory = read_url(base_url, f"/api/v1/memory/0/{args.scan_bytes}", args.timeout)
                if len(memory) != args.scan_bytes:
                    raise ValueError(f"Short snapshot: {len(memory)} bytes, expected {args.scan_bytes}")
                result = inspect_snapshot(memory, profile, args.radius)
                break
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
                if time.monotonic() >= deadline:
                    print(json.dumps({"passed": False, "profile": args.profile, "phase": args.phase, "error": str(error)}))
                    return 2
                time.sleep(min(1.0, max(0, deadline - time.monotonic())))
        result.update({"profile": args.profile, "phase": args.phase, "sample": sample + 1, "snapshot_bytes": len(memory), "utc": datetime.datetime.now(datetime.timezone.utc).isoformat()})
        print(json.dumps(result), flush=True)
        if not result["passed"]:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
