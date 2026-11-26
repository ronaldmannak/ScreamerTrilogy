# Captured-world validation

The actual 16 MiB DOSBox STRT3FX snapshot in `probe/guest-ram.bin` produced both `artifacts/track-flat/scene.json` and `artifacts/track-textured/scene.json`. Source executable recognition, RAM SHA-256, and per-LE-object physical mappings are checked by the immutable bridge. Artifact JSON records the snapshot provenance and binary-buffer hashes.

The captured world matches the documented Rally China model/cell/object counts exactly:

| Item | Actual capture |
|---|---:|
| Models in table | 1,596 |
| World cells | 639 |
| Static objects | 2,260 |
| Track-section objects | 693 |
| Scenery objects | 1,567 |
| Unique highest-detail parts | 1,585 |
| Exported polygons | 43,700 |
| Exported triangles | 81,446 |
| Exported vertices | 168,846 |
| Original retained textures decoded | 324 |
| Opaque and keyed PNG variants (v2) | 384 |
| Texture records rejected | 0 |
| Material batches | 193 |
| Keyed material batches | 60 |

Every static object yielded geometry. The exporter walks both lists in every nonempty grid cell, the highest available detail level, and the union of all 16 polygon orders. It preserves polygon winding and UVs, triangulates polygon fans, and applies object and part placements. There is no generated fallback track. Exported camera position is `[-47714, 520, 41314]`; libraries include `map3`, `misc`, four car libraries and `env`.

Checks include bounded reads, terminated model/vertex/polygon tables, valid polygon corner offsets, finite transformed positions, triangle-index bounds, buffer lengths, batch index sums, and valid texture indices. Four unit tests cover documented world placement, malformed polygon rejection, original texture channel/palette conversion, and lossless PNG scanline encoding. Unit fixtures are never used as viewer assets.

This validates static scene reconstruction, not live game integration, interpolation, visual fidelity on every track, or renderer performance. The sky is not retained in guest RAM after upload; the first preview omits it. Dynamic cars, HUD, shadows and smoke are not in this static export. Those limitations must remain visible when describing the prototype.

The corrected `track-textured-v2` artifact separates opaque and keyed images. Every pixel of every referenced opaque PNG was checked to have alpha 255. The original flat/textured-v1 input capture was subsequently overwritten by the capture probe; its original hash remains in its provenance, but its exact RAM input cannot be recovered. The later validated input used for corrected textures and cars is preserved in `artifacts/source-capture-v2/{ram.bin,metadata.json}`. The probe now uses new output directories for future captures.

The optional `cars-textured-v1` export contains the six scene-table cars, 72 highest-detail parts, 2,297 triangles and 5,499 vertices in local car-root coordinates. All 98 batches belong to exactly one of the six stable scene IDs; buffer lengths, index sums and the complete batch partition were checked. It contains 18 alpha-blended mode-6 batches and six reflection mode-5 batches, which require renderer features beyond the initial static-track preview. Wheels and part poses are frozen at capture time.
