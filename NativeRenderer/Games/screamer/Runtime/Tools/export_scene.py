#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Export owned original Screamer (1995) track assets to the Metal scene contract.

Geometry conventions derive from Rick-Barber/ScreamerRally-Recomp's documented
GPL-3.0 renderer; the S1 formats were independently checked against STARTH.EXE.
This tool executes no guest code and modifies no original files.
"""
from array import array
from collections import Counter
import argparse
import binascii
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import sys
import uuid
import zlib

from archive_formats import archive, require, u32

EXE_SHA = '1246afc95463f96598d5fee764fc99c847b6d3e0bf8ca2268bd362c664bb28a3'
ARCHIVE_SHA = {
    1:'2d4c9e308a9856b0e77b1d1c8a9487a72b1aba70bf3a2757bcb9ef5efe25e861',
    2:'56017a5c989a05bd80768b8628805e4a451aca628ba7e6f0f3c6be366915344f',
    3:'d9a07fc578342797551b3dda20afc2d7308363ccc7afdf989f7480f99c7e92a7',
    4:'e06e6c73675612cf0103aee2303928c84ba7db446951e419ee81103879c39b66',
    5:'6f6e87e89c65b2203413e26821ec86f54099b7f2bf8dbda784d5c089ad06a2c3',
    6:'7ed452ad0d6c7188e67e804f659d7a55d87170050fb1325ce472d1c8c27ec359',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unpack(data, fmt, at):
    require(0 <= at <= len(data) - struct.calcsize(fmt), f'Out-of-bounds field {at:#x}')
    return struct.unpack_from(fmt,data,at)


def rotation(angles):
    a,b,c=[(angle & 2047)*math.tau/2048 for angle in angles]
    sa,ca,sb,cb,sc,cc=math.sin(a),math.cos(a),math.sin(b),math.cos(b),math.sin(c),math.cos(c)
    return [[cc*cb-sc*sb*sa,-cc*sb*sa-sc*cb,-ca*sb],
            [sc*ca,cc*ca,-sa],
            [sc*cb*sa+cc*sb,cc*cb*sa-sc*sb,cb*ca]]


def transform(matrix, translation, point):
    return [sum(matrix[r][c]*point[c] for c in range(3))+translation[r] for r in range(3)]


def polygon_double_sided(vertices,indices,record_normal):
    """Keep authored face-normal exceptions at their previous two-sided policy.

    Original83853/83907/83BC7 culls by one record normal, while native culling
    uses each emitted fan triangle. Only conforming fans may use CW back cull.
    """
    if len(record_normal)!=3 or not all(math.isfinite(v) for v in record_normal):
        return True
    if not any(record_normal):return True
    first=vertices[indices[0]]
    for corner in range(1,len(indices)-1):
        a=[vertices[indices[corner]][k]-first[k] for k in range(3)]
        b=[vertices[indices[corner+1]][k]-first[k] for k in range(3)]
        cross=[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
        if not all(math.isfinite(v) for v in cross):return True
        if any(cross) and sum(cross[k]*record_normal[k] for k in range(3))>=0:
            return True
    return False

def png(width,height,pixels):
    require(len(pixels)==width*height*4,'Invalid PNG byte count')
    def chunk(kind,payload):
        return struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',binascii.crc32(kind+payload)&0xffffffff)
    rows=b''.join(b'\0'+pixels[y*width*4:(y+1)*width*4] for y in range(height))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>2I5B',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(rows,6))+chunk(b'IEND',b'')


def write_array(path,values):
    require(values.itemsize==4,'Scene contract requires four-byte elements')
    if sys.byteorder!='little':
        values.byteswap()
    with path.open('xb') as f:
        values.tofile(f)


def palette_effect_rgba(index,palette):
    """Reconstruct MAPn.SMG's authored E0 ramps before VGA quantization.

    STARTH CDBB4 indexes SMG[texture_byte * 256 + destination_index].
    The 64 original rows fade to white (0..31), black (32..47), or the
    track's gold color197 (48..63). The texture is an opacity mask, not COL.
    """
    require(0<=index<64,'Unrecognized original E0 palette-effect row')
    if index<32:color,alpha=(255,255,255),index/31
    elif index<48:color,alpha=(0,0,0),(index-32)/15
    else:color,alpha=palette[197],(index-48)/15
    return (*color,round(alpha*255))


def polygon_signature(part,polygon):
    """Compare authored surface coordinates, allowing extra night-only faces."""
    return (tuple((tuple(part['vertices'][i]),tuple(part['uv'][i])) for i in polygon['indices']),
            tuple(polygon['record_normal']))


class Scene:
    def __init__(self, game, track, output, phase=0, visual_track=None):
        self.track,self.output,self.phase=track,output,phase
        self.archive_name=f'GFX/MAP{track}H.DAT'
        raw,entries,read=archive(game/self.archive_name)
        require(sha(raw)==ARCHIVE_SHA[track],'Unrecognized original track archive hash')
        self.bank,self.grid,self.mlb,self.col=(read(f'MAP{track}.{ext}') for ext in ('UNR','MMP','MLB','COL'))
        smg=read(f'MAP{track}.SMG');require(len(smg)==64*256,'Invalid original palette-effect table')
        size,self.model_count=unpack(self.bank,'<2I',0)
        require(0<self.model_count<=4096,'Invalid model bank count')
        self.model_data=8+4*self.model_count
        require(self.model_data+size==len(self.bank),'Model bank size mismatch')
        self.model_bases=[self.model_data+u32(self.bank,8+4*i) for i in range(self.model_count)]
        require(len(self.col)==768 and max(self.col)<=63,'Unexpected original RGB666 palette')
        # DOSBox's rgb6_to_8() LUT formula, matching its VGA DAC output.
        self.palette=[tuple((v*259+33)>>6 for v in self.col[3*i:3*i+3]) for i in range(256)]
        self.materials={}
        for at in range(0,min(len(self.mlb),16384),16):
            kind,frames,w,h=unpack(self.mlb,'<4I',at)
            if not any((kind,frames,w,h)):
                break
            indices=[]
            if frames:
                count,word1=unpack(self.mlb,'<2I',frames)
                require(0<count<=1024 and 0<w<=256 and 0<h<=256,'Invalid material/frame extent')
                indices=list(unpack(self.mlb,'<'+str(count)+'I',frames+8))
                require(all(p+(h-1)*256+w<=len(self.mlb) for p in indices),'Texture crop exceeds original MLB')
            self.materials[at]={'offset':at,'type':kind,'width':w,'height':h,'frames':indices}
        else:
            raise ValueError('Unterminated material directory')
        self.models,self.parts,self.texture_ids={},{},{}
        self.textures,self.instances=[],[]
        self.vertices=array('f')
        self.normals=array('f')
        self.groups={}
        self.counts=Counter()
        self.unsupported=Counter()
        self.low,self.high=[math.inf]*3,[-math.inf]*3
        self.provenance={'original_executable_sha256':EXE_SHA,'archive':self.archive_name,
            'archive_sha256':sha(raw),'asset_sha256':{ext:sha(data) for ext,data in
                [('UNR',self.bank),('MMP',self.grid),('MLB',self.mlb),('COL',self.col)]},
            'source':'Original owned S1 assets, decoded offline; no game execution or generated geometry',
            'format_research':'S1/README.md and original STARTH.EXE disassembly',
            'convention_source':'https://github.com/Rick-Barber/ScreamerRally-Recomp',
            'source_license':'GPL-3.0-only',
            'palette_effects':{'original_smg_sha256':sha(smg),
                'original_kernel':'STARTH CDBB4 / CDCA7: SMG[texture_byte*256+destination_index]',
                'reconstruction':'E0 straight alpha reproduces white0..31/31, black32..47/15, gold48..63/15 ramps before original VGA palette quantization'}}
        self.visual_source=None;self.visual_parts={};self.visual_matches={}
        if visual_track is not None and visual_track!=track:
            require(track==1 and visual_track==4,'Only original Palm Town day/night assets are compatible')
            self.visual_source=Scene(game,visual_track,output,phase)
            # Cars are separate original 3DX models. Include their named parts
            # in the matching catalogue, without adding any geometry/actors.
            _,entries,read_visual=archive(game/self.visual_source.archive_name)
            source=self.visual_source
            for name in entries:
                if name.upper().endswith('.3DX'):
                    source.model_bases.append(len(source.bank));source.bank+=read_visual(name)
                    source.model_count+=1
            for index in range(source.model_count):
                model=source.model(index)
                for slot in range(model['parts']):
                    offsets=[model['levels'][level][slot] for level in range(3) if model['levels'][level][slot]]
                    if offsets:
                        part=source.part(model,offsets[0])
                        self.visual_parts.setdefault(part['name'],[]).append(part)
            self.provenance['visual_variant']={
                'original_track':visual_track,'archive_sha256':ARCHIVE_SHA[visual_track],
                'policy':'Original MAP1 geometry, grid, IDs and placements; compatible named MAP4 surfaces only',
                'palette_effects':'E0 straight alpha reconstructs original SMG ramps before palette quantization'}

    def surface(self,part,polygon):
        """Choose only an unambiguous original night material for this surface."""
        source=getattr(self,'visual_source',None)
        if source is None:return self,polygon
        key=id(part)
        if key not in self.visual_matches:
            candidates=self.visual_parts.get(part['name'],[]);mapping={}
            for original in part['polygons']:
                signature=polygon_signature(part,original);matches=[]
                for candidate in candidates:
                    matches.extend(p for p in candidate['polygons'] if polygon_signature(candidate,p)==signature)
                # Same-name geometry can recur at different LODs. An override
                # is safe only when every matching surface has the same art.
                values={(p['material'],p['color']) for p in matches}
                if len(values)==1:
                    match=matches[0]
                    old=self.materials.get(original['material']);new=source.materials.get(match['material'])
                    if old and new and old['type']==new['type']:
                        mapping[id(original)]=match
            self.visual_matches[key]=mapping
        match=self.visual_matches[key].get(id(polygon))
        if match is not None:
            self.counts['authored_night_polygons']+=1
            return source,match
        self.counts['unchanged_day_polygons']+=1
        return self,polygon

    def model(self,index):
        require(0<=index<self.model_count,'Invalid model reference')
        if index in self.models:
            return self.models[index]
        base=self.model_bases[index]
        count=u32(self.bank,base+0x14)
        require(0<count<=65,'Invalid model part count')
        result={'base':base,'parts':count,'animation_frames':unpack(self.bank,'<i',base+0x10)[0],
            'levels':[[u32(self.bank,base+0x18+0x104*level+4*slot) for slot in range(count)] for level in range(3)]}
        self.models[index]=result
        return result

    def part(self,model,offset):
        base=model['base']; at=base+offset
        if at in self.parts:
            return self.parts[at]
        vertex_at=base+u32(self.bank,at+0x1c)
        vertices=[]
        for i in range(8192):
            vertex=unpack(self.bank,'<3h',vertex_at+6*i)
            if vertex[0]==0x7fff:
                break
            vertices.append(vertex)
        else:
            raise ValueError('Unterminated vertex list')
        uv_offset=u32(self.bank,at+0x24)
        uv=[unpack(self.bank,'<3h',base+uv_offset+6*i)[:2] for i in range(len(vertices))] if uv_offset else [(0,0)]*len(vertices)
        part_flags=u32(self.bank,at+0x18)
        normal_offset=u32(self.bank,at+0x20)
        normals=[]
        if part_flags&0x2000:
            require(normal_offset not in (0,0xffffffff),'Missing original reflection normal table')
            normal_at=base+normal_offset
            normal_count=u32(self.bank,normal_at)
            require(0<normal_count<=len(vertices),'Invalid original normal table count')
            normals=[unpack(self.bank,'<3f',normal_at+4+12*i) for i in range(normal_count)]
        records=set()
        for j in range(16):
            order=u32(self.bank,at+0x28+4*j)
            if not order:
                continue
            for i in range(65536):
                value=unpack(self.bank,'<h',at+order+2*i)[0]
                if value<=0:
                    break
                records.add(at+value)
            else:
                raise ValueError('Unterminated polygon order')
        polygons=[]
        for record in sorted(records):
            color,material,count=unpack(self.bank,'<HhH',record+2)
            require(3<=count<=64,'Invalid polygon extent')
            indices=unpack(self.bank,'<'+str(count)+'H',record+8)
            require(all(v%6==0 and v//6<len(vertices) for v in indices),'Invalid polygon index')
            polygons.append({'color':color,'material':material,'indices':[v//6 for v in indices],
                'record_normal':unpack(self.bank,'<3i',record+0x14)})
        result={'vertices':vertices,'uv':uv,'normals':normals,'flags':part_flags,'polygons':polygons,
            'name':self.bank[at+0x68:at+0x78].split(b'\0')[0].decode('ascii',errors='replace')}
        self.parts[at]=result
        self.counts['unique_parts']+=1
        return result

    def placement(self,model,slot):
        require(model['levels'][0][slot]!=0,'Missing level-zero placement record')
        part=model['base']+model['levels'][0][slot]
        at=model['base']+u32(self.bank,part+0xc)
        if model['animation_frames']>=0:
            self.counts['frozen_animated_part_placements']+=1
            words=unpack(self.bank,'<12h',at+0x1c)
            return [[words[row+3*col]/16384 for col in range(3)] for row in range(3)],words[9:12]
        return rotation(unpack(self.bank,'<3i',at+4)),unpack(self.bank,'<3i',at+0x10)

    def texture(self,material,animation,reflection_phase=0,source=None):
        source=source or self
        frames=material['frames']
        if not frames:
            return None
        if material['type']==0xa0:
            # Original 8ADF7/DBBCA use the independent instance+3C phase.
            require(0<=reflection_phase<65536,'Invalid original reflection frame phase')
            index=(len(frames)*reflection_phase)>>16
        else:
            phase=self.phase if animation<0 else animation>>2
            index=max(0,min(len(frames)-1,(len(frames)*phase)>>14))
        pointer=frames[index];declared_w,declared_h=material['width'],material['height']
        # Original A0 setup DB630 unconditionally selects its256 fast path.
        # The raster reads two byte coordinates at source stride256, including
        # the authored border of the materials declared254-by-254.
        w,h=(256,256) if material['type']==0xa0 else (declared_w,declared_h)
        require(pointer+(h-1)*256+w<=len(source.mlb),'Original texture tile exceeds MLB')
        keyed=material['type']==0x40
        effect=material['type']==0xe0
        key=(source.track,pointer,w,h,keyed,effect)
        if key in self.texture_ids:
            return self.texture_ids[key]
        pixels=bytearray()
        for y in range(h):
            for color in source.mlb[pointer+256*y:pointer+256*y+w]:
                pixels.extend(palette_effect_rgba(color,source.palette) if effect else
                              (*source.palette[color],0 if keyed and color==0 else 255))
        encoded=png(w,h,bytes(pixels))
        ident=len(self.textures);path=f'textures/{ident:04d}.png'
        (self.output/path).write_bytes(encoded)
        self.textures.append({'path':path,'width':w,'height':h,'sha256':sha(encoded),
            'source':'MLB E0 SMG ramp mask, true-color reconstruction before palette quantization' if effect else 'MLB indexed8 + original COL RGB666',
            'source_track':source.track,'source_frame_offset':pointer,
            'source_row_stride':256,'source_declared_width':declared_w,'source_declared_height':declared_h,
            'alpha':'original SMG ramp strength' if effect else 'index0 keyed' if keyed else 'opaque','frame_index':index})
        if effect:
            # ImageIO/MTKTextureLoader premultiplies PNG RGB. Preserve the
            # original straight target color for the GPU's alpha blend pass.
            raw_path=f'textures/{ident:04d}.rgba'
            (self.output/raw_path).write_bytes(pixels)
            self.textures[-1].update(rgba_file=raw_path,rgba_sha256=sha(pixels))
        self.texture_ids[key]=ident
        return ident

    def objects(self):
        count=0
        for row in range(256):
            rp=u32(self.grid,row*4)
            if rp==0xffffffff:
                continue
            for col in range(256):
                cp=u32(self.grid,rp+col*4)
                if cp==0xffffffff:
                    continue
                self.counts['cells']+=1
                for listing in (0,1):
                    base,n=u32(self.grid,cp+4*listing),u32(self.grid,cp+0x14+4*listing)
                    require(n<=100000 and base+n*0x40<=len(self.grid),'Invalid cell list')
                    count+=n
                    require(count<=100000,'World object budget exceeded')
                    self.counts[f'objects_list_{listing}']+=n
                    for i in range(n):
                        at=base+0x40*i
                        yield {'id':f'cell:{row}:{col}:{listing}:{i}','cell':[row,col],'listing':listing,
                            'model':u32(self.grid,at),'flags':u32(self.grid,at+4),
                            'position':unpack(self.grid,'<3i',at+8),'angles':unpack(self.grid,'<3i',at+0x14),
                            'animation':unpack(self.grid,'<i',at+0x20)[0],
                            'reflection_phase':u32(self.grid,at+0x3c)}

    def add_object(self,obj):
        model=self.model(obj['model']); angles=obj['angles']
        if obj['flags']&0x8000:
            self.counts['frozen_billboard_instances']+=1
            angles=[angles[0]&2047,-(angles[1]+1024)&2047,2047]
        world_rotation=rotation(angles)
        instance={**obj,'position':list(obj['position']),'angles':list(obj['angles']),'part_names':[]}
        for slot in obj.get('slots',range(model['parts'])):
            available=[(level,model['levels'][level][slot]) for level in range(3) if model['levels'][level][slot]]
            if not available:
                continue
            level,offset=available[0];self.counts[f'parts_lod_{level}']+=1
            part=self.part(model,offset);instance['part_names'].append(part['name'])
            matrix,translation=self.placement(model,slot)
            vertices=[transform(world_rotation,obj['position'],transform(matrix,translation,v)) for v in part['vertices']]
            for polygon in part['polygons']:
                source,art=self.surface(part,polygon)
                material=source.materials.get(art['material'])
                require(material is not None,'Polygon names nonexistent S1 material')
                kind=material['type']
                if kind not in (0x10,0x40,0x80,0xa0,0xe0):
                    self.unsupported[f'{kind:#x}']+=len(polygon['indices'])-2
                    continue
                texture=self.texture(material,obj['animation'],obj.get('reflection_phase',0),source) if kind!=0x80 else None
                require(texture is not None or kind==0x80,'Missing texture for textured material')
                rgba=[v/255 for v in source.palette[art['color']&255]]+[1.] if kind==0x80 else [1.,1.,1.,1.]
                start=len(self.vertices)//9
                require(start+len(polygon['indices'])<=3000000,'Scene vertex budget exceeded')
                for i in polygon['indices']:
                    position=vertices[i]
                    require(all(math.isfinite(v) and abs(v)<10000000 for v in position),'Invalid transformed vertex')
                    # Original UV records are retained; raw/256 is the initial
                    # normalized mapping, pending an original-frame comparison.
                    self.vertices.extend(list(position)+[part['uv'][i][0]/256,part['uv'][i][1]/256]+rgba)
                    normal=[0.,0.,0.]
                    if kind==0xa0:
                        require(part['flags']&0x2000,'Original A0 part does not enable reflection texgen')
                        require(i<len(part['normals']),'Missing authored reflection vertex normal')
                        original=part['normals'][i]
                        length=sum(v*v for v in original)
                        require(all(math.isfinite(v) for v in original) and .99<length<1.01,
                                'Invalid authored reflection vertex normal')
                        # Same basis as exported vertex positions. DynamicScene
                        # supplies identity placement, retaining part-local data.
                        normal=transform(world_rotation,[0,0,0],transform(matrix,[0,0,0],original))
                    self.normals.extend(normal)
                    for axis in range(3):
                        self.low[axis]=min(self.low[axis],position[axis]);self.high[axis]=max(self.high[axis],position[axis])
                double_sided=polygon_double_sided(part['vertices'],polygon['indices'],polygon['record_normal'])
                self.counts['double_sided_polygons' if double_sided else 'single_sided_polygons']+=1
                if double_sided:self.counts['double_sided_triangles']+=len(polygon['indices'])-2
                group=(art['material'],texture,obj.get('dynamic_instance_id'),double_sided,source.track)
                indices=self.groups.setdefault(group,array('I'))
                for corner in range(1,len(polygon['indices'])-1):
                    indices.extend((start,start+corner,start+corner+1))
                self.counts[f'rendered_type_{kind:#x}_polygons']+=1
        self.instances.append(instance)
        self.counts['world_objects']+=1

    def export(self):
        self.output.mkdir()
        (self.output/'textures').mkdir()
        for obj in self.objects():
            self.add_object(obj)
        indices=array('I');batches=[]
        for (offset,texture,instance_id,double_sided,source_track),values in sorted(self.groups.items(),key=lambda p:(p[0][0],str(p[0][2]),p[0][3],p[0][4])):
            source=self.visual_source if source_track!=self.track else self
            kind=source.materials[offset]['type']
            batches.append({'first_index':len(indices),'index_count':len(values),'texture':texture,
                'alpha_test':kind==0x40,'blend':kind==0xe0,'source_material_offset':offset,'source_material_type':kind,
                'source_track':source_track,
                'double_sided':double_sided})
            if kind==0xe0:batches[-1]['blend_mode']='alpha'
            if kind==0xa0:
                material=source.materials[offset];count=len(material['frames'])
                frame_textures=[self.texture(material,0,(i*65536+count-1)//count,source) for i in range(count)]
                batches[-1].update(texgen='s1-reflection',reflection_scroll=[0.,0.],
                                  reflection_textures=frame_textures)
            if instance_id is not None:
                batches[-1]['instance_id']=instance_id
            indices.extend(values)
        require(indices and max(indices)<len(self.vertices)//9,'Invalid scene index buffers')
        require(len(self.normals)==len(self.vertices)//3,'Invalid parallel vertex normal count')
        write_array(self.output/'vertices.bin',self.vertices);write_array(self.output/'indices.bin',indices)
        write_array(self.output/'normals.bin',self.normals)
        scene={'schema':'screamer-scene/v1','title':f'Screamer (1995): original track {self.track}',
            'prototype':'Offline original static world in native Metal scene format; no game physics or playback',
            'provenance':self.provenance,'coordinates':{'handedness':'left','up':'+Y','units':'original game world units','vertices':'absolute world positions','winding':'original polygon order'},
            'vertices':{'file':'vertices.bin','count':len(self.vertices)//9,'stride':36,'format':'float32-le',
                'attributes':{'position':{'offset':0,'components':3},'uv':{'offset':12,'components':2},'rgba':{'offset':20,'components':4}}},
            'indices':{'file':'indices.bin','count':len(indices),'format':'uint32-le'},'batches':batches,'textures':self.textures,
            'normals':{'file':'normals.bin','count':len(self.normals)//3,'stride':12,'format':'float32-le','space':'vertex-local',
                'source':'Original counted float3 table at part+0x20; non-A0 vertex normals are zero'},
            'materials':list(self.materials.values()),'bounds':{'min':self.low,'max':self.high},'camera':None,'instances':self.instances,
            'statistics':{**dict(self.counts),'models_used':len(self.models),'vertices':len(self.vertices)//9,'triangles':len(indices)//3,
                'textures':len(self.textures),'unsupported_triangles_by_type':dict(self.unsupported)},
            'limitations':['Static world only; original simulation, cars, HUD, sky, input and audio not integrated.',
                'A0 opaque reflections retain original authored normals and256-stride environment tiles; renderer must implement s1-reflection texgen.',
                'E0 SMG fades are reconstructed before original palette quantization; C0 remains explicitly omitted.',
                'Texture animation and any animated part placements are frozen at one phase; billboard orientation is fixed.',
                'UV normalization raw/256, flat-polygon palette index and transform conventions need original-frame calibration.',
                'An orbit inspection camera is a host view of original geometry, not an original captured game camera.'],
            'files_sha256':{name:sha((self.output/name).read_bytes()) for name in ('vertices.bin','indices.bin','normals.bin')}}
        (self.output/'scene.json').write_text(json.dumps(scene,indent=2)+'\n')
        return scene


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--game-root',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--track',required=True,type=int,choices=range(1,7))
    p.add_argument('--phase',type=int,default=0)
    args=p.parse_args()
    require(0<=args.phase<16384,'Phase must be0..16383')
    require(sha((args.game_root/'STARTH.EXE').read_bytes())==EXE_SHA,'Unrecognized original STARTH.EXE')
    require(not args.output.exists(),'Refusing to overwrite an existing scene')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    staging=args.output.with_name('.'+args.output.name+'.extracting-'+uuid.uuid4().hex)
    try:
        scene=Scene(args.game_root,args.track,staging,args.phase).export()
        staging.rename(args.output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    print(json.dumps({'scene':str(args.output/'scene.json'),'statistics':scene['statistics'],'bounds':scene['bounds']},indent=2))


if __name__=='__main__':
    main()
