# Screamer window-reflection checks

`ReflectionContracts.mm` includes the production frontend through `PREVIEW_SOURCE_FILE`. Build it like the fullscreen regression harness, with C++17, ARC, AppKit, Metal, MetalKit and QuartzCore. It checks original environment-frame boundaries, wrapped scroll interpolation, malformed material/pose rejection and compatibility with scenes without authored normals. It does not start a game or initialize an application UI.

`ReflectionGoldens.mm` is a small ARM64 Foundation/Metal executable. Compile it with ARC and those two frameworks, then run:

```
ReflectionGoldens /path/to/World.metal /path/to/original-UV-inputs.json /private/tmp/reflection-report.json
```

The original 87-case input is owned game data, retained locally at `NativeRenderer/Captures/Screamer-Glass-build10/original-UV-inputs.json` and excluded from Git. The probe appends a compute kernel that calls the production `originalS1ReflectionUV` function; it does not duplicate its formula. The expected values came from the original game's completed C3E84 UV buffer. Negative signed UVs must remain negative until sampling.

Source/export, GPU and isolated 4K race reports are under `NativeRenderer/Validation/screamer-reflection-*.json`. The race checks appearance and live reflection scroll; its presentation callbacks were throttled, so it establishes no new displayed-FPS result. Camera and part interpolation retain their existing floating-point approximation to original Q14 matrices. Other palette-effect materials are outside this fix.

## Original sign visibility

`SignCullProbe.mm` includes the same production source through `PREVIEW_SOURCE_FILE`, then renders a supplied owned fixture into a fresh output folder. Each fixture has `both`, `face-a`, `face-b` scenes and an 18-pose `replay.json`. It tests both cull states; the correct clockwise result must match the isolated face reference. A folded-quad fixture separately proves the per-polygon `double_sided` exception. Fixtures are retained under ignored `Captures/Screamer-Signs-build11`; decoded game geometry/textures stay out of Git. Neither probe starts a game or sends inputs.
