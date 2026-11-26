# Screamer native Metal adapter

The **0.3.7 / build 12** `Screamer Metal.app` opens a simple **Classic / Upgraded** choice. Classic runs the embedded Apple Silicon wrapper with the original renderer, 4:3 framing and original draw distance. Upgraded draws original race geometry with Metal at the window's display pixel resolution, including Retina scaling, with 16:9 framing and Full track draw distance. The wider view extends the horizontal field of view without stretching the geometry; Full track can reveal authored scenery gaps.

The original 50 Hz simulation remains unchanged, while Upgraded rendering targets 60 FPS. F1 (bonnet), F3 (near chase, default) and F4 (far chase) use native rendering in Upgraded. F2 (cockpit), menus and intros automatically use the original framebuffer. Original textures and HUD art keep their source resolution. The selector remembers the chosen experience; there are no separate resolution, aspect or distance controls.

The0.3.3/build8 package passed36.3seconds of continuous native racing with actual acceleration, steering and checkpoint progression. The observed foreground window averaged59.98FPS; GPU, parser and HUD errors were zero. No crash occurred during this bounded test. All six high-detail track archives are supported by the exporter, but only PalmTown received this player-race test.

`Runtime/Session.py` owns the private ARM64 game engine and bridge; Metal never advances physics. Original `STARTH.EXE` SHA256 is1246afc95463f96598d5fee764fc99c847b6d3e0bf8ca2268bd362c664bb28a3. Its two-tick wait remains instruction/hash guarded and unmodified. Runtime data/saves are separate from the installed classic wrapper.

The model/grid/material formats differ from Rally. Native actors use original root and individual part transforms. Exact original RAM-write coverage produces transparent HUD layers and colors from the same original index/DAC snapshot. Original PCX skies use the installed MAP palette and verified heading/pitch mapping. A0 car-window reflections now retain original geometry, authored normals, complete environment tiles, and live scroll/environment phases. Palette-effect shadows/smoke, damage animation, cockpit composition and widescreen HUD anchoring remain incomplete.

`NATIVE-GRAPHICS.md` documents the guarded rasterizer lease, conventional framebuffer, sparse actor decoder and limits. `../../Validation/screamer-playable-4k.json` retains the actual race evidence. Original owned game files, extracted meshes, images and built apps stay local and excluded from Git.

## Reflective windows — 0.3.5 / build 10

The earlier exporter omitted A0 window polygons. These now use the original opaque, depth-writing reflection material, authored normals, signed per-vertex UV generation, repeating sampling, and live original actor offsets/environment-frame selection. Existing camera/part interpolation is retained; original Q14 quantization differs slightly, so pixel-identical images are not claimed.

The production GPU helper matches all 87 saved original UV pairs exactly. An isolated 4K player-race capture renders 136 reflection triangles across ten batches, with zero GPU/parse errors and changing live scroll. The route stays in environment phase 0; other phase boundaries were checked separately. This run validates appearance and function, not foreground FPS. Source/export checks preserve all 745 existing non-A0 batches and pass all six static tracks. See [contract](../../Validation/screamer-reflection-contract.json), [GPU proof](../../Validation/screamer-reflection-GPU.json) and [race proof](../../Validation/screamer-reflection-race.json).

## Stable sign visibility — 0.3.6 / build 11

The original sign models contain coincident front/back polygons with opposite winding and different artwork. The original renderer rejects backfaces; the Metal live state now enables its clockwise backface rule so the gray rear cannot compete with the sign front. Original zero/folded-normal exceptions remain two-sided in separate batches, preserving their earlier rendering without disabling visibility rules for shared materials. No depth bias, geometry movement, physics change, or texture replacement is involved.

All 108 moving-camera sign views match their isolated original-face references exactly; a separate actual folded original quad retains its previous pixels in all 18 views. All six static and two dynamic exports preserve their original vertex bytes, normals and triangle sets. The runtime suite passes 50 tests. See [sign pixel checks](../../Validation/screamer-sign-pixels.json) and [export checks](../../Validation/screamer-sign-export.json).
