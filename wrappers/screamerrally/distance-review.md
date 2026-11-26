# Distance review and persistence patch

> Rally version 1.2.1 adds an independent timing byte to every launch mode. Current Rally hashes are in [the pacing mode report](tests/pacing-mode-verification.json); older hashes below describe build 5. Distance behavior and its arithmetic limits are unchanged.


Static review of original DOS guest code. No game executable, installed app, user data, or system policy was modified or launched during this review. The only files written are this report and `src/distance-persistence.json`.

## Recommendation

For Rally, offer Original, Extended (104,000-unit object admission radius), and Farther / experimental (130,000 units). For Screamer 2, offer Original and Extended (104,000 units). For Screamer 1, offer Original and managed animated-object visibility +20%, +30% and +40% (40,000 to 48,000, 52,000 and 56,000 units respectively). None is an unlimited world/terrain draw-distance switch. Do not describe 104,000 as a guaranteed doubling of the visible horizon: the race-specific far plane, coarse frustum, hand-authored cell lists, and renderer limits remain in place. Engine units have not been validated as metres.

130,000 is a plausible static prototype value within the signed distance consumer's range, not an all-track safety certification. Keep it explicitly experimental until runtime checks cover all tracks, mirrors and camera modes. A constant-only 3x preset is unsuitable because it feeds a negative value to the existing signed x87 distance consumer.

## Critical finding: the original five-immediate E6 patch is overwritten

The five collectors have compiled `CMP EAX,0x14257880` values, but `SetFarDistance` recalculates and writes all five immediates during scene/race setup. The original calculation is `(distance + 8192)^2 >> 3`, where its argument is negative distance. Thus 52,000 is the compiled/default admission radius, not a fixed original radius for every race. Rick's reverse-engineering notes give a 50,000-unit far distance for Rally China at highest detail, corresponding to a 58,192-unit admission radius after this routine runs.

Rally's self-modifying writers are raw 0x8585d, 0x85863, 0x85869, 0x8586f, 0x85875. Their LE code-object offsets 0x59fd0, 0x5a034, 0x5a0ba, 0x5a11e, 0x61893 relocate to VAs 0x69fd0, 0x6a034, 0x6a0ba, 0x6a11e, 0x71893: exactly the immediate fields patched by E6. All five writer address operands have LE internal 32-bit fixups to code object 1. Screamer 2 has the homologous writers beginning at raw 0x9355d.

The pinned upstream launcher applies E6 to the on-disk runtime copy; inspected hooks contain draw-distance telemetry but no reapplication of the admission constants. Consequently a file-byte check alone does not prove the earlier option persists while racing.

## In-place persistence patch

Replace only the 15-byte arithmetic region, retaining the five original relocated writers.

| Guest | SHA-256 | VA | Raw offset |
|---|---|---|---|
| Rally START65H.EXE | `0785e38567c475f25663e4022ec125e447a799004e34efa59758b50cfd84901d` | `0x7284e` | `0x8584e` |
| Screamer 2 START65H.EXE | `05f576866f26602be303343c5e9104132616f464b71ed6ae958e99a668e5c7c8` | `0x7ed4e` | `0x9354e` |

Expected bytes in both: `2d 00 20 00 00 f7 e8 8b c8 8b ea 0f ac e9 03`.

104,000-unit replacement: `b9 00 e2 95 50 90 90 90 90 90 90 90 90 90 90`.

130,000-unit Rally replacement: `b9 20 31 ea 7d 90 90 90 90 90 90 90 90 90 90`.

This is `MOV ECX,threshold` plus ten NOPs. Both complete functions use PUSHAD/POPAD; EAX is additionally saved before the replaced arithmetic and restored after the five writers. Subsequent far-plane globals use that restored EAX. EDX and EBP values produced by the old multiplication are not read later before POPAD. No flag-dependent branch consumes the replaced arithmetic's flags. The other far-plane and clipping updates remain byte-identical. The region has no source relocation overlap: all 15,403 Rally and 16,138 Screamer 2 fixup sources were parsed. No branch/call target into this arithmetic region was identified in the inspected source; runtime validation remains required.

