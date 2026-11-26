# Live Rally bridge

This Python service connects the original DOS game's emulation to the native Metal frontend. It receives real user input from the frontend, reads completed guest state and the emulator's actual framebuffer, and prepares per-race mesh assets in child processes. It does not execute game physics, automate macOS input, or write simulation memory. Normal keyboard events use the custom engine's `KEYBOARD_AddKey` endpoint.

Run alongside `Execution/launch_engine.py`; the launcher atomically publishes `SESSION/layout.json` after resolving the original executable's LE layout. Framebuffer and normal keyboard service work before that file exists.

```sh
python3 bridge/live_bridge.py \
  --base-url http://127.0.0.1:9096 \
  --layout SESSION/layout.json \
  --state SESSION/state.json \
  --input SESSION/input.json \
  --cache-root SESSION/assets \
  --extractor-dir NativeRenderer/extractor \
  --parent-pid 12345
```

Use absolute paths from an app launcher. `--seconds` optionally bounds a diagnostic run; zero means the service follows its parent/lifecycle. `--hud-profile PATH` accepts a separately validated original-UI cutout profile. `PYTHONDONTWRITEBYTECODE=1` is set for extraction children and the bridge disables bytecode writes, keeping signed app resources unchanged.

## Engine protocol

Only plain loopback HTTP origins are accepted. The preferred custom engine endpoints are:

- `POST /api/v1/rally/read`: bounded `{ranges:[{address,size}],require_eip_ranges:[...]}`; returns base64 ranges, CPU registers, linear PC/SP, stack bytes and capture time. The range group is atomic between CPU steps. The bridge requests the known frame-wait PCs and classifies the saved return address as a menu or race timer.
- `POST /api/v1/rally/keys`: `{pressed_keys:[...],release_all:bool}` sends normal keyboard changes. The engine releases its owned keys after a 600 ms lease expiry.
- `GET /api/v1/rally/frame`: the actual cached BGRA image, with `X-Rally-Width`, `Height`, `Pitch`, `Sequence` and `Capture-Ns` headers.

The original executable SHA-256 and explicit LE mappings are validated. The live wait-helper bytes must still identify its relocated tick counter and the existing three-tick pacing correction. A completed atomic wait snapshot remains valid when pending ticks already exceed three; drawing may have used the minimum period. The stock multi-GET fallback instead requires compatible before/after wait phase, nondecreasing pending ticks below three, and equal real/simulation clocks.

Default polling is 100 Hz to find completed states; duplicate game-clock states retain their original pose timestamp. This rate is not the physics rate. Metrics report distinct observed game-clock transitions and active race time separately. Lost wait windows can make this an observation lower bound, not an all-frames count.

Clock-rate intervals include ordinary acquisition jitter, but a gap exceeding 150 ms ends the active segment. A pause with no accepted wait snapshots therefore does not enter the denominator when play resumes. Unique clock states remain counted across segments.

## State and input files

`state.json` uses `schema: "screamer-live/v1"` and is replaced atomically. It contains a process epoch, heartbeat `seq`/`sequence`, `pose_sequence`, capture/publication timestamps, status, camera, six stable scene IDs and root poses, asset epoch/paths, and framebuffer metadata. Canonical asset keys are `assets.world_scene` and `assets.cars_scene`; `scene`/`cars` aliases are retained.

Cross-process timestamps explicitly use Mach absolute nanoseconds on macOS, matching the native frontend. Python 3.9's process-relative `time.monotonic_ns()` must not be used for this protocol. Internal scheduling and lease intervals can still use the process-local monotonic clock.

The frontend atomically publishes `input.json`:

```json
{
  "schema": "screamer-input/v1",
  "epoch": "<current state epoch>",
  "seq": 1,
  "focused": true,
  "pressed_keys": ["up"],
  "press_counts": {"up": 1}
}
```

The independent 100 Hz input worker observes full held-key state and monotonically increasing initial-press counters. An 80 ms tap latch prevents a short press disappearing between file reads. Focus loss, invalid epoch, a 500 ms stale frontend lease, bridge shutdown and the engine's own lease release keys. After one release the bridge stops forcing zero state, allowing the original emulator window to receive its own keyboard input.

