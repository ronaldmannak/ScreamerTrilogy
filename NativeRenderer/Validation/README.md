# Initial Metal milestone validation — 24 November 2026

## Final packaged track-and-car build

The final ARM64 app includes the real China track and six captured car meshes: 83,743 triangles, 174,345 vertices, 291 batches and 733 original-data texture variants. Root car poses are interpolated from the captured sequence; wheel poses/reflections/transparency retain the documented prototype limits. No live game executes in these tests.

| Measurement | Final packaged result |
|---|---:|
| Display test duration / drawable | 30 seconds / 2560×1440 |
| Unique presentation timestamps / submissions | 1,796 / 1,800 |
| Presented FPS | 59.900 |
| Presentation interval, median / p95 | 16.6666 / 16.6668 ms |
| GPU time, mean / p95 | 0.4470 / 0.5017 ms |
| CPU encoding time, p95 | 0.3772 ms |
| 4K offscreen frames / drawable | 180 / 3840×2160 |
| 4K offscreen GPU time, mean / p95 | 0.8206 / 0.8230 ms |

Raw reports: `presented-cars-1440p.json` and `offscreen-cars-4k.json`. Positive presentation timestamps are sorted and deduplicated before computing FPS. The offscreen run has no presentation callbacks; its FPS is zero. Neither run proves live emulator/renderer integration or complete-game performance.

31 Python tests passed (23 bridge, four extractor, four execution guards). The math-only source contract passed 535 checks, pinned to the final source/shader hashes. The packaged executable's `--check-math`, ARM64 build with warnings as errors, and deep/strict code-signature verification also passed.

The following sections retain the earlier track-only development measurements for comparison.

These measurements describe the initial static China track plus captured-camera replay. They are a renderer feasibility check, not a benchmark of playable Rally or of a simultaneous emulator/renderer workload.

## Native display test

`presented-track-1440p.json` records the unprofiled one-minute development run on the Apple M5 Max:

| Measurement | Result |
|---|---:|
| Drawable | 2560×1440 |
| Presented FPS, first to last reported presentation | 59.908 |
| Presentation interval, median | 16.6666 ms |
| Presentation interval, 95th percentile | 16.6667 ms |
| GPU frame time, mean | 0.3969 ms |
| GPU frame time, 95th percentile | 0.4410 ms |
| CPU encoding time, 95th percentile | 0.2220 ms |
| Submitted frames / presentation callbacks | 3,539 / 3,261 |

The FPS calculation uses actual positive `CAMetalDrawable.presentedTime` callbacks rather than the requested MTKView frame rate. Submission and presentation counts differ; frames submitted before the window becomes visible, skipped presentations and final callbacks are not presumed displayed. This is an average over reported presentations, not a guarantee of every frame deadline.

Native UI inspection confirmed the rendered track and a window title reporting 59.9 FPS. The known-good installed game was not replaced.

## 4K offscreen test

`offscreen-track-4k.json` records 180 textured frames into a 3840×2160 Metal target, with a fixed captured camera. GPU mean was 0.4514 ms and 95th percentile 0.7711 ms. CPU encoding 95th percentile was 0.1279 ms. No drawable was presented, so presented FPS is correctly zero. This establishes 4K rendering and GPU headroom for this scene; it does not establish 4K display cadence, complete-game frame cost or performance on another Mac.

Both initial tests draw 81,446 triangles in 193 material batches using 384 PNG texture variants derived from 324 original records. They exclude dynamic cars, sky, HUD, mirrors and game execution. Later car-preview measurements, if present, are separate reports.

## Instruments corroboration

A five-second **Metal System Trace** attached to the prototype successfully recorded native Metal submissions and GPU activity. The trace's prototype vertex channel total was 11.72 ms and fragment channel total 18.43 ms; its process CPU usage summary reported 1.1% average and no hang data. The display summary covers mixed desktop surfaces and is not used as the prototype's FPS result. Trace instrumentation and other desktop GPU clients affect the traced workload.

The local `.trace` bundle is retained under ignored captures. The authoritative display-rate evidence is the unprofiled presentation report above. No extrapolation from offscreen throughput or requested refresh rate is used.

## Capture and correctness evidence

- `bridge/bridge-verification.json`: actual executable and relocated-memory profile checks.
- `bridge/replay-sparse-verification.json`: 67 actual pose samples at 32.917 Hz, 331,542 payload bytes, no missed polling slots, six moving car roots. Reads within a pose span 5–7 ms; no claim of atomic end-of-tick snapshots.
- `bridge/metal-contract-verification.json`: numeric projection, handedness and quaternion interpolation checks against the actual source.
- `extractor/VALIDATION.md`: actual geometry/material counts and limitations.

The source executable profile is the original `STRT3FX.EXE` SHA-256 `9eac6e12ab309389bdda019cfa695bfbbc791fbda1a4634464a444fce35165d1`. The isolated guest copy uses the guarded three-tick pacing patch; original installed executables and save data remain untouched. Polling poses at 33 Hz is independent of proving unchanged simulation outcomes; deterministic game integration tests remain a future milestone.
