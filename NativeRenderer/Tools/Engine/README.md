# ARM64 live engine

This directory retains the complete local bridge patch against official DOSBox Staging 0.83.1, plus three upstream CMake/system-library fixes. The additional unified patch observes original Rally HUD writes and exposes bounded original texture reads. It also supplies an explicitly installed S1 graphics replacement with a short renderer-ready lease. CPU-core and physics/timer behavior remain unchanged.

The bridge is disabled unless `SCREAMER_METAL_BRIDGE=1`. The launcher binds the HTTP API to loopback. The extension provides cached original framebuffer pixels, normal guest keyboard transitions with a 600 ms release watchdog, and bounded atomic memory reads at a validated guest wait helper. The read endpoint never writes guest memory. `launch_engine.py` separately makes the documented guarded three-tick change to a private Rally executable.

Build dependencies on Apple Silicon: Xcode command line tools, CMake, Ninja, pkgconf, SDL2/SDL3, SDL2_image, asio, opusfile, iir1, speexdsp, mt32emu, fluid-synth, libslirp and framework Python 3.14 for application packaging. The tested Homebrew SDL2 is SDL2-compat, which dynamically loads SDL3. Required dependencies are build inputs; the packaged app loads private ARM64 copies.

```sh
python3 NativeRenderer/Tools/Engine/build_engine.py \
  --output /path/to/fresh-engine-build
```

`--archive /path/to/dosbox-v0.83.1.tar.gz` avoids downloading an already available archive. `--prepare-only` verifies and patches source without configuring/compiling. The archive and all eight patches have mandatory SHA-256 guards. Apply the three upstream fixes, then rally-bridge.patch, then unified-engine.patch, then s1-conventional-hud.patch, then s1-display-hud.patch, then s1-hud-cohort.patch. The prepare-only replay matched all 1,679 source files byte-for-byte. S1 graphics callbacks remain inactive until the game-specific runtime validates the owned executable and loaded mappings; active player-race behavior is still a candidate pending driving validation.

Source: [official v0.83.1](https://github.com/dosbox-staging/dosbox-staging/tree/v0.83.1). Upstream fixes: [system libraries](https://github.com/dosbox-staging/dosbox-staging/commit/e97e927c198960c809d18fae53280554ed0c975f), [zlib discovery](https://github.com/dosbox-staging/dosbox-staging/commit/d12e88ced5ae5b94c48bde4c2809b53da6f6ecae), [zlib linkage](https://github.com/dosbox-staging/dosbox-staging/commit/482477a6f48ba30520920c0a09732371ba1cd772).

The engine and local engine changes use GPL-2.0-or-later; `LICENSE-DOSBOX` is retained. No game binary, RAM capture or compiled dependency is included here.

The conventional-framebuffer patch accepts the original S1 framebuffer in validated ordinary conventional RAM, with flat DS/ES, paging off and A20 enabled. It retains range, ROM/code and write-handler guards. Passive tests verified these conditions; actual main-race HUD capture and native activation remain pending validation.
