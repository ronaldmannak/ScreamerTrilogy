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
