# S1 native graphics integration

The source Runtime was copied from `NativeRenderer/Games/screamer/Runtime`.
Only these four Python files differ:

- `Tools/live_s1.py`: graphics control worker, exact HUD retrieval/publication,
  native eligibility, and fallback status.
- `Tools/s1_native_client.py`: bounded engine control/status/HUD transport.
- `Tools/native_graphics_policy.py`: pure readiness/lease/bootstrap policy.
- `Tools/test_native_graphics.py`: socket-free regressions.

The engine must include the separately staged `s1_native.cpp/h` module. A normal
bridge installs it with `renderer_ready: false` once the original executable SHA
and LE mappings validate. `--diagnostic-read-only` still sends no input or memory
writes: it does not start the graphics worker or request HUD extraction.

## Frontend heartbeat contract

Use the existing atomic input JSON, with the current bridge epoch and sequence:

```json
{
  "schema": "screamer-input/v1",
  "epoch": "current state.epoch",
  "seq": 42,
  "published_monotonic_ns": 123456789,
  "native_render_requested": true,
  "native_assets_ready": true,
  "native_assets_epoch": "current state.assets.epoch",
  "native_renderer_ready": false
}
```

These rendering flags are separate from keyboard focus. Asset readiness means
that the current asset epoch has loaded, even while the original framebuffer is
displayed. Renderer readiness means native geometry and the exact original HUD
are actually being presented. Original View makes `native_render_requested`
false. All three flags must be real booleans. The bridge rejects wrong epochs,
malformed/oversized state, timestamps older than 300 ms, and timestamps more than
50 ms in the future. Engine, Python, and frontend timestamps share the Mach
absolute epoch; the engine agent checked libc++ steady_clock against Mach time.

## Readiness order

1. Install guarded engine hooks with original drawing enabled.
2. Export/load the current scene and obtain a race pose less than 150 ms old.
3. A fresh frontend confirms current assets loaded and native view requested.
4. Send one 600 ms bootstrap lease for this asset epoch/HUD mode. This permits
   bypassing the original world raster before the first exact HUD is available.
5. The unchanged original HUD runs and its exact byte-write coverage becomes a
   transparent BGRA layer. Once frontend native rendering also reports ready,
   renew the engine lease every 150 ms.
6. After successful native readiness, a stale HUD, stale pose, lost frontend, or
   Original View request immediately sends readiness false. The bootstrap budget
   is consumed and cannot extend a later stale-HUD condition.

An interrupted or expired bootstrap cannot restart for the same asset/view. A
new asset epoch gets a separate bounded attempt. If the bridge/control worker
stops, the engine's independent lease also expires after 600 ms.

The HUD must be no older than 250 ms, match the current original HUD mode and
asset epoch, and have been captured after the current assets became ready. HUD
bytes are published independently from the complete original framebuffer:

```json
{
  "hud": {
    "complete": true,
    "rects": [],
    "layers": [{
      "path": "/absolute/session/frames/hud-1.bgra",
      "format": "bgra8",
      "premultiplied": true,
      "x": 0, "y": 0, "width": 640, "height": 480,
      "stride": 2560, "anchor": "center", "sequence": 7
    }],
    "coverage": "original-ram-byte-writes"
  }
}
```

The initial HUD stays centered at its original aspect ratio; world rendering can
remain 16:9. There are no opaque rectangle fallbacks. The old partial HUD profile
remains available as historical evidence but is not used for normal native
eligibility. Current native gameplay eligibility is restricted to original HUD
mode 2 to match the frozen engine guard. Other views use the original framebuffer.
Normal intro/attract modes also use original rendering; diagnostic read-only
attract geometry remains available for the existing offscreen validation tools.

## Validation and remaining limits

`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest test_native_graphics test_live_s1`
passes all 41 tests. They cover strict heartbeat provenance, bootstrap expiry,
scene changes, original-view/disconnect handling, stale HUD rejection after native
success, exact-alpha layer publication, and original actor/asset guards. No game
inputs, sockets, or emulator execution occur in these tests.

The packaged0.3.3/build8 test observed36.3seconds of continuous native player racing at3840×2160. It verified real acceleration, brief steering, player movement and a natural checkpoint extension. The observed foreground window averaged59.98FPS, including brief startup/fallback, with zero GPU/parsing/HUD errors. Original physics remained50Hz with its unmodified two-tick wait. The final HUD uses one atomic original RAM index/coverage/DAC snapshot. Its timer glyphs were independently checked for completeness; the preceding asynchronous color comparison is retained only as historical evidence. See `../../Validation/screamer-playable-4k.json`.

This bounded run did not reproduce a crash. It does not prove every old wall-impact case or long-session behavior; no specific collision flag was asserted. Native rendering supports F1(bonnet), F3(near chase) and F4(far chase). F2(cockpit), menus and intros use Original Game View.

The bad-span trigger in the original rasterizer remains undiagnosed. Selecting
Original View or losing the native lease deliberately restores that renderer, so
its previous crash can still recur there. Special
palette effects, cockpit native eligibility, and widescreen HUD anchoring
remain separate work. No S1 physics constants or timing routines were changed.

## Original sky

The candidate exports all six original MAPn.BCK PCX skies through the original MAPn.COL palette. Its 1536×256 padded texture preserves the source renderer's sequential row spill. Main-view sky fields are atomically validated; continuous camera interpolation controls the heading and pitch mapping. The original400-space center is260, distinct from480-space projection center312. All131,072 MAP1 index bytes match captured original RAM; original palette use and integer pitch offset were independently verified. An input-free diagnostic automatic-demo render passed at3840×2160 with original sky active and zero GPU/parse errors. This excludes HUD composition, active main-race backend bypass and the wall-crash path.

## Conventional framebuffer correction

The original allocator can return a conventional-memory framebuffer near0xDC50. The earlier1MiBminimum rejected every HUD capture in the observed main-race session, so selecting4K still displayed the original low-resolution framebuffer. `s1-conventional-hud.patch` accepts complete spans in normal conventional RAM below0xA0000 or extended RAM, while retaining flat-segment, paging, A20, range and ordinary-page checks. Original blitter disassembly confirms a direct destination pointer. Passive sessions verified the real buffer and unchanged fallback operation, but did not enter the main-race HUD. Build0.3.3/8 now passes actual native4Kracing and exactHUD capture; the bounded crash-validation scope is documented above.

## Original display and sparse actors

The original VGA output reaches the cache as BGRX32, so an Indexed8-only publication guard could never publish captured HUDs. The display patch removed the Indexed8-only dependency. The final cohort patch snapshots the original indexed HUD buffer, exact VGA DAC color LUT and write coverage together at HUD end, then publishes only this coherent snapshot with the verified400→480 row expansion. A later scanout RGB frame is never mixed with an earlier mask; this also fixes clipped timer digits. No HUD pixels are classified by color.

Actor-list flags and deletion holes also differ between attract and live racing: original disable/enable routines XOR both high bits(C0000000), while removed slots contain FFFFFFFF until the list's zero terminator. The shared decoder preserves sparse slot IDs, validates all recovered pointers/models/part extents and rejects an unproven active sign bit. Actual race RAM validated78actors and188parts. Seven synthetic regressions cover disabled pointers, holes, stable identity and invalid lists.
