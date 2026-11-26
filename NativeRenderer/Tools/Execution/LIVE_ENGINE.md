# Live engine lifecycle

`launch_engine.py` owns a live DOSBox child and an isolated, persistent game
directory. It does not automate menus or inject keys. The application bridge
handles real keyboard events through the custom engine's normal keyboard
endpoint. The original intro and menus remain available.

```sh
python3 launch_engine.py --engine /path/to/custom/dosbox \
  --game-root /path/to/owned/game --data-dir /path/to/private/userdata \
  --session-dir /path/to/new/session --parent-pid GUI_PID --port PORT
```

The game root must contain `SR/STRT3FX.EXE`, `SR/GLIDE2X.OVL`, and
`cd/srally.cue`; `--disc-cue` can select another owned disc image.
`capture_probe.py` supplies exact original hash, patch-context, and LE-layout
guards. Only the original wait immediate changes from one to three 100 Hz
ticks, retaining the verified 33 1/3 Hz pacing. The source executable is
never modified. A private derived `Game/SR/NATIVE3D.EXE` is regenerated from
the guarded source at launch.

The data directory is marked `.screamer-metal-owner.json` and locked while
running. Initial copying is staged before rename; later launches preserve
the private game configuration and saves. An unrelated nonempty directory
or a mismatched executable/driver is refused. Use a separate directory from
the working DOS wrapper's saves. Do not delete or re-create user data when
rebuilding the app.

The per-session directory publishes:

- `engine-status.json`: atomic lifecycle, PID, endpoint and diagnostic state.
- `layout.json`: immutable executable hash and resolved LE object mapping,
  published as soon as code loads, without waiting for a race.
- `boot-ram.bin`: immutable matching initial memory snapshot; a world may
  not yet have loaded at capture time.
- `dosbox.conf` and `runtime.log`: exact guest configuration and engine log.

The live bridge may start before `layout.json` exists. Framebuffer and normal
keyboard endpoints work during initial loading and menus. Dynamic asset
extraction is owned by that bridge; the launcher's optional `--extractor`
is disabled unless explicitly supplied.

Default video is SDL dummy (`--video hidden`) and audio is CoreAudio on
macOS (`--audio on`). It sets `SCREAMER_METAL_BRIDGE=1` for the custom API,
binds the server to loopback, enables the Voodoo emulation, and starts the
original 3dfx executable. `--audio dummy` is available for bounded tests;
`--video window` is a diagnostic alternative. The GUI should display cached
engine frames for menus and loading, and native geometry only after the
bridge validates a loaded race.

SIGTERM/SIGINT, direct-parent exit, or `--parent-pid` exit stop the child.
`--max-seconds` adds a finite diagnostic limit; zero means the application
owns the lifetime. Cleanup waits five seconds before killing an unresponsive
owned child. The session orchestrator should stop the input bridge first,
allowing it to release held keys while the engine still runs.

`--check-only` validates source and patch prerequisites without creating
user data, starting an engine, or opening a network endpoint. Existing
published layouts are not overwritten; create a new session directory.

The launcher's periodic phase/status reads are diagnostic and are not an
atomic simulation sample. The live bridge must use the custom CPU-step
batch-read endpoint, guard the known wait helper, and deduplicate physics
ticks. A boot snapshot alone does not establish a loaded track or a stable
physics boundary. Do not use raw memory writes to change game timing,
advance simulation, drive menus, or alter unvalidated guest state.
