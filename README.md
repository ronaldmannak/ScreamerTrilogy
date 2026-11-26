# Screamer Trilogy for Apple Silicon

Play **Screamer**, **Screamer 2** and **Screamer Rally** on Apple Silicon Macs using native ARM64 DOSBox Staging and an experimental Metal renderer. Rosetta is not required.

This [repository](https://github.com/ronaldmannak/ScreamerTrilogy) contains source and build tools. **There is currently no downloadable binary release.** Build the apps locally, then import your own supported game copies. Original games, discs, music, textures, loading art and icons are excluded from the repository.

## Classic and Upgraded

Each app offers two experiences after setup:

- **Classic:** original graphics, original 4:3 framing and original draw distance.
- **Upgraded:** Metal rendering at the window/display's pixel resolution, including Retina scaling, a wider **16:9 field of view**, and **full-track draw distance**. Widescreen extends the horizontal view. Original textures retain their source resolution.

The original game logic runs in DOSBox. Physics retains approximately **50 Hz** for Screamer and Screamer 2, and **33 Hz** for Rally. Metal presentation targets **60 FPS**, interpolating camera/car snapshots between game updates. Menus, loading screens and unsupported views use the original framebuffer.

## First launch: import your game

1. [Build the apps](#build-on-macos), then open the matching locally built `Screamer.app`, `Screamer 2.app` or `Screamer Rally.app`.
2. Choose your owned GOG macOS `.app`, GOG `.pkg`/`.dmg`, or an extracted game installation folder. The importer verifies recognized game versions, copies the required data and prepares local artwork/scene resources.
3. Choose Classic or Upgraded and start the game.

Installer packages are expanded as data; their installer scripts are not run. Disk images are mounted read-only. Raw ISO/disc images alone are unsupported. The importer checks exact supported file hashes, so other editions or modified executables may be rejected.

**Screamer 2 also requires a compatible, owned `GLIDE2X.OVL` DOS Glide driver.** If prompted, select that file or an owned Screamer Rally installation containing it.

Imported content and per-game configuration live in `~/Library/Application Support/Screamer Metal/`, `Screamer 2 Metal/` or `Screamer Rally Metal/`. These support-folder names retain `Metal` for save compatibility. The signed app remains unchanged. See [import and command-line instructions](docs/PUBLISHING.md#importing-owned-game-files).

## Build on macOS

Use an Apple Silicon Mac with Xcode command-line tools, CMake, Ninja, pkgconf and framework Python 3.14. Engine dependencies include SDL2/SDL3, SDL2_image, asio, opusfile, iir1, speexdsp, mt32emu, fluid-synth and libslirp. The tested SDL2 build uses SDL2-compat and loads SDL3. See the [engine recipe](NativeRenderer/Tools/Engine/README.md) and [runtime packaging requirements](NativeRenderer/Tools/Packaging/README.md).

The **current locally built dependency set requires macOS 27.2**. The packager calculates each app's minimum from its bundled native libraries. This is a property of those local dependencies; supporting older macOS versions requires compatible dependency rebuilds and validation. It is not an inherent requirement of the DOS games or Metal frontend.

From the repository root, build the pinned DOSBox Staging **0.83.1** source with the retained bridge patches:

```sh
python3 NativeRenderer/Tools/Engine/build_engine.py \
  --output NativeRenderer/build-engine
```

The engine tool downloads the official source archive and checks its pinned SHA-256 and patch hashes. An existing archive can be supplied with `--archive /path/to/dosbox-v0.83.1.tar.gz`.

Supply an official DOSBox Staging resources tree containing `shaders/interpolation/sharp.glsl`, then build the three game-data-free apps:

```sh
python3 NativeRenderer/Tools/Packaging/build_public.py \
  --engine NativeRenderer/build-engine/build/dosbox \
  --engine-resources "/path/to/official/DOSBox-Staging.app/Contents/Resources" \
  --python-prefix /opt/homebrew/opt/python@3.14 \
  --output NativeRenderer/build-public
```

The output contains `Screamer.app`, `Screamer 2.app` and `Screamer Rally.app`. Both output directories must be fresh. Build outputs stay in ignored `NativeRenderer/build-*/` directories. `--game screamer`, `--game screamer2` or `--game screamerrally` builds a selected game; the default builds all three. Public packages default to **0.4.0 / build 13** and bundle their ARM64 engine, Python and libraries. Homebrew and build tools are build-time dependencies.

The public builder takes runtime/compiler inputs without original game files. Its artifact check rejects known game payloads and verifies an authored startup placeholder. Local packages use ad-hoc signing; Developer ID signing, notarization and binary-release dependency/source compliance remain separate release work. See [building public app candidates](docs/PUBLISHING.md#building-a-public-app-candidate).

## Current limitations and validation

The Metal path remains experimental. Screamer 2 and Rally reflection mapping, wheel/part animation, smoke, shadows and some camera/effect combinations remain incomplete. Full-track drawing can reveal gaps in the original scenery. Split-screen and broader track/race transitions need further validation. Unsupported composition falls back to the original framebuffer.

Source-only tests cover import validation, failure cleanup and publication guards. Local data-import, packaging, launch-option and offscreen checks do not establish complete player-race coverage or compatibility across Macs. Historical renderer measurements and their scope are documented in [renderer validation](NativeRenderer/README.md#verified-milestone-and-limitations) and [per-game coverage](NativeRenderer/Games/README.md).

## Tests without original game data

These synthetic tests run without starting a game; CI runs them on Linux with Python 3.12:

```sh
python3 -m unittest discover -s Tools/Publication/tests -v
python3 -m unittest discover -s NativeRenderer/Importer -p 'test_*.py' -v
python3 -m unittest discover -s NativeRenderer/Tools/Packaging -p 'test_public*.py' -v
python3 Tools/Publication/audit_repository.py --history --report /tmp/screamer-source-audit.json
```

The audit checks current source and reachable history for non-source payloads, known credential patterns and personal paths. It assists review; it does not determine copyright permissions. [Publication instructions](docs/PUBLISHING.md) explain sanitized source exports and binary-distribution requirements.

## How it fits together

```text
NativeRenderer/Launcher/          First-launch import and Classic/Upgraded selection
NativeRenderer/Importer/          Owned-data validation, copying and extraction
NativeRenderer/NativePreview/     AppKit/Metal renderer and shaders
NativeRenderer/Games/             Screamer and Screamer 2 runtime adapters
NativeRenderer/bridge/            Rally snapshots, HUD/sky and live protocol
NativeRenderer/Tools/Engine/      Pinned DOSBox build recipe and bridge patches
NativeRenderer/Tools/Packaging/   Self-contained, game-data-free app packaging
wrappers/                        Classic ARM64 launchers and enhancement recipes
Tools/Publication/               Source/history audit and sanitized source export
```

A separate DOSBox process executes the game. Python adapters publish live state and extracted resources; the Metal frontend renders those snapshots. See [renderer architecture](NativeRenderer/README.md) and the [live bridge contract](NativeRenderer/bridge/README.md).

## Credits and license

The native extractor and transform/material work builds on [Rick Barber's ScreamerRally-Recomp](https://github.com/Rick-Barber/ScreamerRally-Recomp). Enhancement recipes credit [AkitaOnRails/rea-screamer-trilogy](https://github.com/akitaonrails/rea-screamer-trilogy). [DOSBox Staging](https://github.com/dosbox-staging/dosbox-staging) supplies the emulator/runtime foundation.

First-party source defaults to **GPL-3.0-only**. MIT enhancement contributions, GPL-2.0-or-later DOSBox code/shaders and other dependencies retain their respective licenses and notices. See [LICENSE](LICENSE), [license scope](LICENSING.md) and [third-party notices](NativeRenderer/THIRD_PARTY_NOTICES.md). Original game assets remain the property of their rights holders and must be supplied by each user.
