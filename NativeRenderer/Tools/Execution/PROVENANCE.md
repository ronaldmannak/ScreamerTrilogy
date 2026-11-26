# Supported guest and three-tick patch

The tool supports the same original Italian-CD `STRT3FX.EXE` profile used by Rick's runtime:

| Input | Size | SHA-256 |
|---|---:|---|
| `STRT3FX.EXE` | 1,044,502 | `9eac6e12ab309389bdda019cfa695bfbbc791fbda1a4634464a444fce35165d1` |
| Genuine DOS `GLIDE2X.OVL` | 348,791 | `6981a7bd77445be7b360ca367af1e527927db396546db15b69803b16a67676a9` |

The source files are required externally and are never modified. No original payload bytes, except the short instruction guards below, are included in this bundle.

## Guard and change

LE code object 2 has link base `0x20000`. The wait helper at link VA `0x504dc` maps to file offset `0x556dc` in this exact executable:

```text
50 a1 12 05 03 00 83 f8 01 7c f6 58 c3
```

The three-byte compare at VA `0x504e2`, raw `0x556e2`, changes:

```text
83 f8 01   cmp eax, 1
83 f8 03   cmp eax, 3
```

Only raw byte `0x556e4` changes. The resulting executable must hash to:

```text
2fd67bfeb387558da4952dcd8442864e869e67ca5ef39793526cafd34358b9d4
```

The neighboring relocated tick-counter address operand is retained unchanged. This numeric change leaves the HMI timer at 100 Hz, the existing dt clamps/smoothing and physics tables intact, and applies to the common menu/race wait helper. Guest menus also receive the three-tick minimum. No Rick runtime, Windows write-watch implementation, frame interpolation code, F7 texture patches, widescreen patch, or distance patch is copied into the guest by this tool.

Original hash, complete helper context, LE mapping, output hash and the complete one-byte difference are checked before any output directory or engine process is created. These guards use explicit exceptions and remain active under Python optimization.

## Runtime base resolution

The loaded helper's relocated tick pointer must equal the helper address plus `0x36`; this rejects an unrelocated file-image copy. That establishes code object 2's loaded base. The tool then reads relocated internal 32-bit operands from that code and votes on each target object's base. Required data object 6 must resolve; the selected bases and evidence counts are recorded.

The observed prototype maps were code object 2 at `0x1e1000` and data object 6 at `0x2b0000`. These are observations only and are not hardcoded. Scene/camera/model markers are resolved through the live maps, not through those historical addresses.

## Primary sources

- [Rick's STRT3FX executable profile](https://github.com/Rick-Barber/ScreamerRally-Recomp/blob/main/crates/sr-runtime/src/profile/strt3fx.rs).
- [Rick's pacing implementation and measured simulation-rate dependence](https://github.com/Rick-Barber/ScreamerRally-Recomp/blob/main/crates/sr-runtime/src/pacing.rs).
- [Rick's timing reverse-engineering notes](https://github.com/Rick-Barber/ScreamerRally-Recomp/blob/main/docs/re/strt3fx.md#timing-verified).
- [DOSBox Staging 0.83.1 Voodoo documentation](https://github.com/dosbox-staging/dosbox-staging/blob/v0.83.1/website/docs/0.83/manual/graphics/3dfx-voodoo.md).
- [DOSBox Staging 0.83.1 HTTP API](https://github.com/dosbox-staging/dosbox-staging/blob/v0.83.1/website/docs/0.83/manual/http-api.md) and [memory/register capture implementation](https://github.com/dosbox-staging/dosbox-staging/blob/v0.83.1/src/webserver/memory.cpp).

The executable instructions, LE mapping and derived hash were independently verified against the supported original file. The capture logic is Python orchestration and read-only inspection; it does not port or embed Rick's guest-execution runtime.

The historical first top-level snapshot from the exploratory session was overwritten before per-session preservation was introduced. Its old hash alone cannot reproduce those exact bytes. The later advertised three-frame sequence was retained unchanged. This packaged tool requires a fresh output directory and exclusive capture-file creation to prevent that recurrence.
