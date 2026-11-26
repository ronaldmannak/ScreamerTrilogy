#!/usr/bin/env python3
"""Verify six Rally modes against a pre-pacing app and a one-byte oracle.

Only --prepare-only is invoked. Both launchers use disposable --data-dir trees;
the DOS emulator and options UI are never started. The baseline must be an app
built before the always-on pacing correction, not an updated installed app.
"""

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


ORIGINAL_SHA256 = "0785e38567c475f25663e4022ec125e447a799004e34efa59758b50cfd84901d"
CONTEXT_OFFSET = 0x532CC
CONTEXT = bytes.fromhex("50 a1 02 03 03 00 83 f8 01 7c f6 58 c3")
PACING_OFFSET = 0x532D4
MODES = [(wide, level) for wide in (False, True) for level in range(3)]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def old_hashes(source):
    """Read only a literal assignment; do not import or execute the old harness."""
    for node in ast.parse(source.read_text()).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "RALLY_HASHES"
            for target in node.targets
        ):
            values = ast.literal_eval(node.value)
            require(set(values) == set(MODES), "Old Rally hash oracle must cover six modes")
            return values
    raise AssertionError(f"No RALLY_HASHES literal found in {source}")


def profile_for(app):
    profile = json.loads((app / "Contents/Resources/game-profile.json").read_text())
    require(profile["key"] == "screamerrally", f"Not a Rally app: {app}")
    return profile


def prepare(app, data, wide=None, level=None):
    command = [str(app / "Contents/MacOS/GameLauncher"), "--prepare-only", "--data-dir", str(data)]
    if wide is not None:
        command.append("--widescreen" if wide else "--original-aspect")
    if level is not None:
        command += ["--distance-level", str(level)]
    result = subprocess.run(command, text=True, capture_output=True, timeout=30)
    require(result.returncode == 0, f"Prepare failed ({app}): {result.stdout}{result.stderr}")
    return result


