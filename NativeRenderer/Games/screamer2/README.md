# Screamer 2 native live runtime

This stage runs the owned original `S2_3DFX.EXE` in native ARM64 DOSBox Staging and reads completed camera/car state into the shared Metal renderer. It preserves the executable byte for byte, including its original two-tick wait. At a 100 Hz timer that is a minimum 20 ms frame period (about 50 Hz); the original in-race smoothing still produces about 0.022 seconds. Renderer timing is separate.

## Classic and Upgraded

The **0.3.7 / build 12** package opens a simple **Classic / Upgraded** choice over the original loading-screen background. Classic starts the embedded stable Apple Silicon wrapper with the original renderer, 4:3 framing and original draw distance. Upgraded renders with Metal at the window's display pixel resolution, including Retina scaling, with 16:9 framing and Full track draw distance. Widescreen extends the horizontal field of view without stretching the geometry. Full track uses the exported scene range and can reveal authored scenery gaps. The chosen experience is remembered in `LaunchOptions.json`; Cancel leaves it unchanged. Resolution, aspect and distance have no separate controls.

Menus and unsupported or incomplete views automatically use the complete original framebuffer inside Upgraded. Launching Classic selects the original renderer for the entire session. Upgraded preserves 16:9 framing; Classic uses 4:3. Original source images retain their authored resolution. Classic and Upgraded use their respective existing private save folders. Upgraded presentation targets 60 FPS while the original roughly 50 Hz simulation remains unchanged.

`Session.py` owns `Execution/launch_engine.py` and `bridge/live_bridge.py`. It accepts the same native-app entry arguments as Rally: `--resources`, `--session-dir`, `--data-dir`, `--parent-pid`. The engine reads bundled resources and copies mutable game files only on first launch into its separately owned data directory. Existing configuration and saves are retained on later launches. The executable and DOS Glide hashes are checked before every launch. Original source/data path overlap is rejected.

A standalone input-free diagnostic is runnable from this directory:

```sh
python3 -B Session.py \
  --session-dir /private/tmp/s2-new-session \
  --data-dir /private/tmp/s2-owned-test-data \
  --max-seconds 120 --audio dummy --read-only
```

For a packaged app, always pass `--resources /path/App.app/Contents/Resources`; the standalone `/Applications` source defaults are then unused. With no GUI parent, diagnostics require a finite duration at most 600 seconds. `--read-only` disables the entire keyboard worker. Only input-free automatic demos have validated these S2 upgrades; no scripted player-race inputs have been approved or run.

## Packaging inventory

Copy these runtime source files into `Contents/Resources/Live`:

- `Session.py`, `profile_s2.py`, `le_image.py`, `screamer2-live-profile.json`, `hud-profile.json`.
- `Execution/launch_engine.py`.
- All source modules in `bridge/`, including the S2 sky assets/state, exact overlay API/HUD publisher and original draw-distance helper.
- `extractor/extract_track.py`, `extractor/extract_cars.py`, `extractor/extractor_profile.py`, `extractor/texture_decode.py`, plus `profiles/screamer2.json` and relevant license files. The profile directory is required because the extractor resolves it relative to `Live`.

Bundle the native engine at `Contents/MacOS/dosbox`, private Python as in Rally, and the owned S2 game/CD files in `Contents/Resources/game`. Also bundle the genuine owned Rally DOS `GLIDE2X.OVL` in that game's resource root (SHA-256 `6981a7bd77445be7b360ca367af1e527927db396546db15b69803b16a67676a9`). S2's original source remains untouched. The runtime then has no dependency on another `/Applications` game install.

Build with `Games/build_game.py screamer2 --classic-app "/Applications/Screamer 2.app"` alongside the required engine, game-root, scene and output arguments described in [../README.md](../README.md). The builder embeds the matching owned Classic app and its original selection background.

Do not package probe output directories, full RAM, decoded game assets or diagnostic screenshots as source. `capture_s2.py`/`frame_png.py` are optional investigation tools, not required by the app launcher.

## Verified profile and feed

Original S2 executable SHA-256 is `e6c24c84650938f2baee5f4b571baa45bb09a93ba12dd24e3e1d2cefd9b6f3ec`. The wait helper is link `0x519b4`, counter `0x519ea`, exact runtime suffix `83 f8 02 7c f6 58 c3`. Explicit LE mappings are resolved using the relocated wait signature and many independent code fixups. Addresses are never host pointers.

