# Presentation regression checks

`python3 NativeRenderer/NativePreview/Tests/check_geometry.py` compiles the actual renderer source and verifies that 16:9 adds horizontal field of view while retaining the central 4:3 framing and vertical scale. It does not create a window or run a game.

On macOS14+, the native fullscreen test uses the actual PreviewApp, PreviewView, PreviewRenderer and MetalDisplayDriver classes with owned local scene/shader inputs. A sentinel live path creates the real game-overlay UI without starting live services; a tiny placeholder framebuffer hides the status label while leaving its constraints active. It enters and exits native fullscreen, changes between 4K and Window Resolution, and checks view/backing/layer/supplied texture agreement and presentation aspect. No engine, game simulation, guest input or save files are used. Fullscreen assertions compare the actual view and content width with the owning screen, so a small centered game window cannot pass on aspect ratio alone. Both render modes use the production live-game presentation branch and retain16:9. A successful test requires observed native fullscreen events and actual presentations, not just a requested transition.

Run from this worktree with an explicit fresh isolated output directory:

```sh
python3 NativeRenderer/NativePreview/Tests/run_fullscreen_regression.py \
  --source "$PWD/NativeRenderer/NativePreview/Sources/NativePreview.mm" \
  --scene /path/to/owned/Scene/scene.json \
  --shader "$PWD/NativeRenderer/NativePreview/Sources/World.metal" \
  --cars /path/to/owned/Cars/scene.json \
  --output /private/tmp/screamer-fullscreen-new-check
```

The probe runs for14seconds after startup and the runner enforces a30second maximum. It briefly activates its own test window. `--compile-only` builds without showing a window. The fresh output directory retains compile arguments, geometry events, metrics and assertions. This validates presentation geometry; it is not a player-race or gameplay/FPS benchmark. See `../../Validation/fullscreen-fill-regression.json` for the verified build0.3.2/7 result.

## Live Day / Night / Fog

Run the source-only conditions checks on an Apple Silicon Mac with a Metal device:

```sh
python3 NativeRenderer/NativePreview/Tests/check_conditions.py \
  --output /private/tmp/screamer-conditions-new-check
```

The runner compiles the actual production frontend and shader. Authored synthetic geometry and one-pixel colors check unchanged original artwork and night skies, black night distance haze, the exact original 64-byte grey fog table and independent Glide lookup reference, camera-depth rather than radial fog, the original `BDF7` flat background expansion, alpha-key discard, preserved source alpha, and the original alpha/ONE–SRC_COLOR/2×source×destination glow equations. Modulated light cones retain the original fog exemption. Framebuffer and HUD fragments remain byte-identical across presets. CPU checks cover Day-bank selection for Fog, missing/incomplete tables, unchanged source clock/identity and finite uniforms. Menu probes cover ⌘1/2/3, unsupported Night/Fog availability and unchanged game-input/session state. Actual frontend CLI runs reject unknown conditions and preserve untinted near-field artwork.

`OriginalConditionsIntegration.mm` additionally exercises the production asynchronous asset loader with a private `screamer-live/v1` fixture containing baseline assets and `assets.condition_variants`. It renders Day → Night (when available) → Day → Fog → Day at 1280×720, checks every captured instance/model identity, verifies Fog's disabled sky and preserved world-distance policy, and requires restored Day images to match byte-for-byte. Unsupported Fog must render the identical original image. It injects immutable captured poses directly into the frontend; it never starts a game, advances physics or publishes input. Fixtures and rendered original assets belong outside version control. An asset-load snapshot can precede the first camera/car placement: use a later recorded pose from the same verified asset epoch and document that provenance when preparing a visual fixture.

No original game files, game process, save data or guest input are used. Generated images are synthetic probes, not gameplay captures. This checks rendering and switching contracts, not player-race visuals or frame-rate guarantees.
