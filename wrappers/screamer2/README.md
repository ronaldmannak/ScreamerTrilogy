# Screamer 2 for Apple Silicon

Open `/Applications/Screamer 2.app` to play. The launcher and bundled DOSBox Staging 0.83.1 runtime are native ARM64; Rosetta is not required. The original DOS game runs inside that runtime, with its CD music included.

## Launch options

The options window uses an original Screamer 2 loading screen extracted from the game files. Choose **16:9 widescreen** and **Draw distance**, then click **Play**. Choices are independent and remembered. **Quit**, Escape and closing the window leave the saved choices unchanged.

Uncheck **Show options at launch** to open straight into the game. Hold **Option** while opening the app to show the options again.

- **Widescreen:** expands the camera to show more of the world. Menus and the HUD stretch to 16:9.
- **Original distance:** retains the original behavior.
- **Extended (2×):** uses a 104,000-unit object-admission radius, twice the compiled 52,000-unit reference. This is not a guarantee of twice the visible horizon: the original game varies its limits by scene, and terrain, far-plane, visibility-list and clipping limits remain. The patch keeps the selected object threshold in place when the game updates it during scene setup. Higher visibility can expose scenery gaps or increase load.

## Saves and preferences

Your writable game files and saves are under:

```text
~/Library/Application Support/Screamer Native/screamer2/Game/
```

The neighboring `settings.json` stores `widescreen`, `distance_level` (0 original, 1 extended) and `show_options`. `extended_distance` is retained for compatibility. Quit the game before editing preferences. Moving only `settings.json` aside restores default launch options without deleting saves.

The app keeps the bundled original files unchanged and makes the writable copy on first launch. Replacing or rebuilding the app preserves an existing writable game folder. Back up that folder before moving saves; do not delete it to reset launch options. Optional executable variants are regenerated from hash-checked bundled originals.

`runtime.log` and the generated `dosbox.conf` are in the same support folder. The launcher regenerates `dosbox.conf` on each launch.

## Rebuild

Keep the source files, patch manifests and `artwork/` together. From the folder containing `build-native.py`, use a fresh output directory and an official DOSBox Staging 0.83.1 app bundle:

```sh
python3 build-native.py \
  --game screamer2 \
  --game-data "/Applications/Screamer 2.app/Contents/Resources/game" \
  --runtime "/path/to/DOSBox Staging.app" \
  --output "/private/tmp/screamer2-rebuild"
```

This requires Python 3 and Xcode command line tools. The script refuses to replace an existing output app and rejects an unrecognized original executable. The source game files are read only. `--package "/path/to/original-gog.pkg"` can replace `--game-data`; package contents are extracted without running the installer. Local builds are ad-hoc signed by default; `--sign-identity` accepts a local signing identity.

See [distance review](distance-review.md), [mode verification](mode-verification.json), [bundle verification](screamer2-verification.json), [verification notes](verification-notes.md) and [artwork provenance](artwork/README.md). All four aspect/distance combinations passed preparation and save-preservation checks. In an isolated headless normal-core test with widescreen off, 11 live snapshots confirmed all five distance thresholds persisted through automatic scene setup; see the [live report](tests/live-distance-results.md). This does not establish a visually observed race or certify every track, mirror or camera mode.
