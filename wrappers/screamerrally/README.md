# Screamer Rally for Apple Silicon

Open `/Applications/Screamer Rally.app` to play. The launcher and bundled DOSBox Staging 0.83.1 runtime are native ARM64; Rosetta is not required. The original DOS game runs inside that runtime, with its CD music included.

## Launch options

The options window uses the original Rally Wales loading screen extracted from the game files. Choose **16:9 widescreen** and **Draw distance**, then click **Play**. Choices are independent and remembered. **Quit**, Escape and closing the window leave the saved choices unchanged.

Uncheck **Show options at launch** to open straight into the game. Hold **Option** while opening the app to show the options again.

- **Widescreen:** expands the camera to show more of the world. Menus and the HUD stretch to 16:9.
- **Original distance:** retains the original visibility limits. The timing correction below still applies.
- **Extended (2×):** uses a 104,000-unit object-admission radius.
- **Farther (2.5×, experimental):** uses a 130,000-unit radius. This can reveal scenery gaps, clipping or extra load; switch back to Extended or Original if a scene looks wrong.

The multipliers use the compiled 52,000-unit reference. Original scene-specific limits vary, so neither option guarantees that multiplier for the visible horizon. Terrain, far-plane, visibility-list and other renderer limits remain. The selected object threshold is preserved when scene setup updates the game's distance checks.

The unchanged signed distance calculation requires a radius below approximately 131,072 units. Farther stays just below this boundary; a simple 3× constant patch would exceed it and is not supported. Passing this arithmetic check does not prove every track or camera mode is safe.

## Acceleration and timing correction

Version 1.2.1 corrects Rally’s frame pacing on fast emulated CPUs. The original one-tick wait could run physics near 100 updates per second, even though its minimum simulation step is 0.02 seconds. This can distort grip, acceleration and AI behavior. The wrapper now waits at least three ticks of the original 100 Hz timer, targeting roughly 33 updates per second. This applies with widescreen and extended distance off as well as on.

The original DOS render loop is tied to simulation, so game drawing and DOS menu animation are also limited to about 33 frames per second. The native options window is unaffected. No Windows runtime or replacement renderer is included.

The bundled and writable original `START65H.EXE` remain unchanged. The corrected `RALLYMAC.EXE` is generated and checked on every launch. See [timing diagnosis and checks](pacing-fix.md), [six-mode verification](tests/pacing-mode-verification.json), and [measured timing comparison](tests/pacing-comparison.json).

## Saves and preferences

Your writable game files and saves are under:

```text
~/Library/Application Support/Screamer Native/screamerrally/Game/SR/
```

`settings.json` is in the parent `screamerrally` support folder. It stores `widescreen`, `distance_level` (0 original, 1 extended, 2 farther) and `show_options`; `extended_distance` remains for compatibility. Quit the game before editing preferences. Moving only `settings.json` aside restores default options without deleting saves.

The app retains immutable bundled originals and creates the writable `Game/SR` copy on first launch. Replacing or rebuilding the app preserves an existing writable folder and saves. Back up that folder before moving saves; do not delete it to reset options. Enhanced executable variants are regenerated from hash-checked bundled originals. The original `C:\SR` layout is preserved.

`runtime.log` and the regenerated `dosbox.conf` are in the same support folder as `settings.json`.

## Rebuild

Keep the source files, patch manifests and `artwork/` together. From the folder containing `build-native.py`, use a fresh output directory and an official DOSBox Staging 0.83.1 app bundle:

```sh
python3 build-native.py \
  --game screamerrally \
  --game-data "<owned-games>/ScreamerRally/Screamer_Rally_1997/ScrmRal" \
  --runtime "/path/to/DOSBox Staging.app" \
  --output "/private/tmp/screamerrally-rebuild"
```

The source directory must contain both `SR/` and `cd/srally.cue` plus `cd/srally.img`. This requires Python 3 and Xcode command line tools. The script reads the source files without changing them, rejects an unrecognized original executable and refuses to replace an existing output app. Local builds are ad-hoc signed by default; `--sign-identity` accepts a local signing identity.

See [distance review](distance-review.md), [mode verification](mode-verification.json), [bundle verification](screamerrally-verification.json), [verification notes](verification-notes.md) and [artwork provenance](artwork/README.md). All six aspect/distance combinations passed preparation and save-preservation checks. In an isolated headless normal-core test with widescreen off, 14 live snapshots confirmed all five Farther thresholds persisted through automatic scene setup; see the [live report](tests/live-distance-results.md). This does not establish a visually observed race or certify every track, mirror or camera mode.
