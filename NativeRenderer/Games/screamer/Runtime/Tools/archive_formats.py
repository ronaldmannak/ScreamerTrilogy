#!/usr/bin/env python3
"""Inspect owned S1 archive metadata and geometry without executing the game.

DAT/LZW format provenance: Rick-Barber/ScreamerRally-Recomp,
crates/sr-disc/src/dat.rs. This independent decoder uses dictionary byte strings;
no decompressed copyrighted assets are written to disk.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct


def require(condition, message):
    if not condition:
        raise ValueError(message)


def u32(data, offset):
    require(0 <= offset <= len(data) - 4, f'Out-of-bounds dword: {offset:#x}')
    return struct.unpack_from('<I', data, offset)[0]


def lzw(packed, expected):
    require(expected <= 16 * 1024 * 1024, 'Asset exceeds investigation bound')
    output, previous, bits, width = bytearray(), None, 0, 9
    table = [bytes([n]) for n in range(256)] + [None, None]
    while len(output) < expected:
        require(bits + width <= len(packed) * 8, 'Truncated LZW stream')
        index = bits // 8
        code = (int.from_bytes(packed[index:index + 3], 'little') >> (bits % 8)) & ((1 << width) - 1)
        bits += width
        if code == 256:
            table = [bytes([n]) for n in range(256)] + [None, None]
            width, previous = 9, None
            continue
        if code == 257:
            break
        if code < len(table):
            word = table[code]
            require(word is not None, 'Reserved LZW code')
        else:
            require(code == len(table) and previous is not None, 'Undefined LZW code')
            word = previous + previous[:1]
        output.extend(word)
        require(len(output) <= expected, 'LZW output overflow')
        if previous is not None and len(table) < 4096:
            table.append(previous + word[:1])
            if len(table) == 1 << width and width < 12:
                width += 1
        previous = word
    require(len(output) == expected, 'Incorrect LZW output length')
    return bytes(output)


def archive(path):
    raw = path.read_bytes()
    length = u32(raw, len(raw) - 4)
    require(length % 32 == 0 and length <= len(raw) - 4, 'Invalid DAT directory')
    directory = len(raw) - length - 4
    entries = {}
    for offset in range(directory, len(raw) - 4, 32):
        name = bytes(v ^ 0x3a for v in raw[offset:offset + 16]).split(b'\0')[0]
        if not name:
            break
        start, packed, size, flags = struct.unpack_from('<4I', raw, offset + 16)
        require(start + packed <= directory, 'DAT entry overlaps directory')
        entries[name.decode('ascii')] = (start, packed, size, flags)
    def read(name):
        start, packed, size, flags = entries[name]
        source = raw[start:start + packed]
        result = lzw(source, size) if flags & 2 else source
        require(len(result) == size, 'Incorrect uncompressed asset size')
        return result
    return raw, entries, read


def material_summary(data):
    materials = []
    for offset in range(0, min(len(data), 16384), 16):
        kind, frame_offset, width, height = struct.unpack_from('<4I', data, offset)
        if not any((kind, frame_offset, width, height)):
            break
        frames = []
        if frame_offset:
            count, phase = struct.unpack_from('<2I', data, frame_offset)
            require(0 < count <= 1024, 'Invalid frame count')
            frames = [u32(data, frame_offset + 8 + i * 4) for i in range(count)]
            require(0 < width <= 256 and 0 < height <= 256, 'Invalid material extent')
            require(all(p + (height - 1) * 256 + width <= len(data) for p in frames), 'Texture crop exceeds MLB')
        materials.append({'offset':offset, 'type':kind, 'width':width, 'height':height,
                          'frame_count':len(frames), 'frame_offsets':frames})
    else:
        raise ValueError('Unterminated material directory')
    return {'count':len(materials),'types':dict(Counter(m['type'] for m in materials)),
            'frame_references':sum(m['frame_count'] for m in materials),
            'unique_texture_offsets':len({p for m in materials for p in m['frame_offsets']}),
            'materials':materials}


def model_summary(data, base=0):
    count = u32(data, base + 0x14)
    require(0 < count <= 65, 'Invalid model part count')
    offsets = [u32(data, base + 0x18 + i * 4) for i in range(count)]
    vertices_total = polygons_total = triangles_total = 0
    names = []
    for offset in offsets:
        part = base + offset
        vertex_at = base + u32(data, part + 0x1c)
        vertices = 0
        while vertices < 32767:
            require(vertex_at + vertices * 6 + 6 <= len(data), 'Unterminated vertices')
            if struct.unpack_from('<h', data, vertex_at + vertices * 6)[0] == 0x7fff:
                break
            vertices += 1
        else:
            raise ValueError('Too many vertices')
        records = set()
        for order in range(16):
            order_offset = u32(data, part + 0x28 + order * 4)
            if not order_offset:
                continue
            pos = part + order_offset
            for n in range(65536):
                require(pos + n * 2 + 2 <= len(data), 'Unterminated polygon order')
                p = struct.unpack_from('<h', data, pos + n * 2)[0]
                if p <= 0:
                    break
                records.add(part + p)
            else:
                raise ValueError('Too many polygon order records')
        for record in records:
            n = struct.unpack_from('<H',data,record + 6)[0]
            require(3 <= n <= 64, 'Invalid polygon vertex count')
            indices = struct.unpack_from('<' + str(n) + 'H', data, record + 8)
            require(all(i % 6 == 0 and i // 6 < vertices for i in indices), 'Invalid polygon vertex index')
            triangles_total += n - 2
        vertices_total += vertices
        polygons_total += len(records)
        names.append(data[part + 0x68:part + 0x78].split(b'\0')[0].decode('ascii', errors='replace'))
    return {'parts':count,'vertices':vertices_total,'polygons':polygons_total,
            'fan_triangles':triangles_total,'part_names':names}


def grid_summary(data, model_count):
    cells = objects = 0
    model_use = Counter()
    for row in range(256):
        rp = u32(data, row * 4)
        if rp == 0xffffffff:
            continue
        for col in range(256):
            cp = u32(data, rp + col * 4)
            if cp == 0xffffffff:
                continue
            cells += 1
            for listing in (0, 1):
                base, count = u32(data, cp + 4 * listing), u32(data, cp + 0x14 + 4 * listing)
                require(count <= 65536 and base + count * 0x40 <= len(data), 'Invalid cell object list')
                for i in range(count):
                    model = u32(data, base + i * 0x40)
                    require(model < model_count, 'Invalid world model index')
                    model_use[model] += 1
                objects += count
    return {'cells':cells,'static_objects':objects,'unique_models_used':len(model_use),
            'model_use':dict(model_use)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--game-root',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    args = p.parse_args()
    require(not args.output.exists(), 'Refusing to overwrite research evidence')
    report = {'scope':'Static archive inspection only; no engine launched, no assets exported','tracks':[]}
    for number in range(1,7):
        filename = f'GFX/MAP{number}H.DAT'
        raw, entries, read = archive(args.game_root / filename)
        bank = read(f'MAP{number}.UNR')
        data_size, count = struct.unpack_from('<2I',bank)
        require(0 < count < 10000,'Invalid model bank count')
        model_start = 8 + 4 * count
        require(model_start + data_size == len(bank),'Model bank length mismatch')
        models = [model_summary(bank, model_start + u32(bank,8 + 4*i)) for i in range(count)]
        grid = grid_summary(read(f'MAP{number}.MMP'), count)
        materials = material_summary(read(f'MAP{number}.MLB'))
        palette = read(f'MAP{number}.COL')
        require(len(palette)==768 and max(palette)<=63,'Unexpected VGA palette')
        report['tracks'].append({'archive':filename,'archive_sha256':hashlib.sha256(raw).hexdigest(),
            'model_bank_sha256':hashlib.sha256(bank).hexdigest(),'models':count,
            'high_lod_model_parts':sum(m['parts'] for m in models),
            'high_lod_unique_vertices':sum(m['vertices'] for m in models),
            'high_lod_unique_polygons':sum(m['polygons'] for m in models),
            'high_lod_unique_fan_triangles':sum(m['fan_triangles'] for m in models),
            'grid':grid,'materials':materials,'palette_bytes':len(palette),'palette_range':[min(palette),max(palette)]})
        print(filename,'models',count,'cells',grid['cells'],'objects',grid['static_objects'],'materials',materials['count'],flush=True)
    with args.output.open('x') as f:
        json.dump(report,f,indent=2)
        f.write('\n')


if __name__ == '__main__':
    main()
