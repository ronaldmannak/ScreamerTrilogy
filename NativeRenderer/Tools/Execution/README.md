# Execution probe

Source-only tools for loading the supported Screamer Rally 3dfx guest in an external DOSBox Staging 0.83.1 engine and collecting read-only snapshots for the native renderer. This directory contains no engine, executable, driver, disc image, game assets, RAM dump, or captured replay.

The probe copies the caller's `SR` directory into a new output directory, applies the guarded three-tick change to that copy, and launches a bounded headless guest. HTTP requests only read memory and registers. The source game and installed app are untouched. The copied guest can write its own scratch data.

## Requirements

- Python 3.9 or newer; standard library only.
- An external DOSBox Staging 0.83.1 executable with Voodoo emulation, the HTTP API, and SDL's dummy video/audio drivers.
- The verified owned game layout below. Exact executable and DOS Glide driver hashes are enforced; other editions are unsupported.

```text
GAME_ROOT/
  SR/STRT3FX.EXE
  SR/GLIDE2X.OVL
  SR/...other original game files...
  cd/srally.cue
  cd/...disc files referenced by that cue...
```

Use `--disc-cue` when the disc cue lives elsewhere. The tool does not download dependencies or locate installed apps automatically.

## Validate without running

Run the source-only guard tests from this directory:

```sh
python3 test_capture_probe.py
```

They use synthetic non-game inputs to check hash rejection before launch/output, unrelocated-image rejection, capture overwrite refusal and unsafe config-path rejection. They start no engine or server and are not runtime game tests.

From the repository root after this directory is copied to `NativeRenderer/Tools/Execution`:

```sh
python3 NativeRenderer/Tools/Execution/capture_probe.py \
  --engine "/path/to/DOSBox.app/Contents/MacOS/dosbox" \
  --game-root "/path/to/owned/Rally/game" \
  --output ../rally-captures/run-001 \
  --check-only
```

`--check-only` verifies paths, original hashes, LE mapping, expected instructions, the single changed byte and the derived executable hash. It creates no output and starts no engine.

## Capture

Run the same command without `--check-only`. Relative input and output paths resolve from the current working directory. The output directory must not already exist; use a distinct path for every session. Published capture files are opened exclusively and are never replaced.

The default port is `127.0.0.1:9091`; `--port` selects another loopback port. An occupied port is rejected before launch. The tool uses `core=auto`, protected-mode cycles `max`, 16 MiB guest RAM, Voodoo with 4 MiB video memory, and no optional widescreen/distance changes.

The probe waits up to 70 seconds for the automatic 3D scene. After capturing, it normally stops immediately. Add `--hold-seconds 45` to give the separate bridge capture client a brief read-only endpoint. The whole run has a 90-second budget plus bounded process cleanup. The engine is stopped in a `finally` block, including interruption/error paths.

Output includes:

```text
OUTPUT/
  Game/SR/                     scratch game copy and NATIVE3D.EXE
  dosbox.conf
  runtime.log
  initial-guest-ram.bin         optional early world snapshot
  initial-snapshot-metadata.json
  guest-ram.bin                 complete camera/world snapshot
  snapshot-metadata.json
  sequence/frame-000.bin        three same-session snapshots
  sequence/frame-000.json
  sequence/frame-001.bin
  sequence/frame-001.json
  sequence/frame-002.bin
  sequence/frame-002.json
  sequence/index.json
  probe-result.json
```

Paths inside `sequence/index.json` are relative to that index's directory. Metadata includes hashes, monotonic timestamps, CPU registers, resolved LE object bases, relocation evidence, and markers. Input engine/game paths in metadata are runtime provenance, supplied by the caller.

Keep output outside this source-only bundle: it contains owned game copies and guest RAM. The tool does not delete failed or completed output directories.

## Scope and remaining limitations

- The snapshot is atomic between emulated CPU steps, not synchronized to the logical end of a simulation or render frame. A nonzero camera pointer can identify the current view, including a mirror; the bridge should prefer the stable main-view camera.
- Full snapshots contain 16 MiB of the API's flat guest address space. They exclude the Voodoo device's separate texture/framebuffer memory. The sky texture is one known asset whose guest RAM copy can be freed after upload.
- The metadata's historical `physical_base` fields identify locations in that flat snapshot. Pointer bias zero was validated for this exact profile; this is not a generic DOS paging/segmentation interface.
- Three full snapshots use requested 0.3-second spacing and record actual timestamps. Full JSON/Base64 RAM transfer is an inspection path, not a 60 Hz transport. Use the bridge's sparse camera/car reader for motion capture.
- This is a guest-loading and capture tool, not an interactive native game launcher, emulator checkpoint API, renderer, or input bridge. A three-tick minimum limits simulation to at most 33⅓ steps/s when rendering keeps up; it does not guarantee that throughput.
- Hash/profile validation is portable, but actual engine operation has only been exercised with the earlier probe on macOS ARM64 and DOSBox 0.83.1. The packaged path/immutability changes received offline checks only; no further engines were launched for packaging. Linux/Windows engine execution, alternate game layouts, other executable hashes, log formats and device settings remain unvalidated.

The earlier probe loaded the real China world, enabling extraction of 1,596 models and 81,446 triangles. A separate sparse client captured six cars and the main camera at about 32.9 Hz over two seconds. These are historical prototype observations, not new benchmarks of this package or proof of complete native rendering parity.

See [patch provenance](PROVENANCE.md) for the exact supported bytes and primary sources.
