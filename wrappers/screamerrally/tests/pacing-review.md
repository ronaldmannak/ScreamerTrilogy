# Rally timing A/B verification

Generated 2026-11-25T03:52:25.684958+00:00. The original one-tick game loop demonstrably over-advances simulation on the current auto/max emulator configuration. The three-tick candidate restores the documented race simulation-to-clock factor in this bounded automatic-scene test.

| Guest | Wait ticks | Samples | Median raw dt (s) | Median smoothed dt (s) | Guest real-clock delta (s) | Guest simulation delta (s) | Wall sample window (s) | Simulation/wall ratio |
|---|---|---|---|---|---|---|---|---|
| control | 1 | 79 | 0.010000 | 0.020000 | 19.940 | 36.493 | 19.919 | 1.832 |
| candidate | 3 | 79 | 0.030000 | 0.033000 | 19.980 | 21.977 | 19.979 | 1.100 |

Both real-clock/wall ratios were approximately1.000. The original guest advanced simulation about1.83seconds per wall second; the patched guest advanced1.100seconds per wall second, preserving Rally's existing intentional1.1factor. The candidate raw_dt was0.030seconds in every sample and smoothed_dt converged to0.033seconds. The baseline raw_dt median was0.010seconds while the0.020physics floor dominated. These quantitative results match the known simulation-rate dependency; they are not an acceleration/traction measurement with human driving input.

## Controlled conditions and scope

Both runs used the same DOSBox0.83.1 executable from `/private/tmp/rally-acceleration-fix/release/screamerrally/Screamer Rally.app/Contents/MacOS/dosbox`, `core=auto`, `cpu_cycles_protected=max`,16MiB guest RAM, dummy SDL video/audio and software texture output. The two guest executables used the same RALLYMAC.EXE basename, with optional widescreen/distance patches off. They differ at exactly one file byte. Each observation began after five seconds of startup and measured approximately20seconds of automatic scene execution. API requests were read-only, bound to loopback9091/9092, and used no input injection. No GUI was launched or operated by this diagnostic. Each engine was terminated after its measurement and exited0; no diagnostic engine remains running.

This supports repairing the game loop rather than choosing a host-dependent fixed CPU cycle rate. It does not prove the user's own-car acceleration curve or every track, camera, long session, or renderer path. The root's separate GUI test supplies visual validation.

## Exact guarded patch

Original supported START65H.EXE: size1,145,058; SHA-256 `0785e38567c475f25663e4022ec125e447a799004e34efa59758b50cfd84901d`.

- Wait helper VA0x402cc / raw0x532cc: `50 a1 02 03 03 00 83 f8 01 7c f6 58 c3`.
- CMP VA0x402d2 / raw0x532d2: expected `83 f8 01`, replacement `83 f8 03`.
- The changed immediate is VA0x402d4 / raw0x532d4. **Raw0x532d3 is F8 (the ModR/M byte), not the immediate.** The older upstream table's532d3 value must not be copied blindly.
- Source fixups parsed:15,403. No source relocation overlaps the3-byte CMP. A neighboring four-byte fixup at raw0x532ce targets code object1offset0x30302 (the tick counter) and is untouched. The candidate's thirteen-byte context guard preserves these four source bytes exactly, so DOS/4GW still applies the original relocation.
- Timing-only candidate hash: `ff46ee5f74bf2b228a7a462cb25c50a228ec705d30e69b2b291887db036e1c98`. All other bytes match the original.

The helper preserves EAX/stack exactly as before. No change is made to the HMI100Hz callback, dt floor/ceiling, race1.1 smoothing multiplier, physics lookup tables, FPU behavior, control data, or optional rendering code. No static LE target reference to the immediate was found, unlike the distance constants' known self-modifying setup routine.

Menu frame timer entry VA0x3f4ce (call at0x3f4dc) and race frame timer entry VA0x3f570 (call at0x3f57e) both call this same wait helper. Global03 therefore sets a minimum30ms wait for guest menus too (at most33⅓steps/s when rendering keeps up). A global02 would avoid the worst100Hz case but still run at50steps/s, where Rick measured substantially worse initial AI slip than33or25. Keeping guest menus at50while races use33would require separately guarded runtime logic rather than this one-byte repair. Native options-screen performance is unaffected by the guest menu rate.

## Vetted read-only observer

`verify-live-pacing.py` finds the relocated helper and confirms its tick-counter pointer equals helper+0x36. It checks the two E8 call targets, obtains the actual relocated smoothed_dt pointer from both timers' post-call A1 operands, and obtains raw_dt from the race timer's first FSTP. It verifies raw_dt=smoothed_dt+4.

The original UpdateClocks routine at VA0x3f653 / raw0x52653 independently confirms the adjacent field layout: smoothed_dt at+0, raw_dt at+4, real-clock accumulator at+12, simulation-clock accumulator at+16. The observer reads these20bytes atomically per sample, plus64bytes around the wait helper. Timing fields can be observed between instructions of an update; medians and accumulator deltas are more useful than a single instantaneous dt. The observer's relocation/signature structural self-check passed before live use.

Full evidence: `pacing-comparison.json`, each `headless-control/pacing-readout.json` and `headless-candidate/pacing-readout.json`, plus their configs and runtime logs. Raw guest RAM was not saved. Original app/game/user data was never changed by this diagnostic.

## Primary sources

- [Rick's current pacing implementation and measured AI slip](https://github.com/Rick-Barber/ScreamerRally-Recomp/blob/main/crates/sr-runtime/src/pacing.rs), local snapshot `/private/tmp/screamer-rally-port-review/crates/sr-runtime/src/pacing.rs`.
- [Rick's verified timing notes](https://github.com/Rick-Barber/ScreamerRally-Recomp/blob/main/docs/re/strt3fx.md#timing-verified), local snapshot `/private/tmp/screamer-rally-port-review/docs/re/strt3fx.md`. These describe STRT3FX; the software wait, two call paths and relocated fields above were independently verified in the exact START65H binary.
- [DOSBox0.83.1 HTTP API and atomic reads](https://github.com/dosbox-staging/dosbox-staging/blob/v0.83.1/website/docs/0.83/manual/http-api.md).

The candidate is a one-byte numeric change derived from the original guest binary. No Rick runtime code was copied into the native wrapper.
