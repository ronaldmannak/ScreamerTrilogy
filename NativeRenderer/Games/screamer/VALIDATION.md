# Screamer 1 native 4K prototype

This prototype decodes the owned original 1995 game assets, runs the original
unmodified `STARTH.EXE` in the native ARM64 DOSBox runtime, and feeds original
camera and actor-part poses to the shared Metal renderer. All work is private
temporary data. Installed apps, original game files and the source repository
were not modified.

## Implemented and checked

- All six original high-detail tracks export into the existing
  `screamer-scene/v1` Metal format, including original UNR models, MMP grid
  placements, MLB texture crops and RGB666 COL palettes. No replacement track
  or texture is generated.
- A real 3840x2160 offscreen Metal render of track1 is in
  `Validation/track1-4k.png`. It contains 1,164 original objects, 31,107
  triangles and 163 original textures. This is geometry rasterization at 4K,
  not enlargement of the DOS framebuffer.
- `Validation/live-v2-4k.png` and its JSON report prove the live bridge and
  shared renderer work together at a real 3840x2160 target: original camera,
  158 supported independently transformed actor parts, 34,180 total triangles,
  313 textures, zero GPU errors and zero live-parse errors. This run is marked
  **scene-only diagnostic**, because original overlays were not claimed
  complete. Offscreen runs present zero screen frames and do not measure
  displayed FPS.
- The camera calibration compares 59 actual original camera-space vertices
  with the game's packed screen positions. With eye offset128 and focal256,
  maximum error is0.979px horizontally and1.822px vertically, consistent with
  the old integer projection. See `Validation/camera-projection-proof.json`.
  This live evidence **rejects the earlier static256/512 hypothesis** in the
  research folder. The corrected image is
  `Validation/captured-camera-corrected-640x400.png`.
- The original wait remains two 100Hz ticks, with the original20ms dt floor.
  Over7.997429s,383 observed clock transitions reconstruct400 timer updates:
  **50.0161Hz**. Every observed raw dt is0.020s; skipped observed states are
  identified by40/60ms clock differences. Thus45–48 observed poses/s is not
  evidence of a slower game simulation. This bounded automatic-sequence
  measurement is `Validation/original-clock-8s.json`.
- Real root and per-part poses are read atomically at the original wait.
  Car wheels/steering parts can animate independently through stable
  `list:<entry>:part:<slot>` IDs and original model guards. The sampled
  automatic scene contains nine cars. The final frontend reports the 158
  independently animated parts as `dynamic_part_instances`, with `cars:null`
  to avoid presenting the part count as a car count.
- Thirteen synthetic tests cover actor/model replacement, same-map roster
  growth, stale mesh-job rejection, retry after export failure, camera
  constants, read bounds, the actual HUD descriptor contract and expected
  completed-frame waits being diagnostics rather than errors.
- A final bounded lifecycle test accepted the frontend's precreated
  `session.log`, `input.json` and `performance.json`, loaded the original game
  and bridge, and shut down owned children cleanly. Every agent-run S1 test
  disabled input; no scripted menu keys or guest-memory writes were used.

## Source tools and reproduction

All command paths below are examples; the scripts accept explicit external
inputs. Use fresh artifact/session directories so existing proof is retained.

```sh
python3 Tools/export_scene.py --game-root /path/to/owned/Screamer \
  --track 1 --output /path/to/new/track1

python3 Tools/session_s1.py --engine /path/to/custom/dosbox \
  --game-root /path/to/owned/Screamer --scenes-root /path/to/six/scenes \
  --data-dir /path/to/private/GameData --session-dir /path/to/new/session \
  --parent-pid GUI_PID
```

For a bounded read-only diagnostic, add
`--diagnostic-read-only --audio dummy --max-seconds 60`. The original game
starts normally; the tool does not skip the intro or select a menu. The custom
engine needs the existing atomic-read, normal-keyboard and cached-BGRA-frame
endpoints, enabled only through the private loopback configuration.

The bridge may start before layout is ready; original framebuffer fallback is
available throughout startup and menus. Original frame capture is already
640x480, after the game's400-to480 scanline expansion. Do not stretch it again.
The live camera uses the equivalent480-row projection: fx256,fy307.2,cx319,
and the original dynamic vertical centre multiplied by1.2.

The original wait caller distinguishes intro/attract (`27747`), the main game
scene (`1FF4F`) and generic menu/input waits (`2AA96`). AI autoplay within the
main game loop is not separately distinguished from a player race. The bridge
never labels a known intro as player racing. No player-race control validation
was performed by this agent.

## Bundled frontend contract

Copy source-only files as follows:

