# Screamer for Apple Silicon

Open `/Applications/Screamer.app` to play. The launcher and bundled DOSBox Staging 0.83.1 runtime are native ARM64; Rosetta is not required. The original DOS game runs inside that runtime, with its CD music included.

## Launch options

The options window uses an original Screamer loading screen extracted from the game files. Choose **16:9 widescreen** and **Draw distance**, then click **Play**. Choices are independent and remembered. **Quit**, Escape and closing the window leave the saved choices unchanged.

Uncheck **Show options at launch** to open straight into the game. Hold **Option** while opening the app to show the options again.

- **Widescreen:** expands the camera to show more of the world. Menus and the HUD stretch to 16:9.
- **Original distance:** retains the original behavior.
- **Extended +20%, +30% or +40% object visibility:** extends the visibility of managed animated objects. These percentages do not extend the road, terrain or overall scenery horizon. Original renderer limits remain; higher settings can reveal clipping or increase load.

## Saves and preferences

Your writable game files and saves are under:

```text
~/Library/Application Support/Screamer Native/screamer/Game/
```

The neighboring `settings.json` stores `widescreen`, `distance_level` (0 original, 1 +20%, 2 +30%, 3 +40%) and `show_options`. `extended_distance` is retained for compatibility. Quit the game before editing preferences. Moving only `settings.json` aside restores default launch options without deleting saves.

The app keeps the bundled original files unchanged and makes the writable copy on first launch. Replacing or rebuilding the app preserves an existing writable game folder. Back up that folder before moving saves; do not delete it to reset launch options. Optional executable variants are regenerated from hash-checked bundled originals.

`runtime.log` and the generated `dosbox.conf` are in the same support folder. The launcher regenerates `dosbox.conf` on each launch.

## Rebuild

Keep the source files, patch manifests and `artwork/` together. From the folder containing `build-native.py`, use a fresh output directory and an official DOSBox Staging 0.83.1 app bundle:

```sh
python3 build-native.py \
  --game screamer \
  --game-data "/Applications/Screamer.app/Contents/Resources/game" \
  --runtime "/path/to/DOSBox Staging.app" \
  --output "/private/tmp/screamer-rebuild"
```

This requires Python 3 and Xcode command line tools. The script refuses to replace an existing output app and rejects an unrecognized original executable. The source game files are read only. `--package "/path/to/original-gog.pkg"` can replace `--game-data`; package contents are extracted without running the installer. Local builds are ad-hoc signed by default; `--sign-identity` accepts a local signing identity.

See [distance review](distance-review.md), [mode verification](mode-verification.json), [bundle verification](screamer-verification.json) and [artwork provenance](artwork/README.md). All eight aspect/distance combinations passed preparation and save-preservation checks; a short live check also reached and drove a race at +40% with widescreen. These checks do not cover every track or camera mode. [Verification notes](verification-notes.md) include the limited test scope and an unresolved invalid-opcode observation after an earlier long unattended demo run.
