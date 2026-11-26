# S2 original-frame and native-camera comparison

The paired source is `../S2-live/live-attract-v2/`: `guest-ram.bin`,
`snapshot-metadata.json`, `original-frame.bgra`, `original-frame.png`, and
`original-frame.json`. The cached original framebuffer is sequence797, 640×480
BGRA8; its capture precedes the coherent RAM capture by11.213458ms in the same
engine clock. No game input was used. Current camera equals main-view owner+0xa64.

The native comparison is `artifacts/attract-v2-comparison-640.png`, with world and
four car meshes from the same paired RAM (`artifacts/attract-v2`). It uses original
captured poses and the verified S2 projection. No screen capture is used as the
native world texture.

Direct code and RAM evidence is preserved in `s2-projection-homology.json`,
`s2-projection-snapshot-proof.json`, and the four `s2-*.asm` function listings.
Unique relocation-aware matches include the768-byte projector at7c430
(590nonmasked bytes),768-byte vertex builder atce048(644),512-byte SetView at54d2c
(329), and near-plane setter at849d4.

Actual S2 snapshot values:

| Item | Link address | Value |
|---|---:|---:|
| Grid centreY | 8386c | 260 |
| Grid width/height | 83880 /83854 | 640 /400 |
| CentreX immediate16.16 | 7c54a | 319×65536 |
| X/Y table offsets | ac0e8 /ac0ec | 0 /0 |
| X table pointer | ac0f4 | Identity mapping |
| Y table | ae0fc | Slope1.2000000476837158 |
| Mirror flags | abfe0 | 0 |

The projector retains focal length256 and depth shift128. These values derive
output width640,height480,fx256,fy307.200012207,cx319,cy312.000012398,near128. The
existing decimal307.2/312 values differ only by original float-table rounding.
Camera matrix conversion, original eye offset128, and the renderer's lateral
axis conversion agree with the source image.

At native640×480, recognizable landmarks align visually: the left house roof
starts near y117, the tall tree near x225/y160, the yellow tree near x430/y195,
and the road's vanishing point and all four cars agree. Remaining car edges differ
by roughly1–several pixels, consistent with the nearby cached-frame timing and
float geometry; this is a visual calibration, not a zero-error pixel proof.

Expected differences are explicit: the native exporter draws high-LOD scenery
outside the original visibility selection, and uses float transforms/filtering.
The original cloud background, car shadows, reflection shading and live wheel
poses are not reproduced by this offline scene proof. There is no evidence of an
X-reflection, reversed car-root transform or incorrect principal-point offset.

`hud-attract.json` covers the actual original logo and copyright source pixels.
It requires attract flag0x80 and must not be applied as a gameplay HUD profile.
An actual race frame is still needed to validate speed/lap/position/map/mirror
overlays before enabling the native gameplay composition for those modes.
