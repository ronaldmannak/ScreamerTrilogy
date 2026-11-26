# Screamer Rally: Classic and native Metal

For current source-only setup and the game-data-free **0.4.0** apps, start with the [repository README](../README.md). App names are now Screamer, Screamer 2 and Screamer Rally; internal support folders retain their legacy Metal names. The **0.3.x** measurements below describe earlier local data-bearing builds.

Version **0.3.7 / build 12** gives all three Metal apps a simple prelaunch **Classic / Upgraded** choice over each game's original loading-screen background. Classic starts an embedded stable Apple Silicon wrapper with the original renderer, 4:3 framing and original draw distance. Upgraded runs the original game in ARM64 DOSBox while Metal draws the world and cars. The chosen experience is remembered; Cancel leaves it unchanged.

Upgraded renders at the window's display pixel resolution, including Retina scaling, with a 16:9 view and Full track draw distance. Widescreen extends the horizontal field of view without stretching the geometry. Full track uses the exported scene's range and can reveal authored scenery gaps. Resolution follows the window and display; there are no separate resolution, aspect or distance choices. Original textures retain their source resolution.

Original physics remains unchanged: about 33 Hz for Rally and 50 Hz for Screamer and Screamer 2. Upgraded presentation targets 60 FPS with delayed camera/car interpolation. Menus, loading, pause and unsupported modes use the original framebuffer. These transitions happen automatically inside Upgraded; launching Classic selects the original renderer for the entire session.

The Rally builder produces `<output>/Screamer Rally.app`, with identifier `local.screamer-rally.metal-player`. Double-click it to choose an experience and play using the original keyboard controls. Closing the window or ⌘Q stops its private engine. It bundles ARM64 Python, DOSBox and their libraries; Homebrew, Rosetta and an Xcode project are not runtime requirements. Original game files are owned local build inputs and remain excluded from Git.

Upgraded configuration/saves live under `~/Library/Application Support/Screamer Rally Metal/GameData`; logs and per-session metrics are in its `Sessions` directory. Classic uses its existing `Screamer Native/screamerrally` support folder. Launch preferences are stored separately as `LaunchOptions.json` in the Metal support folder. The original installed wrappers and the `working-wrappers-2026-11-24` checkpoint remain independent.

## Verified milestone and limitations

A short actual China Arcade race exercised acceleration, steering, pause/resume and key release. Live native output measured **59.583 displayed FPS**, with 16.6668 ms presentation-interval p95 on the M5 Max. Original game-clock increments indicated **32.997 physics steps/s**. A separate live **3840×2160 offscreen render** passed with 0.7652 ms GPU-time p95; this is genuine geometry rasterization, not framebuffer upscaling. Offscreen output does not measure displayed FPS. See [Validation/LIVE.md](Validation/LIVE.md) for the reports and scope.

This remains experimental. Wheel animation, smoke and shadows are incomplete; reflections use approximate UVs and transparency is sorted by batch. The original sky is restored and the HUD uses exact transparent original drawing coverage. Mirrors retain their original pixel view. Upgraded viewports preserve 16:9 framing, including constrained windows and fullscreen; Classic uses 4:3. Native races currently require the six-car profile; other modes preserve the original framebuffer. Broader track/race-transition and long-session validation remains outstanding. Original textures retain their source resolution.

## Screamer and Screamer 2: experimental Metal

Current builds name the three apps **Screamer.app**, **Screamer 2.app** and **Screamer Rally.app**. The same selector is included in each app. Their original executables and roughly 50 Hz timing remain unchanged. Both passed genuine 3840×2160 offscreen geometry checks. Screamer additionally passed an isolated 36.3-second native 4K player race at about 59.98 observed foreground FPS; its minimap preserves the original translucent darkening. Screamer 0.3.5/build10 also restores the original reflective window geometry/material with live environment offsets and frame selection; isolated 4K capture and original-UV GPU checks pass. See [Games/screamer/NATIVE-GRAPHICS.md](Games/screamer/NATIVE-GRAPHICS.md) and [minimap validation](Validation/screamer-minimap-runtime.json).

Screamer 2's original sky/clouds and exact transparent original LFB overlays are now restored and validated in an input-free automatic demo. Player-race inputs and displayed 4K cadence remain unverified. Wheel/part animation, reflections, smoke, shadows and some camera/effect combinations remain incomplete; these updates do not establish that every rendering artifact is fixed. See [Games/README.md](Games/README.md) for coverage and build instructions.

## Rebuild the playable app

The engine recipe and required build dependencies are documented in [Tools/Engine/README.md](Tools/Engine/README.md). Build into fresh directories:

```sh
python3 NativeRenderer/Tools/Engine/build_engine.py --output /path/to/fresh-engine
python3 NativeRenderer/build_playable.py \
  --engine /path/to/fresh-engine/build/dosbox \
  --classic-app "/Applications/Screamer Rally.app" \
  --game-root "/Applications/Screamer Rally.app/Contents/Resources/game" \
  --initial-scene NativeRenderer/Assets/Extracted/china \
  --initial-cars NativeRenderer/Assets/Extracted/cars \
  --output NativeRenderer/build-live-new
```

The initial owned scene is a startup resource only. The bridge extracts the actual loaded race into a private per-session cache and publishes complete assets atomically. [Tools/Execution/LIVE_ENGINE.md](Tools/Execution/LIVE_ENGINE.md) covers engine lifecycle and original executable guards. [bridge/README.md](bridge/README.md) documents snapshots/input. [NativePreview/README-live.md](NativePreview/README-live.md) covers the native client, interpolation, asset replacement and presentation scheduling. [Tools/Packaging/README.md](Tools/Packaging/README.md) covers the private runtime.

```sh
python3 -m unittest discover -s NativeRenderer/bridge -p 'test_*.py'
python3 -m unittest discover -s NativeRenderer/extractor -p 'test_*.py'
python3 -m unittest discover -s NativeRenderer/Tools/Execution -p 'test_*.py'
python3 NativeRenderer/bridge/verify_metal_contract.py
'NativeRenderer/build-live/Screamer Rally.app/Contents/MacOS/RallyMetalPreview' --check-math
```

The separately retained captured-scene preview in `build/Screamer Rally Metal Preview.app` does not execute the game. Its historical measurements are in [Validation/README.md](Validation/README.md). The `--scene`, `--cars`, `--replay`, `--offscreen`, `--width`, `--height`, `--frames`, `--report` and `--check-math` diagnostic options remain available. Explicit `--live` accepts an externally supervised session; explicit offscreen rendering skips app-owned startup. Standalone developer previews and explicit `--live` diagnostics retain the Rendering menu and command-line rendering controls; bundled game sessions use the two launch experiences.

## Attribution and local assets

The extractor and transform/material conventions follow Rick Barber's [ScreamerRally-Recomp](https://github.com/Rick-Barber/ScreamerRally-Recomp). See `LICENSE` and `THIRD_PARTY_NOTICES.md`. Native renderer/extractor adaptations use GPL-3.0-only; the DOSBox engine modifications use GPL-2.0-or-later.

Original games, disc images, memory captures, extracted meshes/textures, PNGs, built apps and Instruments traces stay local and ignored. No game download or remote publication is part of the build.