Canonical keys include arrows, enter, escape, space, tab, backspace, left/right shift, control, alt, letters, digits and F1–F12. `return`, `shift`, `ctrl` and `alt` aliases are normalized. A guarded ISR-table compare-and-swap fallback is available only with explicit `--allow-isr-input`; it is disabled by default and unnecessary with the custom normal keyboard endpoint.

## Assets, menus and pause

A stable real race starts a new asset epoch using track/condition/detail, loaded model/grid pointers and the transition from menus/attract state. One atomic 16 MiB capture is written into a fresh cache directory. A separate low-priority child runs the existing textured world and car extractors; input and framebuffer service continue. Both scene descriptors and capture hashes must validate before the paths are published. A new epoch never reuses stale assets merely because its track number matches.

While assets are pending, in menus/loading/attract mode, or when a race pose is older than 150 ms, the frontend receives `mode: "framebuffer"`. Attract flag `0x80` preserves the original credits/demo presentation. A stale race is labelled paused and falls back to the original image; this also covers wait-state loss, rather than asserting a fresh racing pose indefinitely.

Race mode is read from link address `0x1436dc`; the unrelated load/start/exit state at `0x13146c` is reported separately as `race_state`. During a real race, `player_telemetry` reports the original player record's raw gear, RPM, speed, position, velocity, smoothed simulation step and raw frame step. Speed remains in game units because the HUD's conversion has not been established; this metadata does not substitute invented speed units.

The cached framebuffer uses a bounded four-file ring. Its source format/dimensions/stride are validated. An original-UI profile must explicitly mark its nonempty in-bounds cutouts complete. Without that validated profile, the frontend keeps the entire original image even when Metal assets are ready. Car meshes currently retain captured wheel/part placement; the live root transforms do not animate those parts.

No recorded replay loops drive this service. Every pose comes from the running guest and every game key originates from current user input. The original three-tick guest pacing correction remains separate from renderer timing.

For an isolated automatic-demo renderer benchmark only, `--diagnostic-native-attract` permits native asset capture/presentation during attract scenes. It is false by default and is not enabled by a shipping launch. Diagnostic states retain `status: "attract"`, `is_attract: true` and an explicit `diagnostic_native_attract: true` marker. The diagnostic disables the entire keyboard worker, so frontend input files cannot drive the guest. Attract clocks do not enter real-race physics metrics. This benchmark does not validate driving, and a stale attract pose still falls back to the original framebuffer.

Repeated reads of the same completed game-clock state retain the first pose's capture timestamp and `pose_sequence`; only the publication heartbeat advances. Scene/owner transitions start a new pose identity. Retimestamping duplicate poses at the 100 Hz polling rate would otherwise produce false interpolation endpoints.

## Checks

```sh
python3 bridge/test_live_bridge.py
```

Twenty-nine synthetic tests cover input tap/held/focus/stale behavior, epoch rejection, normal-key lease renewal, avoiding repeated zero writes, bounded layout and batch validation, atomic-versus-legacy wait handling, pause/attract fallback, separate race-mode/state addresses, raw player telemetry, pause-safe clock intervals, diagnostic labelling/defaults, immutable duplicate-pose timestamps, canonical asset publication and a real cross-process Mach-clock regression. They do not drive the game or send network requests.

Controlled integration separately verified actual framebuffer updates, completed race-state reads, automatic world/car asset extraction and the normal keyboard input route. An explicitly approved disposable-game API test navigated Arcade/China/Motrail/Automatic, accelerated for 2.5 seconds (raw speed 0→48.86, gear 1→2), steered, paused and resumed, with every key action released. Pause correctly switched to the original image and excluded paused wall time from active-rate metrics.

A five-second real-race observation found 162 distinct clock states. The clock increments were 159 × 30 ms, 1 × 60 ms and 1 × 90 ms: 164 inferred original updates over 4.970 seconds, approximately 33.0 Hz, with three missed intermediate reads. Raw frame step remained 0.030 seconds and the original smoothed step 0.033 seconds. This supports the configured rate in that scene; it is separate from polling and native presentation rates, and does not establish all-track or long-session stability.

Original source-frame LCD pixels were compared with the same race's captured font/palette. At rest they match speed `000` and gear `1`; after acceleration they match speed `041` and gear `2`, with small dithering differences. The dark “8” silhouettes are the font's unlit segments. No numeric-HUD workaround is supported by those captures. Final Metal/HUD presentation and packaged-app lifecycle remain separate integration checks; passing transport tests alone does not establish complete renderer fidelity.