Completed snapshots use the generic atomic range-read endpoint, gated to the helper's wait PCs. Saved return links `0x50bcb` and `0x50c6d` distinguish menu and race timers. Mode flags are `0x151748`, independent load/start/exit state `0x13fac0`, real/simulation clocks `0x153d94/98`, and count/track/condition/detail `0x151680`. These were independently mapped with relocation-aware source-code contexts and checked against a live capture. `live-field-homology.json` records the evidence.

The automatic attract scene has four car roots. The bridge and asset validator accept a bounded profile count rather than Rally's six-car constant. Pose timestamps remain immutable across repeated reads of the same completed game-clock state. Atomic file publication, Mach absolute clocks, original framebuffer fallback, scene hashes and model/pointer guards are retained. No physics state is written.

Camera-owner, world-key and car-pointer/model changes retire all cached guest pointers and increment a cache generation, even when track pointers are reused. The session starts a new asset epoch from that generation. A requested capture stays pending across the 250 ms throttle or a missed wait window; consuming a menu transition cannot lose the request. Original framebuffer fallback remains available while the new meshes load.

S2 state honestly uses `status: "attract"`, `mode: "attract"`, `is_attract: true`, `physics_period_ms: 20`. Attract updates do not enter real-race metrics. The shared renderer accepts this mode. Its explicit `--live-scene-only` option is a diagnostic geometry view, not a claim to preserve original overlays.

The main camera is the view pointer at `0x1396cc` plus `0xa64`. Projection is verified against original code, captured globals and paired source/native images: 640×480, focal 256/307.2, principal point 319/312, near 128. Live main-view height/width/centre are checked when the current view matches the main camera. The standard transform and row-major car rotations match the existing renderer contract.

## HUD and limits

The upgraded path now composes transparent pixels from exact final original Voodoo LFB writes, including same-color writes, rather than rectangular sky/road crops around text. The engine separately recognizes the three original gauge-needle line primitives. HUD completeness requires recognized coverage; a race also requires those needle primitives to have been observed. The rear view is the intentional opaque exception: it preserves the original 3D image within its verified mirror viewport. The original palette/source artwork remains unchanged.

Original sky/cloud textures are extracted from the owned track archives, checked against the live texture memory and mapped from original sky flags/colors and camera state. A bounded input-free automatic demo validated native 3840×2160 geometry, active sky and transparent original overlays with zero GPU/parser errors. This does not validate player controls, every dashboard/needle state, projected labels, transient messages, split-screen or all tracks. Unsupported or incomplete coverage retains explicit fallback/partial-HUD status; it is not silently promoted to complete.

Car roots update live; wheel/part poses remain frozen at extraction, with approximate reflection UV and batch-sorted transparency inherited from the current exporter. Smoke, shadows and some material/camera effects remain incomplete. This is not an all-track or long-session fidelity claim.

## Checks and evidence

```sh
python3 -B test_s2_live.py
```

Synthetic tests check S2 hashes/layout bounds, the untouched two-tick guard, rejection of Rally's three-tick bytes, relocated counter verification, separate callers, attract exclusion from race metrics, honest mode/period, read-only input, stale fallback, phase and split-screen HUD gating, preserved partial validation/missing labels, source dimensions, camera-mode forwarding and immutable duplicate-pose times. Recovery cases replace pointers/models/owners under the same scene key, verify cached pointers are retired, and verify deferred or missed captures retry without losing the request or churning the epoch. Tests send no network requests or inputs.

`attract-capture-v1` captured the original world after 13.6 seconds without inputs; `live-attract-v2` adds a source framebuffer captured 11.21 ms before the atomic RAM snapshot. `session-validation-v1` verifies the complete session/launcher/bridge/extractor path with four cars, raw step 0.020, smoothed step 0.022 and no bridge errors. The graphics work independently exported 2,000 world objects, 67,188 world triangles and four cars, decoded 344 textures with no unresolved materials, and rendered into an actual 3840×2160 Metal target. Paired 640×480 views align the house roof, trees, road and cars. See [Validation/CAMERA-COMPARISON.md](Validation/CAMERA-COMPARISON.md) and the extraction reports. These earlier alignment checks are separate from the newer sky/transparent-overlay automatic-demo validation.

The original update rate was also measured, rather than inferred solely from configuration. `original-clock-observation-v2.json` records an eight-second read-only automatic-attract interval: 381 distinct states, 380 observed transitions and 20 missed intermediate states. Original clock deltas reconstruct 400 updates over 7.99589 contiguous wall seconds, approximately 50.026 Hz. Every sample has raw step 0.020 and smoothed step 0.022; the largest error from an integer 20 ms clock increment is 6.72 microseconds. This is an automatic-attract timing result, not a race-control or long-session validation.