def verify(args):
    baseline = args.baseline_app.resolve()
    candidate = args.candidate_app.resolve()
    source = args.old_hashes_source.resolve()
    hashes = old_hashes(source)
    baseline_profile = profile_for(baseline)
    candidate_profile = profile_for(candidate)
    require(not baseline_profile["enhancements"].get("always_apply"), "Baseline is already pacing-corrected")
    require(candidate_profile["enhancements"].get("always_apply") is True, "Candidate lacks always_apply")
    require(not any(p["option"] == "compatibility" for p in baseline_profile["enhancements"]["patches"]),
            "Baseline already contains a compatibility patch")
    require(sum(p["option"] == "compatibility" for p in candidate_profile["enhancements"]["patches"]) == 1,
            "Candidate must have exactly one compatibility patch")
    original_path = Path("SR/START65H.EXE")
    derived_path = Path("SR/RALLYMAC.EXE")
    require(Path(candidate_profile["program"]) == original_path, "Original profile path changed")
    require(Path(candidate_profile["enhancements"]["derived"]) == derived_path, "Unexpected derived DOS path")
    resource_originals = [app / "Contents/Resources/game" / original_path for app in (baseline, candidate)]
    for path in resource_originals:
        data = path.read_bytes()
        require(sha(data) == ORIGINAL_SHA256, f"Bundled original changed: {path}")
        require(data[CONTEXT_OFFSET:CONTEXT_OFFSET + len(CONTEXT)] == CONTEXT,
                "Original pacing function context does not match the independent oracle")
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(candidate)], check=True,
                   capture_output=True, text=True, timeout=30)

    mode_reports = []
    expected = {}
    checks = []
    with tempfile.TemporaryDirectory(prefix="rally-pacing-verification-") as temporary:
        temporary = Path(temporary)
        old_data = temporary / "baseline data with spaces"
        new_data = temporary / "existing user data with spaces"

        # First prove that the old launcher really reproduces the pinned six
        # historical hashes. The candidate manifest supplies none of the oracle.
        for wide, level in MODES:
            prepare(baseline, old_data, wide, level)
            relative = derived_path if wide or level else original_path
            old_bytes = (old_data / "Game" / relative).read_bytes()
            require(sha(old_bytes) == hashes[(wide, level)], f"Old mode hash mismatch: {wide}, {level}")
            require(old_bytes[CONTEXT_OFFSET:CONTEXT_OFFSET + len(CONTEXT)] == CONTEXT,
                    "Old selected executable already has different pacing bytes")
            patched = bytearray(old_bytes)
            require(patched[PACING_OFFSET] == 1, "Expected old timer minimum is not one tick")
            patched[PACING_OFFSET] = 3
            expected[(wide, level)] = bytes(patched)
            mode_reports.append({"widescreen": wide, "distance_level": level,
                                 "old_sha256": sha(old_bytes), "candidate_sha256": sha(patched),
                                 "only_changed_offset": hex(PACING_OFFSET), "old_byte": "01", "new_byte": "03"})
        checks.append("Old installed app reproduced all six pinned pre-pacing mode hashes")

        # Seed with the old launcher to exercise an existing pre-update Game
        # directory, rather than only the candidate's first-run copy path.
        prepare(baseline, new_data, False, 0)
        game = new_data / "Game"
        sr = game / "SR"
        sentinel = sr / "PRESERVE.SAV"
        sentinel.write_bytes(b"Existing binary save sentinel\x00\xff\x80\r\n")
        preserved = [game / original_path, sentinel] + sorted(sr.rglob("*.CFG"))
        require((sr / "SCREAMER.CFG") in preserved, "Missing original path configuration fixture")
        require((sr / "CONFIG/CONTROLS.CFG") in preserved, "Missing controls fixture")
        snapshot = {str(path.relative_to(game)): sha(path.read_bytes()) for path in preserved}
        settings_path = new_data / "settings.json"
        saved_settings = (b'{\n  "widescreen": false,\n  "extended_distance": false,\n'
                          b'  "distance_level": 0,\n  "show_options": false,\n'
                          b'  "preserve_extra_key": "unchanged"\n}\n')
        settings_path.write_bytes(saved_settings)

        def check_candidate(wide, level, use_saved=False):
            result = prepare(candidate, new_data, None if use_saved else wide, None if use_saved else level)
            actual = (game / derived_path).read_bytes()
            require(actual == expected[(wide, level)], f"Candidate differs from one-byte oracle: {wide}, {level}")
            config = (new_data / "dosbox.conf").read_text()
            require("\ncd SR\nRALLYMAC.EXE\nexit\n" in config, "Always-corrected DOS program not selected")
            require("START65H.EXE" not in config, "Uncorrected original still selected")
            require("Program: SR/RALLYMAC.EXE\n" in result.stdout, "Prepare report does not identify corrected program")
            require(("aspect = stretch" in config) == wide, "Aspect setting changed")
            require(("shader = trilogy-widescreen" in config) == wide, "Shader setting changed")
            require(("window_size = 1280x720" in config) == wide, "Window size setting changed")
            require({str(path.relative_to(game)): sha(path.read_bytes()) for path in preserved} == snapshot,
                    "Original executable, configuration or save sentinel changed")
            require(settings_path.read_bytes() == saved_settings, "Prepare rewrote saved settings")

        sequence = MODES + list(reversed(MODES)) + [(False, 0), (False, 0)]
        for wide, level in sequence:
            check_candidate(wide, level)
        checks.append("All six candidate modes exactly equal the independently verified old mode plus only 0x532d4:01->03")
        checks.append(f"{len(sequence)} candidate preparations cover forward/reverse mode switching, repeated launches and OFF/OFF")

        # A stale pre-update derived executable must not bypass the compatibility
        # correction, even with both optional settings disabled.
        (game / derived_path).write_bytes(resource_originals[0].read_bytes())
        check_candidate(False, 0, use_saved=True)
        checks.append("OFF/OFF remembered preferences still select RALLYMAC; stale derived executable regenerated correctly")
        checks.append("Saved OFF/OFF choices and settings.json formatting/extra key remain byte-identical")
        checks.append(f"Writable original executable, {len(preserved) - 2} CFG files and binary save sentinel preserved")

        # Also exercise fresh first launch without importing old writable files.
        fresh_data = temporary / "fresh data"
        prepare(candidate, fresh_data, False, 0)
        require((fresh_data / "Game" / derived_path).read_bytes() == expected[(False, 0)],
                "Fresh OFF/OFF launch omitted compatibility correction")
        require(sha((fresh_data / "Game" / original_path).read_bytes()) == ORIGINAL_SHA256,
                "Fresh writable original was patched in place")
        require(not (fresh_data / "settings.json").exists(), "Headless first launch created saved preferences")
        checks.append("Fresh OFF/OFF first launch creates corrected derived executable and retains unmodified original")

    for path in resource_originals:
        require(sha(path.read_bytes()) == ORIGINAL_SHA256, f"Bundled original changed during test: {path}")
    checks.append("Both bundled original executables remain byte-identical to the pinned SHA-256")
    return {"result": "passed", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "baseline_app": str(baseline), "candidate_app": str(candidate),
            "old_hashes_source": str(source), "original_sha256": ORIGINAL_SHA256,
            "mode_count": len(MODES), "candidate_preparations": len(sequence) + 2,
            "scope": "prepare-only, no emulator or GUI launched, disposable data only; no physics or visual proof",
            "checks": checks, "modes": mode_reports}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-app", type=Path, default=Path("/Applications/Screamer Rally.app"))
    parser.add_argument("--candidate-app", type=Path,
                        default=Path("/private/tmp/rally-acceleration-fix/release/screamerrally/Screamer Rally.app"))
    parser.add_argument("--old-hashes-source", type=Path,
                        default=Path("/private/tmp/screamer-trilogy-update/tests/verify-trilogy.py"))
    parser.add_argument("--report", type=Path,
                        default=Path(__file__).resolve().with_name("pacing-mode-verification.json"))
    args = parser.parse_args()
    result = verify(args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
