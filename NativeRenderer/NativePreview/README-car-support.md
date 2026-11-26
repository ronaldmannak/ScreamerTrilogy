# Optional captured-car support

Build with `--cars-dir artifacts/cars-textured-v2` to bundle `Resources/Cars`. The runtime also accepts `--cars /path/to/scene.json`; `--no-cars` keeps a bundled preview in track-only mode. Without any car input the existing track preview remains available.

The actual six captured car meshes contribute 2,297 triangles in car-root-local space. Every draw batch references a stable `scene:<entry>` ID. The renderer applies the matching captured model transform, or interpolates recorded root poses using linear position interpolation and proper quaternion slerp. Both samples must have the same ID and model number as the artifact. Missing or replaced objects are omitted; jumps over 4,000 world units snap rather than sweep. Loop endpoints are not interpolated across the recording seam.

Static world batches use an identity model transform. Opaque and keyed batches retain depth writes and the original pipeline; source-alpha car batches draw afterward with depth writes disabled, sorted by batch-centre distance. Original RGBA bytes for blended textures are uploaded directly from `rgba_file` sidecars, avoiding image-loader premultiplication ambiguity. Alpha-key images use separate PNG variants; opaque output remains opaque.

The preview does not execute physics, accept driving controls, or synchronize live game state. It replays captured poses. Wheel and part poses remain frozen at capture time; reflection materials use approximate ordinary UVs, and transparency is sorted by batch rather than by polygon. These limits are included in the runtime metrics. The camera projection and existing display/GPU metrics remain in place.

Validation: ARM64 build with warnings as errors; `--check-math` retains the original projection reference checks and adds translated/quaternion-slerped car-root checks. Actual captured track plus six cars rendered offscreen at 640×480 and 1280×720; these checks measure GPU work, not displayed frame rate. See `../Validation/cars-640-metrics.json` and `../Validation/cars-1280-metrics.json` for the measured runs.
