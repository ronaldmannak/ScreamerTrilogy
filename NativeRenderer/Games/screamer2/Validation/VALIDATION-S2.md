# Actual Screamer 2 export and true-4K proof

Input: immutable `../S2-live/attract-capture-v1/guest-ram.bin` and
`snapshot-metadata.json`, captured from the unmodified recognized S2 3dfx game in
automatic attract mode. The engine stopped cleanly. No input, pacing patch or
installed-file mutation was used for this capture.

RAM SHA-256:
`6cebb9d41ae8ab2ced66879cc01bc459001af8804ce6a97c26469d16e30a0df7`.
Metadata SHA-256:
`ec72aa8725e982cfb6d16677725e72ac68a72b72bb87a6c0a80e587ee445b572`.
Relocated main code base: `0x1e1000`; data object6 base `0x2b2000`, link `0x130000`.
Current camera equals main-view owner+`0xa64`, independently checked by the capture
agent. The loaded track library is `map1`.

Output: `artifacts/attract-v1`.

| Item | World | Cars |
|---|---:|---:|
| Original objects/root instances | 2,000 | 4 |
| Grid cells | 457 | — |
| Loaded model table entries | 654 | 654 |
| High-LOD part placements | 2,044 | 48 |
| Output vertices | 137,162 | 3,245 |
| Output triangles | 67,188 | 1,337 |
| Material batches | 207 | 65 |
| PNG variants | 393 | 375 |

All 344 retained original texture records decoded (169 indexed8, 151 RGB565,
24 ARGB4444); zero rejected records. World material modes are 0/1/2; car modes
also include 5/6. Every referenced texture and mode resolves. Alpha-tested and
opaque texture variants remain separate; blended textures retain straight-alpha
RGBA sidecars. Car roots are `scene:160`, `scene:162`, `scene:164`, `scene:166`, with
model IDs650..653. The loaded original libraries include `auto1`..`auto4`.

The validator checked finite vertices, index bounds, file hashes/sizes, PNG
dimensions/hashes, complete nonoverlapping triangle batches, material references,
stable dynamic IDs and matching model guards. A second independent export of the
same input produced **787 byte-identical scene/buffer/texture files**; see
`artifacts/repeat-verification.json`. Eight unit/negative tests pass, including
invalid polygon references, profile confusion and output-buffer tampering.

The existing native ARM64 Metal renderer rasterized 68,525 world+car triangles
into a **3840×2160 BGRA render target**, saved as a PNG whose IHDR is independently
checked to contain exactly3840×2160. This uses original 3D vertex/index buffers,
not a scaled DOS framebuffer. No Rally backend change was needed.

- `artifacts/attract-v1-overview-4k.png`: orbit overview, visually checked for
  coherent original asphalt, roadside scenery, trees and buildings.
- `artifacts/attract-v1-overview-4k-metrics.json`: 30 offscreen frames; Apple M5 Max;
  GPU mean0.423ms, p950.506ms.
- `artifacts/attract-v1-camera-4k.png`: original captured camera/root poses, repeated
  for display using `snapshot_view.py`; 30 frames, GPU mean0.212ms. The projection
  was subsequently verified against S2 code/RAM tables and a paired original
  framebuffer; see `CAMERA-COMPARISON.md`. This is a frozen captured pose, not
  recorded motion.

The renderer's `presented_fps=0` is expected for this offscreen test. These timings
prove GPU execution and target resolution; they do not prove live S2 gameplay or
onscreen presentation at60FPS. Original two-tick/~50Hz simulation was preserved.
The 4K target gives new geometric rasterization detail while retaining original
low-resolution textures. Native sky, wheel animation, precise reflection mapping,
shadows, live HUD/audio/input and complete track transitions are outside this
offline export milestone.
