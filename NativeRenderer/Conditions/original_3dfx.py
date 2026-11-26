#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Bounded offline readers for owned Screamer 2/Rally model/material assets.

No guest execution or guest memory writes. DAT/LZW and geometry conventions
follow the retained reverse-engineering attribution in THIRD_PARTY_NOTICES.md.
"""
from array import array
import binascii
import hashlib
import math
from pathlib import Path
import struct
import sys
import zlib


def require(value, message):
    if not value:
        raise ValueError(message)


def unpack(data, fmt, offset):
    size = struct.calcsize(fmt)
    require(isinstance(offset, int) and 0 <= offset <= len(data) - size, 'Original asset field exceeds bounds')
    return struct.unpack_from(fmt, data, offset)


def u32(data, offset):
    return unpack(data, '<I', offset)[0]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def lzw(data, expected):
    require(0 <= expected <= 16 * 1024**2, 'Original asset exceeds decode bound')
    output, previous, bits, width = bytearray(), None, 0, 9
    table = [bytes([i]) for i in range(256)] + [None, None]
    while len(output) < expected:
        require(bits + width <= len(data) * 8, 'Truncated original LZW')
        offset = bits // 8
        code = (int.from_bytes(data[offset:offset+3], 'little') >> (bits % 8)) & ((1 << width)-1)
        bits += width
        if code == 256:
            table = [bytes([i]) for i in range(256)] + [None, None]
            previous, width = None, 9
            continue
        if code == 257:
            break
        if code < len(table):
            word = table[code]
            require(word is not None, 'Reserved original LZW code')
        else:
            require(code == len(table) and previous is not None, 'Undefined original LZW code')
            word = previous + previous[:1]
        output.extend(word)
        require(len(output) <= expected, 'Original LZW overflow')
        if previous is not None and len(table) < 4096:
            table.append(previous + word[:1])
            if len(table) == 1 << width and width < 12:
                width += 1
        previous = word
    require(len(output) == expected, 'Original asset decode length differs')
    return bytes(output)


def archive_entry(path, name):
    raw = Path(path).read_bytes()
    require(4 <= len(raw) <= 128 * 1024**2, 'Unsupported original archive size')
    length = u32(raw, len(raw)-4)
    require(length % 32 == 0 and length <= len(raw)-4, 'Invalid original DAT directory')
    directory, found = len(raw)-length-4, None
    for at in range(directory, len(raw)-4, 32):
        entry = bytes(v ^ 0x3a for v in raw[at:at+16]).split(b'\0')[0]
        if not entry:
            break
        offset, packed, size, flags = unpack(raw, '<4I', at+16)
        require(offset + packed <= directory and size <= 16*1024**2, 'Original DAT entry exceeds bounds')
        if entry.decode('ascii').upper() == name.upper():
            require(found is None, 'Ambiguous original DAT entry')
            found = (offset, packed, size, flags)
    require(found is not None, 'Original asset is absent: ' + name)
    offset, packed, size, flags = found
    data = raw[offset:offset+packed]
    result = lzw(data, size) if flags & 2 else data
    require(len(result) == size, 'Original DAT entry length differs')
    return result, {'archive': Path(path).name, 'archive_sha256': sha(raw),
                    'entry': name, 'entry_sha256': sha(result), 'entry_bytes': len(result)}


def png(width, height, pixels):
    require(0 < width <= 4096 and 0 < height <= 4096 and len(pixels) == width*height*4, 'Invalid original RGBA extent')
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', binascii.crc32(kind+data)&0xffffffff)
    rows = b''.join(b'\0'+pixels[y*width*4:(y+1)*width*4] for y in range(height))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>2I5B',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(rows,6))+chunk(b'IEND',b'')


def rgb565(value, indexed=False):
    r, g, b = (value >> 11)&31, (value >> 5)&63, value&31
    return (r << 3, g << 2, b << 3) if indexed else ((r << 3)|(r >> 2),(g << 2)|(g >> 4),(b << 3)|(b >> 2))


def rgba4444(value):
    return tuple(((value >> shift)&15)*17 for shift in (8,4,0,12))


def palette4444(value, alpha=15):
    # Original converter ccae4: green rounds (g6+1)>>2, capped to 15.
    return ((alpha&15)<<12) | (((value>>12)&15)<<8) | (min(15,(((value>>5)&63)+1)>>2)<<4) | ((value&31)>>1)


def material_mode(kind):
    if kind in (0x80,0x90):return 2
    if 0x30 <= kind <= 0x70:return 1
    if kind in (0xa0,0xb0) or 0x160 <= kind <= 0x1f0:return 5
    if kind in (0xc0,0xd0):return 4
    if kind in (0xe0,0xf0):return 3
    if kind in (0x100,0x110):return 6
    if kind in (0x120,0x130):return 7
    return 0


def rotation(angles):
    a,b,c = [(v&2047)*math.tau/2048 for v in angles]
    sa,ca,sb,cb,sc,cc=math.sin(a),math.cos(a),math.sin(b),math.cos(b),math.sin(c),math.cos(c)
    return [[cc*cb-sc*sb*sa,-cc*sb*sa-sc*cb,-ca*sb],
            [sc*ca,cc*ca,-sa],[sc*cb*sa+cc*sb,cc*cb*sa-sc*sb,cb*ca]]


def transform(matrix, translation, point):
    return [sum(matrix[r][c]*point[c] for c in range(3))+translation[r] for r in range(3)]


def write_array(path, values):
    require(values.itemsize == 4, 'Original scene requires four-byte elements')
    if sys.byteorder != 'little':values.byteswap()
    with Path(path).open('xb') as stream:values.tofile(stream)


class RawAssets:
    """Original UNR model bank or one 3DX car plus its MLB/HIC textures."""
    def __init__(self, bank, mlb, hic, output, *, single_model=False, env_mlb=None, env_hic=None,
                 special_colors=(0xedc,0xedc,0)):
        self.bank,self.mlb,self.hic = bytes(bank),bytes(mlb),bytes(hic)
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        (self.output/'textures').mkdir(exist_ok=True)
        self.single_model=single_model
        if single_model:self.model_bases=[0]
        else:
            size,count=unpack(self.bank,'<2I',0)
            require(0 < count <= 4096, 'Original model bank count exceeds bound')
            start=8+4*count
            require(start+size==len(self.bank),'Original model bank size differs')
            self.model_bases=[start+u32(self.bank,8+4*i) for i in range(count)]
        self.materials,self.models,self.parts,self.texture_ids={},{},{},{}
        self.textures=[]
        self.special_colors=special_colors
        self.environment=None
        if env_mlb is not None:
            self.environment=RawAssets(self.bank,env_mlb,env_hic,self.output/'environment',single_model=single_model,
                                       special_colors=special_colors)

    def model(self,index=0):
        require(0 <= index < len(self.model_bases),'Original model index exceeds bank')
        if index not in self.models:
            base=self.model_bases[index];count=u32(self.bank,base+0x14)
            require(0 < count <= 13,'Unsupported original 3dfx part count')
            self.models[index]={'base':base,'parts':count,'animation_frames':unpack(self.bank,'<i',base+0x10)[0],
                                'levels':[[u32(self.bank,base+0x18+0x34*level+4*i) for i in range(count)] for level in range(3)]}
        return self.models[index]

    def part(self,model,offset):
        base=model['base'];at=base+offset
        if at in self.parts:return self.parts[at]
        vertex_at=base+u32(self.bank,at+0x1c);vertices=[]
        for i in range(8192):
            value=unpack(self.bank,'<3h',vertex_at+6*i)
            if value[0]==0x7fff:break
            vertices.append(value)
        else:raise ValueError('Unterminated original vertex table')
        uv_offset=u32(self.bank,at+0x24)
        uv=[unpack(self.bank,'<3h',base+uv_offset+6*i)[:2] for i in range(len(vertices))] if uv_offset else [(0,0)]*len(vertices)
        flags=u32(self.bank,at+0x18);normals=[];normal_offset=u32(self.bank,at+0x20)
        if flags&0x2000:
            require(normal_offset not in (0,0xffffffff),'Missing original reflection normals')
            normal_at=base+normal_offset;count=u32(self.bank,normal_at)
            require(0<count<=len(vertices),'Invalid original reflection normal count')
            normals=[unpack(self.bank,'<3f',normal_at+4+12*i) for i in range(count)]
        records=set()
        for j in range(16):
            order=u32(self.bank,at+0x28+4*j)
            if not order:continue
            for i in range(65536):
                value=unpack(self.bank,'<h',at+order+2*i)[0]
                if value<=0:break
                records.add(at+value)
            else:raise ValueError('Unterminated original polygon order')
        polygons=[]
        for record in sorted(records):
            color,material,count=unpack(self.bank,'<HhH',record+2)
            require(3<=count<=64,'Invalid original polygon extent')
            indices=unpack(self.bank,'<'+'H'*count,record+8)
            require(all(v%6==0 and v//6<len(vertices) for v in indices),'Invalid original polygon index')
            polygons.append({'color':color,'material':material,'indices':[v//6 for v in indices],
                             'record_normal':unpack(self.bank,'<3i',record+0x14)})
        result={'vertices':vertices,'uv':uv,'normals':normals,'flags':flags,'polygons':polygons,
                'name':self.bank[at+0x68:at+0x78].split(b'\0')[0].decode('ascii',errors='replace')}
        self.parts[at]=result
        return result

    def placement(self,model,slot):
        base=model['base'];part=base+model['levels'][0][slot];at=base+u32(self.bank,part+0xc)
        if model['animation_frames']>=0:
            words=unpack(self.bank,'<12h',at+0x1c)
            return [[words[r+3*c]/16384 for c in range(3)] for r in range(3)],words[9:12]
        return rotation(unpack(self.bank,'<3i',at+4)),unpack(self.bank,'<3i',at+0x10)

    def material(self,offset):
        if offset not in self.materials:
            kind,frames,w,h,palette=unpack(self.mlb,'<5I',offset)
            indices=[]
            if frames:
                count,_=unpack(self.mlb,'<2I',frames)
                require(0<count<=1024 and 0<w<=256 and 0<h<=256,'Invalid original material extent')
                indices=list(unpack(self.mlb,'<'+'I'*count,frames+8))
                require(all(p+(h-1)*256+w<=len(self.mlb) for p in indices),'Original texture exceeds MLB')
            mode=material_mode(kind)
            self.materials[offset]={'offset':offset,'type':kind,'width':w,'height':h,'frames':indices,
                                    'palette_offset':palette,'mode':mode,'blend_mode':'source_color' if mode==3 else 'alpha' if mode in (6,7) else 'opaque'}
        return self.materials[offset]

    def texture(self,material,animation=0,reflection_phase=0):
        if material['mode']==5 and self.environment is not None:
            texture=self.environment.texture(self.environment.material(0),animation,reflection_phase)
            if texture is None:return None
            original=self.environment.textures[texture];key=('env',texture)
            if key not in self.texture_ids:
                self.texture_ids[key]=len(self.textures)
                self.textures.append({**original,'path':'environment/'+original['path']})
            return self.texture_ids[key]
        frames=material['frames']
        if not frames:return None
        if material['mode']==5:index=min(len(frames)-1,len(frames)*(reflection_phase&0xffff)>>16)
        else:
            phase=0 if animation<0 else ((animation&0xffff)>>2 if animation&0x60000 else animation>>2)
            index=max(0,min(len(frames)-1,len(frames)*phase>>14))
        pointer=frames[index];w,h=material['width'],material['height']
        key=(material['offset'],pointer,w,h)
        if key in self.texture_ids:return self.texture_ids[key]
        pixels=bytes(v for y in range(h) for v in self.mlb[pointer+y*256:pointer+y*256+w])
        palette_at=8+material['palette_offset']
        palette=unpack(self.hic,'<256H',palette_at)
        kind,mode=material['type'],material['mode'];grey=mode==7 and any(0x30<=v<0x40 for v in pixels)
        if grey:material['blend_mode']='modulate2x'
        rgba=bytearray()
        indexed=mode in (0,1,4) and w*h>1024
        for value in pixels:
            if grey:
                n=min(31,(value&15)+17);rgba.extend((*rgb565((n<<11)|(n<<6)|n),255))
            elif mode==6:
                rgba.extend(rgba4444(0 if value==0 else palette4444(palette[value],6 if value>=0xf0 else 15)))
            elif mode==7:
                if value==0:color=0
                elif value<0x30:
                    group=value>>4;rgb=self.special_colors[(2,0,1)[group]]
                    color=((value&15)<<12)|(rgb&0xfff)
                elif value<0x60:color=((value&15)<<12)|0xfff
                else:color=palette4444(palette[value])
                rgba.extend(rgba4444(color))
            else:
                rgb=rgb565(palette[value],indexed)
                rgba.extend((*rgb,0 if mode in (1,3) and palette[value]==palette[0] else 255))
        encoded=png(w,h,bytes(rgba));ident=len(self.textures);relative=f'textures/{ident:04d}.png'
        (self.output/relative).write_bytes(encoded)
        self.texture_ids[key]=ident
        self.textures.append({'path':relative,'width':w,'height':h,'sha256':sha(encoded),
                              'source':'original owned MLB indexed texels + HIC RGB565; original ccae4 conversion',
                              'source_frame_offset':pointer,'source_material_type':kind,'frame_index':index,
                              'grey_blend':grey,'blend_mode':material['blend_mode']})
        if mode in (3, 6, 7):
            raw_name = relative[:-4] + '.rgba'
            (self.output / raw_name).write_bytes(rgba)
            self.textures[-1].update(rgba_file=raw_name, rgba_sha256=sha(rgba))
        return ident