Keep the five original CMP patches too, so the selected threshold is present both before and after SetFarDistance. For Rally Farther, change each of those five CMP replacements to `3d 20 31 ea 7d`. The JSON contains one additional patch per game plus offset-keyed overrides to merge into Rally's existing patches; the overrides must not be appended as duplicate patches.

## Arithmetic and limits

All ten inspected S2/Rally collector sites square each signed 32-bit coordinate difference using the one-operand IMUL form, producing EDX:EAX, and accumulate using ADD/ADC into a 64-bit sum. They use SHRD by 3, then compare its low 32-bit result with an unsigned JAE rejection branch (`73`). Therefore the current doubling does not overflow a 32-bit intermediate multiplication.

| Admission radius | Metric threshold `r*r/8` | CMP bytes |
|---|---|---|
| 52,000 | 338,000,000 / `0x14257880` | `3d 80 78 25 14` |
| 104,000 | 1,352,000,000 / `0x5095e200` | `3d 00 e2 95 50` |
| 130,000 | 2,112,500,000 / `0x7dea3120` | `3d 20 31 ea 7d` |
| 156,000 (3x) | 3,042,000,000 / `0xb5513c80` | not suitable unchanged |

The unsigned admission field alone can represent radii up to approximately 185,363.8 units, but that is not the renderer's usable limit. The accepted value is later loaded with signed `FILD m32int` and square-rooted: Rally raw 0x84a6b / VA 0x71a6b (`db 05 40 a1 05 00 d9 fa`), S2 raw 0x9276b / VA 0x7df6b (`db 05 60 66 06 00 d9 fa`). Values >= 0x80000000 become negative, making FSQRT invalid. The unchanged downstream arithmetic therefore requires admitted distances below roughly 131,072 units (about 2.5206 times the compiled 52k radius). 130k stays below this boundary; it has about 1,072 units of radius headroom.

SHRD also discards metric bits above bit31; far-away candidates above approximately 185,364 units can wrap. The proposed values do not add a high-word rejection or otherwise repair the original algorithm. Coordinate subtraction, fixed-point vertex transforms, and wider frustum products are further constraints; static admission capacity is not a proof of arbitrary-distance rendering.

Upstream documents 1,600 entries in the 0x3200-byte admission list and at most 192 source records in the official track hierarchy, giving 960 under its deliberately pessimistic five-collector count. That supports the original track subset's proposed admission expansion, but is upstream static evidence rather than a new runtime count and is not a guarantee for modified tracks or every later renderer list. Rick separately expands three object lists by eight times, changes Q14 frustum rotation to Q12 with divided corners, scales the actual far plane, and merges visibility lists for its broader 3x feature. That implementation cannot be equated with the present in-place admission patch.

## Screamer 1 scope and reset check

The retained GOG STARTH.EXE is byte-identical to the upstream profile: size 1,034,923, SHA-256 `1246afc95463f96598d5fee764fc99c847b6d3e0bf8ca2268bd362c664bb28a3`.

The manifest retains E6's +20% option and adds +30% and +40% alternatives at the same three original sites. The shared float is at VA0x100d29 / raw0xf7529; both coarse per-axis gates are at VA0x209bb / raw0x2b1bb and VA0x209d2 / raw0x2b1d2. Every variant verifies the original expected bytes before replacing them.

| Distance level | Managed-object float | Float bytes | Per-axis gate | Gate bytes |
|---|---|---|---|---|
| 0 / Original | 40,000 | `00 40 1c 47` | 52,000 | `20 cb 00 00` |
| 1 / +20% | 48,000 | `00 80 3b 47` | 62,400 | `c0 f3 00 00` |
| 2 / +30% | 52,000 | `00 20 4b 47` | 67,600 | `10 08 01 00` |
| 3 / +40% | 56,000 | `00 c0 5a 47` | 72,800 | `60 1c 01 00` |

These changes affect managed ANIMATIONS create/destroy/fade/LOD visibility, not the road/terrain draw range. Upstream counted at most five managed animations on original maps with a 32-slot renderer. Higher percentages do not remove the original scenery, terrain or clipping limits. A short +40% widescreen check reached a race and rendered while driving; this is not an all-track or long-session stability result.

