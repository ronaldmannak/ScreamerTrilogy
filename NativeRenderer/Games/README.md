# Experimental native Metal renderers

The **0.3.7 / build 12** Metal packages open a **Classic / Upgraded** selector over each game's original loading artwork. Classic runs the embedded stable Apple Silicon wrapper with the original renderer, 4:3 framing and original draw distance.

Upgraded uses Metal at the window's display pixel resolution, including Retina scaling, with 16:9 framing and Full track draw distance. The wider view extends the horizontal field of view without stretching the geometry. Full track uses the exported scene range and may expose authored scenery gaps. Original textures retain their source resolution. The selector remembers the chosen experience; resolution, aspect and distance have no separate controls.

Unsupported or incomplete views automatically use the complete original framebuffer inside Upgraded. Classic selects the original renderer for the entire session. Cancel leaves the saved experience unchanged.

The original game executables remain unchanged. Both retain the original two-tick wait: short read-only observations reconstructed 50.016 Hz for Screamer and 50.026 Hz for Screamer 2. Presentation targets 60 Hz and interpolates sampled camera/actor transforms without advancing physics. These rates are independent measurements; an offscreen test does not measure displayed FPS.

Both packages passed genuine3840×2160 offscreen geometry checks. Screamer0.3.3/build8 additionally passed an approved isolated player race:36.3seconds native4K, acceleration/steering/checkpoint progression, about59.98observed foregroundFPS and zeroGPU/parser/HUD errors. This is a short observation, not a long-session guarantee. Screamer2 player controls and displayed4K cadence remain unverified.

## Coverage

- **Screamer:** all six original high-detail tracks and skies; live actor-part transforms, including wheels. The minimap now darkens the current native world through its original translucent shade, with source and bounded driving validation. Native racing supports F1/F3/F4 digital views; F2 cockpit and intros automatically use the original framebuffer. A guarded graphics lease replaces the old software polygon backend while the native renderer is ready. Exact original RAM byte-write coverage and a matching captured index/DAC snapshot compose the HUD. A PalmTown player race verified activation and driving. See [screamer/NATIVE-GRAPHICS.md](screamer/NATIVE-GRAPHICS.md).
- **Screamer 2:** live original world/car roots and verified camera projection. Original sky/cloud textures and transparent HUD composition from exact original Voodoo LFB writes are restored. An input-free automatic demo validated native 4K world, sky and overlays. Race needle primitives are source-guarded, and the rear view retains its original 3D pixels. Player-race controls, every camera layout and split-screen composition remain unverified.

Both builds remain experimental. Screamer 0.3.5/build10 restores original A0 window reflections; its other palette effects and some transient/camera combinations remain incomplete. Screamer 2 wheel/part poses and reflection mapping remain incomplete. Smoke/shadows also need further work. HUD readiness and coverage stay explicit in the protocol; unsupported composition uses the complete original framebuffer. The Upgraded desktop viewport preserves 16:9 framing, and the title identifies Original view fallback; Classic uses 4:3. The original installed wrappers and their saves remain independent recovery paths.

## Local bundles

The builder writes `<output>/Screamer.app` or `<output>/Screamer 2.app`. Each includes its Classic fallback and private ARM64 runtime, so Rosetta, Homebrew and an Xcode project are not runtime requirements.

Upgraded saves/configuration and per-session diagnostics live under `~/Library/Application Support/Screamer Metal/` or `Screamer 2 Metal/`. The selector stores `LaunchOptions.json` there. The private owned-data builder keeps Classic in its existing `Screamer Native/<game key>` save folder and its original locking. The public importer build keeps Classic data separately under the corresponding legacy Metal support folder's `ClassicData/` directory.

## Rebuild

Build the engine using `../Tools/Engine/README.md`. `build_game.py` requires owned game data and fresh output directories. For Screamer, export all six tracks first:

```sh
python3 NativeRenderer/Games/screamer/Runtime/Tools/export_scene.py \
  --game-root "/Applications/Screamer.app/Contents/Resources/game" \
  --track 1 --output /path/to/owned-scenes/track1
# Repeat --track 2 through 6 with corresponding fresh output directories.

python3 NativeRenderer/Games/build_game.py screamer \
  --engine /path/to/custom/dosbox \
  --classic-app "/Applications/Screamer.app" \
  --game-root "/Applications/Screamer.app/Contents/Resources/game" \
  --scene /path/to/owned-scenes/track1 \
  --all-scenes /path/to/owned-scenes \
  --output NativeRenderer/build-screamer-new
```

The required `--classic-app` must be the matching owned stable wrapper; its original background and self-contained app are embedded. For a Screamer 2 build, use `--classic-app "/Applications/Screamer 2.app"`. The initial dynamic meshes are optional: the live bridge exports the actual loaded actors. `--cars /path/to/captured/dynamic-scene` can include an initial owned capture. Screamer 2 uses `--scene`/`--cars` exported by its profile-driven extractor, and `--glide` selects the verified owned genuine DOS Glide driver. Its package receives a private driver copy; the installed source stays unchanged.

Game binaries, disc images, captures, meshes/textures and built apps remain local and ignored. Source and validation reports are retained in the game directories.