```text
Session.py             -> Contents/Resources/Live/Session.py
Tools/                 -> Contents/Resources/Live/Tools/
hud-profile.json       -> Contents/Resources/Live/hud-profile.json
Scenes/track1..track6   -> Contents/Resources/S1Scenes/track1..track6
owned original game    -> Contents/Resources/game/
custom DOSBox runtime  -> Contents/MacOS/dosbox + private dependency closure
```

The six scene directories and original game files are copyrighted private
assets, not source. Do not include them in a public source commit. Initial
frontend Scene/Cars may use track1 and `Scenes/dynamic-track1`; once the game
loads, the bridge supplies matching live world and actor-part scene paths.
The shared frontend must allow up to256 part instances.

`Session.py` accepts exactly the frontend arguments
`--resources`, `--session-dir`, `--data-dir`, `--parent-pid`. It starts the
private engine and bridge through the bundled interpreter. Published files
are `state.json`, `layout.json`, `engine-status.json`, `runtime.log` and
`bridge.log`; generated actor meshes go into the session's private asset cache.
The root packager supplies its already verified private Python runtime and
sets PYTHONHOME to `Contents/Resources/Python`.

The persistent game directory is protected by an owner/profile marker and
flock; unrelated folders and paths overlapping source/app bundles are refused.
First copying is staged and renamed. Later launches preserve private saves
and configuration. New sessions refuse old engine artifacts while accepting
only the known prelaunch GUI files. Parent exit/SIGTERM stops the input bridge
first, then the owned engine. No unrelated processes are signalled.

Scene/model/roster changes invalidate old poses and meshes, even when the same
track reuses all original addresses. Generation guards reject old extraction
jobs, and failed jobs can retry with a fresh guarded snapshot. No stale-world
fallback geometry is invented.

## Partial HUD and remaining limits

`hud-profile.json` is explicitly partial. Source-proven conservative regions
cover the digital dashboard's speed, gear and RPM art, and lap/position/time
labels and numbers. Its descriptor uses only the frontend's `left`/`right`
anchors and coordinates within the actual640x480 cached frame. The bridge
enables this profile only in the main-race caller and original digital HUD
mode2. The native frontend must require an explicit partial-HUD opt-in and
retain its original-game-view recovery.

Cockpit and no-dashboard layouts fall back to the original view with a friendly
notice. Source view-table entries0 and2 select the digital dashboard; entry1
selects the cockpit, and entries3/4 omit it. The currently selected/default
player view and the user-facing switching control have not been verified in
a real player race. Intro logos, countdown/pause/results and transient messages
are not covered. Conservative rectangles also retain original-resolution
background pixels around the instruments and fonts.

These dashboard selections come from the original 20-byte view table at link
`0x101DA8`, loaded into the HUD selector at `0x19D07..0x19D0E`.
The original HUD dispatch at `0x236DE..0x236ED` reads that selector:
value1 draws the cockpit and value2 draws the digital instruments. Local
disassembly evidence is in `Validation/dashboard-selection.asm` and
`Validation/pkc-caller-proof.asm`; exact numeric-field and art bounds are
recorded in `hud-profile.json` and `Validation/pkc-validated-bounds.json`.

Material types10h,40h and80h are implemented. Static tracks1,2,3,6 have no
omitted material triangles; track4 omits124 E0h triangles, track5 omits156 C0h
triangles. The first dynamic scene omits120 A0h reflection triangles and18
E0h shadow triangles. Palette blending and view-dependent reflection remain
unfinished. Texture damage/animation selection is frozen at asset capture;
actor-part transforms are live. Sky composition is also unfinished.

The successful offscreen and clock checks do not establish player input,
complete graphics parity, displayed60FPS or all track-transition behavior.
Those remain application/frontend validation tasks; the original simulation
and original-view recovery are preserved throughout.

GPL-3.0-only applies to the decoder/render-convention implementation and copied
bridge support; see `Tools/LICENSE`. DAT format and transformation conventions
are attributed to Rick-Barber/ScreamerRally-Recomp. Original game assets retain
their original rights holders.

### Reflection restoration (0.3.5 / build 10)

The historical omission of A0 triangles above is resolved. Original window geometry and normals are exported, and the Metal renderer implements the original view-dependent UV rule with signed coordinates retained until repeating texture access. Both captured scenes restore their 136/120 A0 triangles; unrelated C0/E0 effects remain outside this change. See [export proof](../../Validation/screamer-reflection-export.json), [GPU reference checks](../../Validation/screamer-reflection-GPU.json), and [isolated race checks](../../Validation/screamer-reflection-race.json).