All six LE-relocated references to the shared float (data object3, offset0xd29) are reads: FCOMP, FLD or FDIV, at raw operand offsets0x2c423,0x2c43e,0x2c4d4,0x2c4dd,0x2c4e3,0x2c4ec. No store reference to the float, or LE-targeted mutator to either coarse CMP immediate, was found. There is no analogous direct SetFarDistance reset identified for S1; this is static inspection rather than a proof excluding every indirect write.

## Verification scope

Expected bytes, exact file hashes, source fixup overlap, equal replacement lengths, and non-overlapping patch ranges were checked against retained original GOG executables. The hashes below were independently generated in Python memory. Distinct settings produce distinct hashes, with original settings reproducing each original hash. The staged apps also passed all 18 preparation modes: eight Screamer, four Screamer 2 and six Rally combinations; [mode verification](mode-verification.json) records repeat/toggle, preference migration and save-preservation checks. See [verification notes](verification-notes.md) for the separate, limited visual checks and an unresolved long unattended run.

Screamer levels 1/2/3 mean +20%/+30%/+40% managed-object visibility. Screamer 2 level 1 means Extended; Rally levels 1/2 mean Extended/Farther. Level 0 is original in every game.

| Game | Widescreen | Distance level | SHA-256 |
|---|---|---|---|
| screamer | False | 0 | `1246afc95463f96598d5fee764fc99c847b6d3e0bf8ca2268bd362c664bb28a3` |
| screamer | False | 1 | `4d77cb6e77a0989bac4edb892c897285b16969ecb4f31f529ecc59408f1d635b` |
| screamer | False | 2 | `f5bd88e4e3648108de9c84ed938f82e2c81b70e4d9c28f29313a24c716bde658` |
| screamer | False | 3 | `a972ac4f7a6d4fe2b8c1a44eda8d6e301ee11df6d3a66511dfff303d84155b7d` |
| screamer | True | 0 | `04d2adc73e5d1ccbb2aadc9978c7b5dcded33114e888181e3206d2e0a25a5541` |
| screamer | True | 1 | `c68f02bd183c1254833099d00a5a9e5ae8ee4f37cc47a3f4cd9c531b2332437c` |
| screamer | True | 2 | `4ba3955593c5d68fb1221d7d43b9a6f391500cb0afb51117eca7187c36649c9d` |
| screamer | True | 3 | `99576a42aa103b47f286747a187e579964e475d784f1083209bdd0475bc793ae` |
| rally | False | 0 | `0785e38567c475f25663e4022ec125e447a799004e34efa59758b50cfd84901d` |
| rally | False | 1 | `012db93bc17f35682357ee50591e5e70c867a21c901b86e7d4aa337412fb7636` |
| rally | False | 2 | `7cbc4aba5d23324be3b1623588dfa49feb89692278e143a82a8ca26f527e1e1b` |
| rally | True | 0 | `a355c5e1741800448fc558f7289f40d8aae15d72569979f7a258c1261d7402ad` |
| rally | True | 1 | `0187f6f5c7ff6d8ed69839eaebe3704fc56bc6c253f89a5fb6c9c6d482cd9c25` |
| rally | True | 2 | `34861f1b2d0189e4f2479cbc268da3894a4d0bfa4cceda7b61e5a79a6e64562d` |
| screamer2 | False | 0 | `05f576866f26602be303343c5e9104132616f464b71ed6ae958e99a668e5c7c8` |
| screamer2 | False | 1 | `b53e735c3b38cca7697c0a95368ddb5b87fd8aee40a183a5c17d89460766b393` |
| screamer2 | True | 0 | `15e36109931525a2895af814488c402b5394e03eec3ae8896c922adbd885abdc` |
| screamer2 | True | 1 | `887921864b27bf57835e5175895037a5a6d0609207f790d85b265088d5b6663b` |

## Primary source evidence

