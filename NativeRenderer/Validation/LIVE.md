# Playable Metal milestone — 25 November 2026

The original 3dfx Rally game runs in an ARM64 DOSBox process. Its completed-frame camera/car snapshots drive a separate native Metal renderer. Additional rendered frames never execute another physics step. Input uses ordinary guest keyboard transitions; menus, loading and pause screens remain original framebuffer pixels.

## Actual live China race

`live-presented-race.json` records simultaneous guest execution and native track/six-car/HUD rendering on the development Apple M5 Max:

| Measurement | Result |
|---|---:|
| Positive presentation timestamps | 573 |
| Presented FPS | 59.583 |
| Foreground presented FPS | 59.583 |
| Presentation interval, p95 | 16.6668 ms |
| GPU frame time, p95 | 0.3047 ms |
| Draw callback rate | 59.843 Hz |
| Drawable | 1318×1440 |
| Triangles / batches / textures | 83,753 / 290 / 733 |
| Live parse errors | 0 |

The 20-second process lifetime includes time without reported visible presentations. FPS uses unique positive drawable presentation timestamps, not submissions, timer requests or offscreen throughput. The positive timestamps cover about 9.6 seconds. The drawable was narrower than the window's default size due to window layout; this is not a displayed-4K benchmark.

`live-offscreen-4k.json` separately records actual live geometry rendered into a **3840×2160** Metal texture. GPU mean/p95 were 0.3613/0.7652 ms. It is explicitly unpaced, reports zero displayed FPS and does not establish 4K display cadence. The original textures and HUD retain their source resolution.

## Input and physics

The user-approved disposable API test navigated name→Arcade→China→Motrail→Automatic and exercised throttle, steering, pause and resume. Normal guest Up input for 2.5 seconds changed speed from 0 to 48.862 original game units, RPM to 5,226 and gear from 1 to 2. Right steering changed the car heading and velocity. Every action released its keys, and all owned test processes exited cleanly. Installed apps and saves were not modified.

`real-race-clock-analysis.json` infers **32.997 original steps per wall-clock second** during a 4.97-second race observation. The 161 observed transitions represented 164 steps: 159 intervals of 30 ms, one of 60 ms and one of 90 ms. Three intermediate states were missed by polling. Raw dt stayed 0.030 s and smoothed simulation dt 0.033 s. This is a short inference from original game clock increments and the verified wait helper, not a deterministic all-tracks physics equivalence proof. Pause wall time is excluded from active-rate measurements.

The LCD pixel reports verify that the original dim segments which resemble “888” are unlit artwork. Source pixels match 000/gear 1 at rest and 041/gear 2 after throttle. No speculative Voodoo byte-write patch was applied.

## Source and package checks

29 live bridge tests, four execution guards and four extractor tests passed. Including the retained baseline bridge tests, 60 Python tests passed in the integrated project. The current Objective-C++/Metal source passed 535 numeric projection/car-root contract checks, an ARM64 warnings-as-errors build, the executable's `--check-math`, and deep/strict package signing verification. The private runtime was checked with a restricted PATH, including its own Python child process and dynamically loaded SDL3. Engine patch reproduction matched the compiled source exactly. The final self-contained app then completed a 20-second normal macOS launch, original-framebuffer startup and clean engine exit with no session error; see `packaged-live-app.json`.

## Scope

This is an experimental playable renderer validated in a short China Arcade race. Native output currently requires the six-car extraction profile; unsupported modes use the original framebuffer. Sky, smoke, shadows and wheel animation are incomplete; reflection UVs are approximate and transparency is batch sorted. HUD/mirrors are original rectangular pixel cutouts that include some original 3D background. Other tracks, race transitions and sustained sessions need broader testing. The known-good DOS wrappers remain the recovery path.

Game captures, PNGs, extracted assets and built apps remain ignored local artifacts. The JSON reports contain metrics and provenance only.

## Final reload recovery regression

The final packaged Rally bridge additionally passed 11 scene-reload regressions covering changed actor pointers/models, camera ownership and capture retries across the extraction throttle. The integrated Rally test total is now 71 Python tests, including the original bridge/extractor/execution tests. A fresh 51.36-second disposable test using the final bundled Python/engine/bridge again reached China, accelerated, steered, paused and resumed; both owned children exited zero. Raw and smoothed dt remained 0.030/0.033. See `final-packaged-rally-input-test.json`. The native Rally binary remains the displayed-FPS-validated live milestone; the bridge fix does not change its renderer or guest timing.
