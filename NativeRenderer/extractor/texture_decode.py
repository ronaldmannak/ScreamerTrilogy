# SPDX-License-Identifier: GPL-3.0-only
"""Read retained original Glide texture records and encode PNGs with the stdlib.

Record/format definitions follow Rick-Barber/ScreamerRally-Recomp native/textures.rs
and glide/tex.rs. Guest texture RAM is never accessed through a host pointer.
"""
from collections import Counter
import binascii
import hashlib
import struct
import zlib


RECORDS = 0x1479d4
RECORD_SIZE = 0x38
RECORD_COUNT = 0xbf8


def png_rgba(width, height, pixels):
    if len(pixels) != width * height * 4:
        raise ValueError('RGBA byte count does not match texture dimensions')
    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', binascii.crc32(kind + payload) & 0xffffffff)
    rows = b''.join(b'\0' + pixels[row * width * 4:(row + 1) * width * 4] for row in range(height))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>2I5B', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows, 6)) + chunk(b'IEND', b''))


def dimensions(lod, aspect):
    size = 256 >> min(lod, 8)
    if aspect <= 3:
        return size, max(1, size >> (3 - aspect))
    return max(1, size >> (aspect - 3)), size


def rgba_pixels(raw, kind, palette=None):
    output = bytearray()
    if kind == 5:
        if palette is None or len(palette) != 256:
            raise ValueError('Indexed8 texture requires 256 palette entries')
        for index in raw:
            rgb = palette[index]
            output.extend(((rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255, 255))
    elif kind == 10:
        for value, in struct.iter_unpack('<H', raw):
            r, g, b = value >> 11, (value >> 5) & 63, value & 31
            output.extend(((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2), 255))
    elif kind == 12:
        for value, in struct.iter_unpack('<H', raw):
            output.extend((((value >> 8) & 15) * 17, ((value >> 4) & 15) * 17,
                           (value & 15) * 17, (value >> 12) * 17))
    else:
        raise ValueError(f'Unsupported original Glide texture format {kind:#x}')
    return bytes(output)


def export_textures(memory, output):
    """Return scene texture metadata and original record-id -> scene-index map."""
    directory = output / 'textures'
    directory.mkdir()
    textures, index_by_record, rejected = [], {}, []
    formats = Counter()
    base = memory.link(RECORDS)
    for record in range(RECORD_COUNT):
        address = base + record * RECORD_SIZE
        if not memory.rd32(address):
            continue
        try:
            small = memory.rd32(address + 0x18) & 15
            large = memory.rd32(address + 0x1c) & 15
            aspect = memory.rd32(address + 0x20) & 7
            kind = memory.rd32(address + 0x24) & 15
            if small != large or large > 8 or kind not in (5, 10, 12):
                raise ValueError(f'Unsupported layout small={small},large={large},format={kind}')
            width, height = dimensions(large, aspect)
            raw = memory.bytes(memory.pointer(address + 0x28), width * height * (1 if kind == 5 else 2))
            palette_address = memory.pointer(address + 0xc)
            palette = [memory.rd32(palette_address + 4 * i) for i in range(256)] if kind == 5 else None
            rgba = rgba_pixels(raw, kind, palette)
            chroma = memory.rd32(address + 0x14) & 0xffffff
            # Opaque material RGB must survive image loaders that premultiply.
            # Keyed use gets a separate variant, created only when referenced.
            opaque = bytearray(rgba)
            for at in range(3, len(opaque), 4):
                opaque[at] = 255
            rgba = bytes(opaque)
            png = png_rgba(width, height, rgba)
            name = f'textures/{record:04d}.png'
            (output / name).write_bytes(png)
            index_by_record[record] = len(textures)
            textures.append({'path': name, 'record': record, 'width': width, 'height': height,
                             'glide_format': kind, 'sha256': hashlib.sha256(png).hexdigest(),
                             'chroma_key': chroma, 'chroma_alpha_encoded': False,
                             'variant': 'opaque',
                             'grey_blend': memory.rd32(address + 0x34) != 0,
                             'source_texel_sha256': hashlib.sha256(raw).hexdigest()})
            formats[str(kind)] += 1
        except (ValueError, IndexError, KeyError) as error:
            rejected.append({'record': record, 'reason': str(error)})
    return textures, index_by_record, {'decoded': len(textures), 'formats': dict(formats), 'rejected': rejected}


def export_keyed_variant(memory, output, original):
    """A separate alpha-tested image, preserving opaque use of the same record."""
    record = original['record']
    address = memory.link(RECORDS) + record * RECORD_SIZE
    width, height, kind = original['width'], original['height'], original['glide_format']
    raw = memory.bytes(memory.pointer(address + 0x28), width * height * (1 if kind == 5 else 2))
    palette_address = memory.pointer(address + 0xc)
    palette = [memory.rd32(palette_address + 4 * i) for i in range(256)] if kind == 5 else None
    keyed = bytearray(rgba_pixels(raw, kind, palette))
    for at in range(0, len(keyed), 4):
        rgb = keyed[at] << 16 | keyed[at + 1] << 8 | keyed[at + 2]
        keyed[at + 3] = 0 if rgb == original['chroma_key'] else 255
    png = png_rgba(width, height, bytes(keyed))
    name = f'textures/{record:04d}-keyed.png'
    (output / name).write_bytes(png)
    return {**original, 'path': name, 'sha256': hashlib.sha256(png).hexdigest(),
            'variant': 'chroma-key', 'chroma_alpha_encoded': True}


def export_blended_variant(memory, output, original):
    """Retain the original texel alpha for a genuine blended-material pipeline."""
    record = original['record']
    address = memory.link(RECORDS) + record * RECORD_SIZE
    width, height, kind = original['width'], original['height'], original['glide_format']
    raw = memory.bytes(memory.pointer(address + 0x28), width * height * (1 if kind == 5 else 2))
    palette_address = memory.pointer(address + 0xc)
    palette = [memory.rd32(palette_address + 4 * i) for i in range(256)] if kind == 5 else None
    rgba = rgba_pixels(raw, kind, palette)
    png = png_rgba(width, height, rgba)
    name = f'textures/{record:04d}-blended.png'
    (output / name).write_bytes(png)
    raw_name = f'textures/{record:04d}-blended.rgba'
    (output / raw_name).write_bytes(rgba)
    return {**original, 'path': name, 'sha256': hashlib.sha256(png).hexdigest(),
            'variant': 'original-alpha', 'chroma_alpha_encoded': False,
            'rgba_file': raw_name, 'rgba_sha256': hashlib.sha256(rgba).hexdigest()}