- [Pinned upstream binary fixes](https://github.com/akitaonrails/rea-screamer-trilogy/blob/c9a21733d7b89cecd4646f1a5249fe482bb9c534/crates/screamer-launcher/src/fixes.rs) and [edition hash profiles](https://github.com/akitaonrails/rea-screamer-trilogy/blob/c9a21733d7b89cecd4646f1a5249fe482bb9c534/crates/screamer-launcher/src/edition.rs).
- [Upstream engine notes, E6 admission limits](https://github.com/akitaonrails/rea-screamer-trilogy/blob/c9a21733d7b89cecd4646f1a5249fe482bb9c534/docs/04-screamer-engine-and-patches.md#33-e6-extended-draw-distance).
- [Upstream runtime file patching](https://github.com/akitaonrails/rea-screamer-trilogy/blob/c9a21733d7b89cecd4646f1a5249fe482bb9c534/crates/screamer-launcher/src/runtime.rs) and [hook telemetry](https://github.com/akitaonrails/rea-screamer-trilogy/blob/c9a21733d7b89cecd4646f1a5249fe482bb9c534/crates/screamer-hooks/src/lib.rs).
- [Rick far-plane, visibility, sort and self-modifying immediate documentation](https://github.com/Rick-Barber/ScreamerRally-Recomp/blob/main/docs/re/strt3fx.md); [far-plane scaling and expanded object lists](https://github.com/Rick-Barber/ScreamerRally-Recomp/blob/main/crates/sr-runtime/src/widescreen.rs); [hand-authored visibility lists](https://github.com/Rick-Barber/ScreamerRally-Recomp/blob/main/crates/sr-runtime/src/visibility.rs). These are STRT3FX-profile documentation; all software patch bytes and the signed-FILD consumer above were independently checked in the actual START65H binaries.

The upstream patch subset is dual MIT/Apache2; the existing build selects MIT and must retain upstream's full MIT copyright/license notice. These new persistence offsets and instructions were derived by static inspection for this task.

## Isolated live verification harness

`tests/live-distance-http.conf` enables only the diagnostic emulator's HTTP server on127.0.0.1:9090 and selects `core=normal`, the core the official0.83.1 API documentation primarily validates. Supply it as an overlay after the normal test config (`-conf normal-test.conf -conf tests/live-distance-http.conf`). Never merge this section into release configs. No browser or API server has been launched by this review.

`tests/verify-live-distance.py` makes only read-only GET requests. Its default snapshot is16MiB, below the documented128MiB per-request limit. It scans for the exact fifteen-byte setter patch, derives all five live CMP addresses by code-relative offsets, verifies their opcodes, and validates the five relocated writer operands against those physical addresses to reject an unrelocated executable-file copy. It reads every live threshold in one atomic memory snapshot.

After visually observing a Rally race begin, run:

```sh
python3 /private/tmp/screamer-trilogy-update/tests/verify-live-distance.py --profile rally --radius 130000 --phase China-race --samples 3
```

For Screamer2 use `--profile screamer2 --radius 104000`. Repeat before/after intro or race changes; the `--phase` tag is operator supplied and is not itself proof that a race started. The JSON also records one far-plane argument immediate written by SetFarDistance, useful for observing scene/race changes. Each successful record must show exactly five threshold values2,112,500,000 for Rally Farther or1,352,000,000 for Extended. `--wait-seconds 30` retries startup/discovery for up to30seconds; individual API reads time out after10seconds by default.

The script's offline self-test passed for all selected profiles/radii, including rejection when one CMP is reset and rejection of unrelocated writer addresses. No live endpoint was accessed here.

Primary protocol and atomic snapshot guarantee: [DOSBox Staging0.83.1 HTTP API](https://github.com/dosbox-staging/dosbox-staging/blob/v0.83.1/website/docs/0.83/manual/http-api.md).

## Complete original functions

### rally: complete SetFarDistance function

Absolute operands below are the original LE object offsets before DOS/4GW relocation. The addresses of the code instructions are mapped VAs. All 158 bytes decoded without gaps.

| VA | Raw offset | Bytes | Instruction |
|---|---|---|---|
| `0x72804` | `0x85804` | `60` | `pushad` |
| `0x72805` | `0x85805` | `a3 57 aa 05 00` | `mov [0x5aa57], eax` |
| `0x7280a` | `0x8580a` | `a3 65 aa 05 00` | `mov [0x5aa65], eax` |
| `0x7280f` | `0x8580f` | `a3 73 aa 05 00` | `mov [0x5aa73], eax` |
| `0x72814` | `0x85814` | `a3 81 aa 05 00` | `mov [0x5aa81], eax` |
| `0x72819` | `0x85819` | `a3 c8 aa 05 00` | `mov [0x5aac8], eax` |
| `0x7281e` | `0x8581e` | `a3 d6 aa 05 00` | `mov [0x5aad6], eax` |
| `0x72823` | `0x85823` | `a3 e4 aa 05 00` | `mov [0x5aae4], eax` |
| `0x72828` | `0x85828` | `a3 b8 be 0c 00` | `mov [0xcbeb8], eax` |
| `0x7282d` | `0x8582d` | `8b d8` | `mov ebx, eax` |
| `0x7282f` | `0x8582f` | `89 1d d5 ac 05 00` | `mov [0x5acd5], ebx` |
| `0x72835` | `0x85835` | `89 1d c6 ac 05 00` | `mov [0x5acc6], ebx` |
| `0x7283b` | `0x8583b` | `81 eb 00 10 00 00` | `sub ebx, 0x1000` |
| `0x72841` | `0x85841` | `50` | `push eax` |
| `0x72842` | `0x85842` | `89 1d 84 99 05 00` | `mov [0x59984], ebx` |
| `0x72848` | `0x85848` | `89 1d 90 99 05 00` | `mov [0x59990], ebx` |
| `0x7284e` | `0x8584e` | `2d 00 20 00 00` | `sub eax, 0x2000` |
| `0x72853` | `0x85853` | `f7 e8` | `imul eax  ; EDX:EAX = signed EAX squared` |
| `0x72855` | `0x85855` | `8b c8` | `mov ecx, eax` |
| `0x72857` | `0x85857` | `8b ea` | `mov ebp, edx` |
| `0x72859` | `0x85859` | `0f ac e9 03` | `shrd ecx, ebp, 3` |
| `0x7285d` | `0x8585d` | `89 0d d0 9f 05 00` | `mov [0x59fd0], ecx` |
| `0x72863` | `0x85863` | `89 0d 34 a0 05 00` | `mov [0x5a034], ecx` |
| `0x72869` | `0x85869` | `89 0d ba a0 05 00` | `mov [0x5a0ba], ecx` |
| `0x7286f` | `0x8586f` | `89 0d 1e a1 05 00` | `mov [0x5a11e], ecx` |
| `0x72875` | `0x85875` | `89 0d 93 18 06 00` | `mov [0x61893], ecx` |
| `0x7287b` | `0x8587b` | `58` | `pop eax` |
| `0x7287c` | `0x8587c` | `8b d8` | `mov ebx, eax` |
| `0x7287e` | `0x8587e` | `f7 d8` | `neg eax` |
| `0x72880` | `0x85880` | `a3 bc be 0c 00` | `mov [0xcbebc], eax` |
| `0x72885` | `0x85885` | `81 eb 80 00 00 00` | `sub ebx, 0x80` |
| `0x7288b` | `0x8588b` | `89 1d c0 97 05 00` | `mov [0x597c0], ebx` |
| `0x72891` | `0x85891` | `b8 00 00 00 00` | `mov eax, 0x0` |
| `0x72896` | `0x85896` | `2d 80 00 00 00` | `sub eax, 0x80` |
| `0x7289b` | `0x8589b` | `a3 bc 97 05 00` | `mov [0x597bc], eax` |
| `0x728a0` | `0x858a0` | `61` | `popad` |
| `0x728a1` | `0x858a1` | `c3` | `ret` |

### screamer2: complete SetFarDistance function

Absolute operands below are the original LE object offsets before DOS/4GW relocation. The addresses of the code instructions are mapped VAs. All 158 bytes decoded without gaps.

| VA | Raw offset | Bytes | Instruction |
|---|---|---|---|
| `0x7ed04` | `0x93504` | `60` | `pushad` |
| `0x7ed05` | `0x93505` | `a3 77 6f 06 00` | `mov [0x66f77], eax` |
| `0x7ed0a` | `0x9350a` | `a3 85 6f 06 00` | `mov [0x66f85], eax` |
| `0x7ed0f` | `0x9350f` | `a3 93 6f 06 00` | `mov [0x66f93], eax` |
| `0x7ed14` | `0x93514` | `a3 a1 6f 06 00` | `mov [0x66fa1], eax` |
| `0x7ed19` | `0x93519` | `a3 e8 6f 06 00` | `mov [0x66fe8], eax` |
| `0x7ed1e` | `0x9351e` | `a3 f6 6f 06 00` | `mov [0x66ff6], eax` |
| `0x7ed23` | `0x93523` | `a3 04 70 06 00` | `mov [0x67004], eax` |
| `0x7ed28` | `0x93528` | `a3 18 84 0d 00` | `mov [0xd8418], eax` |
| `0x7ed2d` | `0x9352d` | `8b d8` | `mov ebx, eax` |
| `0x7ed2f` | `0x9352f` | `89 1d d5 71 06 00` | `mov [0x671d5], ebx` |
| `0x7ed35` | `0x93535` | `89 1d c6 71 06 00` | `mov [0x671c6], ebx` |
| `0x7ed3b` | `0x9353b` | `81 eb 00 10 00 00` | `sub ebx, 0x1000` |
| `0x7ed41` | `0x93541` | `50` | `push eax` |
| `0x7ed42` | `0x93542` | `89 1d a4 5e 06 00` | `mov [0x65ea4], ebx` |
| `0x7ed48` | `0x93548` | `89 1d b0 5e 06 00` | `mov [0x65eb0], ebx` |
| `0x7ed4e` | `0x9354e` | `2d 00 20 00 00` | `sub eax, 0x2000` |
| `0x7ed53` | `0x93553` | `f7 e8` | `imul eax  ; EDX:EAX = signed EAX squared` |
| `0x7ed55` | `0x93555` | `8b c8` | `mov ecx, eax` |
| `0x7ed57` | `0x93557` | `8b ea` | `mov ebp, edx` |
| `0x7ed59` | `0x93559` | `0f ac e9 03` | `shrd ecx, ebp, 3` |
| `0x7ed5d` | `0x9355d` | `89 0d f0 64 06 00` | `mov [0x664f0], ecx` |
| `0x7ed63` | `0x93563` | `89 0d 54 65 06 00` | `mov [0x66554], ecx` |
| `0x7ed69` | `0x93569` | `89 0d da 65 06 00` | `mov [0x665da], ecx` |
| `0x7ed6f` | `0x9356f` | `89 0d 3e 66 06 00` | `mov [0x6663e], ecx` |
| `0x7ed75` | `0x93575` | `89 0d 93 dd 06 00` | `mov [0x6dd93], ecx` |
| `0x7ed7b` | `0x9357b` | `58` | `pop eax` |
| `0x7ed7c` | `0x9357c` | `8b d8` | `mov ebx, eax` |
| `0x7ed7e` | `0x9357e` | `f7 d8` | `neg eax` |
| `0x7ed80` | `0x93580` | `a3 1c 84 0d 00` | `mov [0xd841c], eax` |
| `0x7ed85` | `0x93585` | `81 eb 80 00 00 00` | `sub ebx, 0x80` |
| `0x7ed8b` | `0x9358b` | `89 1d e0 5c 06 00` | `mov [0x65ce0], ebx` |
| `0x7ed91` | `0x93591` | `b8 00 00 00 00` | `mov eax, 0x0` |
| `0x7ed96` | `0x93596` | `2d 80 00 00 00` | `sub eax, 0x80` |
| `0x7ed9b` | `0x9359b` | `a3 dc 5c 06 00` | `mov [0x65cdc], eax` |
| `0x7eda0` | `0x935a0` | `61` | `popad` |
| `0x7eda1` | `0x935a1` | `c3` | `ret` |


## Live follow-up verification — 2026-11-25T01:57:25.504893+00:00

Both isolated headless normal-core tests passed. Rally130,000-unit admission persisted across14 atomic snapshots over5.04–70.38s; Screamer2 104,000-unit admission persisted across11 snapshots over5.04–55.35s. Every snapshot checked all five actual relocated CMP immediates. Original scene far-plane parameter -43,808 changed to -50,000 in both guests, proving scene setup executed while the admission thresholds stayed selected.

This is a scene-setup/persistence check with core=normal, dummy video/audio, widescreen off, and no input automation. It does not establish visually observed race behavior or release auto/dynamic-core stability. Both engines were stopped cleanly with exit0. Full timestamps, scope and evidence paths are in `tests/live-distance-results.md`; machine-readable samples are under the two `tests/headless-live-*` directories. No source patches were changed by this follow-up.
