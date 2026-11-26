# Rally acceleration and pacing correction — version 1.2.1, build 6

The reported symptom was poor acceleration for both the player and an AI car on China, including with widescreen and distance disabled.

## Diagnosis

The original executable, bundled DATA/GFX/configuration, controls, DOSBox code and CPU settings match the earlier working backups. Disabling the optional graphics patches really did select the untouched original. There is no evidence that the update changed car physics data. The earlier session’s precise effective simulation rate was not recorded, so the comparison cannot establish why that session felt different.

The original Rally program waits for only one tick of its 100 Hz timer between frames. Its physics step is clamped to at least 0.02 seconds, so running faster than 50 frames per second can advance simulation faster than real time. Its physics also depends on step size. Rick Barber’s [pacing analysis](https://github.com/Rick-Barber/ScreamerRally-Recomp/blob/main/crates/sr-runtime/src/pacing.rs) documents excessive AI slip at 50 steps/s and chooses approximately 33 steps/s. The [reverse-engineering notes](https://github.com/Rick-Barber/ScreamerRally-Recomp/blob/main/docs/re/strt3fx.md#timing-verified) describe the original 1.1 race-time factor. Those notes concern the Glide build; the corresponding wait and both callers were independently verified in this exact software-renderer executable.

## Change

The derived launch executable changes only file byte `0x532d4` from `01` to `03`, making `cmp eax,1` become `cmp eax,3`. Original executable SHA-256: `0785e38567c475f25663e4022ec125e447a799004e34efa59758b50cfd84901d`. Guarded original function context at `0x532cc`: `50 a1 02 03 03 00 83 f8 01 7c f6 58 c3`. Both menu and race frame timers call this helper. No changed byte intersects any of the 15,403 parsed LE source fixups. The SOS timer, smoothing, 0.02..0.2 step clamps and original race 1.1 factor are unchanged.

The correction always applies in a freshly generated `RALLYMAC.EXE`; both original `START65H.EXE` copies and user saves/settings remain untouched. Optional graphics patches remain independent. The shared guest menu/render loop also caps at approximately 33 frames/s; there is no frame interpolation in this DOSBox wrapper. No code from Rick’s Windows runtime was incorporated.

## Verification

- All six graphics modes exactly match their independently verified previous executables with that single byte changed. Sixteen preparations exercised fresh and existing saves, mode toggling, stale-derived replacement, OFF/OFF saved settings, original/config preservation and a binary save sentinel. See [mode report](tests/pacing-mode-verification.json).
- Controlled headless A/B used the same ARM64 DOSBox host, auto CPU core and max protected cycles, optional graphics off, and guest executables differing by that single byte. Each run took 79 read-only timing snapshots over about 20 seconds. Control: median raw interval 0.010 seconds, simulation advanced 36.49 seconds over 19.92 wall seconds (1.83×). Corrected: raw interval consistently 0.030 seconds, smoothed interval about 0.033, simulation advanced 21.98 over 19.98 wall seconds (1.100×), preserving the original race factor. Both test engines stopped cleanly. See [timing measurements](tests/pacing-comparison.json). These automatic scenes were not visually observed races.
- A separate GUI check used China, Motrail, automatic transmission, original aspect and original distance. AI cars left the grid; holding Up for five seconds from rest moved the player car down the road. The game rendered and quit normally. This is a short functional check, not coverage of all tracks/cars or extended sessions.

The diagnostic HTTP observer is test-only. It is not enabled in the shipped configuration. The release remains native ARM64 with the same DOSBox code. Screamer and Screamer 2 apps were not updated.
