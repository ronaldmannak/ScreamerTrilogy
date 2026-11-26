# SPDX-License-Identifier: GPL-3.0-only
"""Render-only port of the original 3dfx fog table builder.

Rally STRT3FX 5527A and Screamer 2 S2_3DFX 56CA6 build the same 64-byte
Glide table. DEPTH*.DPT is not this table: the 3dfx DPT entry points ignore
their filename arguments and select a constant shade instead. No guest code,
memory writes, clocks, or game assets are needed to evaluate this function.
"""
import math
import struct


def float32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def original_glide_fog(far=25000, color_rgb=(184, 184, 184)):
    """Return original table fog parameters for positive axial far distance.

    Original signed depth is negative. The routine stores depth operands as
    float32; division, the original double constant and fsin remain on x87's
    stack until truncation. The near parameter is cached but never used.
    """
    if type(far) not in (int, float) or not math.isfinite(far) or not 128 < far <= 10000000:
        raise ValueError('Original fog far distance is invalid')
    if not isinstance(color_rgb, (list, tuple)) or len(color_rgb) != 3 or any(
            type(value) is not int or not 0 <= value <= 255 for value in color_rgb):
        raise ValueError('Original fog color requires three bytes')
    signed = -int(far)
    # Original black haze extends the table endpoint by signed/2, truncating
    # toward zero; colored Fog uses the camera far distance without extension.
    endpoint = float32(signed if any(color_rgb) else signed + math.trunc(signed / 2))
    table = [0] * 64
    for slot in range(3, 32):
        depth = float32(-(slot - 3) * 800)
        if depth < endpoint:
            depth = float32(endpoint - 1.0)
        # Literal original EXE double (122038 in Rally), not a fitted curve.
        value = math.trunc(math.sin((depth / endpoint) * 1.570796327) * 255.0)
        table[32 + slot] = value & 255
    # This is the table falloff input, not a projection/world-culling far plane.
    return {'color_rgb': list(color_rgb), 'table': table, 'w_scale': 1,
            'far_distance': int(far)}
