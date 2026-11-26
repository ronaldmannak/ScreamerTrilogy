# Original Rally track snapshot extractor

This prototype reads an immutable RAM capture from the recognized DOS `STRT3FX.EXE` and exports the actual loaded world. It does not launch or modify the game. It requires `bridge/guest_memory.py` for explicit, validated DOS address mapping.

Run after the capture and address mapping are available:

```sh
python3 extractor/extract_track.py --ram probe/race.ram --metadata probe/race.json --output artifacts/track-flat
```

Add `--textures` and choose a new output directory to export retained P8/RGB565/ARGB4444 textures as PNGs and group triangles by material. `textures` is an array of PNG paths; each batch's `texture` is an index into it. Opaque PNG variants have alpha 255 for every pixel, preserving RGB through image loaders. `alpha_test` batches use separate `-keyed.png` variants and discard alpha below 0.5. Blended materials use `-blended.png` variants retaining original texel alpha. Texture images and geometry come from the captured game, not replacements.

The output `scene.json` describes two binary files. `vertices.bin` contains little-endian float32 position XYZ, UV, and RGBA (nine floats, 36 bytes per vertex). `indices.bin` contains little-endian uint32 triangle indices. The positions are in the original game's absolute world coordinates, with Y pointing up. Metadata records original cells and objects, highest available model detail levels, the captured camera, counts, and hashes. No track geometry is generated procedurally or invented.

The flat output uses diagnostic colours, preserving real polygon RGB565 colours where the original uses flat shading. The textured output uses retained original texture pixels and model UVs. Neither provides a playable game, moving cars, sky, HUD, or interpolation. The full model is captured once; it is not a stream of game frames.

`extract_cars.py` is an optional separate export of the six actual car meshes. It uses the same vertex/index/texture layout, but vertices are in each car root's local space. Every batch has an `instance_id`, and `dynamic_instances` gives the matching captured root transform and batch indices. The renderer must apply these transforms; directly drawing all buffers as a world scene overlaps the cars at the origin. Captured per-part wheel placement is baked in and does not animate. Car alpha blending (mode 6) and reflection texgen (mode 5) require further renderer work and are identified explicitly in the batches.

Data structures and placement rules are implemented from the reverse engineering in [Rick-Barber/ScreamerRally-Recomp](https://github.com/Rick-Barber/ScreamerRally-Recomp), especially `docs/re/native/world.md`, `docs/re/native/extract.md`, and `crates/sr-runtime/src/native/{world,extract,transforms,textures}.rs`. The extractor is provided under GPL-3.0-only to preserve compatibility with that source work. See `LICENSE`. Original game assets remain owned by their respective rights holders and are not bundled with the extractor source.
