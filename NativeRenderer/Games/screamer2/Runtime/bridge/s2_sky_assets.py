#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Recover the original Screamer2 backdrop from the owned DAT archive, never freed RAM.

DAT/LZW and sky contracts follow Rick-Barber/ScreamerRally-Recomp. BCK is
65,536 little-endian dwords; the game uploads their low RGB565 words. Runtime
TMU byte comparison can independently validate the original loader conversion.
"""
import argparse,binascii,hashlib,json,struct,zlib
from pathlib import Path

EXE_SHA256='e6c24c84650938f2baee5f4b571baa45bb09a93ba12dd24e3e1d2cefd9b6f3ec'
MAX_ASSET_BYTES=16*1024*1024


def require(condition,message):
    if not condition:raise ValueError(message)

def u32(raw,offset):
    require(0<=offset<=len(raw)-4,'DAT dword outside file')
    return struct.unpack_from('<I',raw,offset)[0]

def sha(raw):return hashlib.sha256(raw).hexdigest()

def lzw(packed,expected):
    require(0<expected<=MAX_ASSET_BYTES,'DAT asset extent exceeds bound')
    output=bytearray();previous=None;bits=0;width=9
    table=[bytes([n])for n in range(256)]+[None,None]
    while len(output)<expected:
        require(bits+width<=len(packed)*8,'Truncated DAT LZW')
        offset=bits//8;code=(int.from_bytes(packed[offset:offset+3],'little')>>(bits%8))&((1<<width)-1);bits+=width
        if code==256:
            table=[bytes([n])for n in range(256)]+[None,None];width=9;previous=None;continue
        if code==257:break
        if code<len(table):
            word=table[code];require(word is not None,'Reserved DAT LZW code')
        else:
            require(code==len(table)and previous is not None,'Undefined DAT LZW code');word=previous+previous[:1]
        output.extend(word);require(len(output)<=expected,'DAT LZW overflow')
        if previous is not None and len(table)<4096:
            table.append(previous+word[:1])
            if len(table)==1<<width and width<12:width+=1
        previous=word
    require(len(output)==expected,'DAT LZW output size differs')
    return bytes(output)

def archive_entry(path,name):
    raw=Path(path).read_bytes();require(4<=len(raw)<=128*1024*1024,'Unsupported DAT size')
    directory_size=u32(raw,len(raw)-4);require(directory_size%32==0 and directory_size<=len(raw)-4,'Invalid DAT directory')
    directory=len(raw)-directory_size-4;match=None
    for at in range(directory,len(raw)-4,32):
        entry=bytes(v^0x3a for v in raw[at:at+16]).split(b'\0')[0]
        if not entry:break
        start,packed,size,flags=struct.unpack_from('<4I',raw,at+16)
        require(start+packed<=directory and size<=MAX_ASSET_BYTES,'DAT asset overlaps directory/exceeds bound')
        if entry.decode('ascii')==name:
            require(match is None,'Duplicate DAT sky entry');match=(start,packed,size,flags)
    require(match is not None,'Original sky is absent for this track/condition')
    start,packed,size,flags=match;payload=raw[start:start+packed]
    decoded=lzw(payload,size)if flags&2 else payload
    require(len(decoded)==size,'Original DAT entry size differs')
    return decoded,{'archive_sha256':sha(raw),'entry':name,'entry_sha256':sha(decoded),'entry_bytes':len(decoded)}

def bck_rgb565(raw):
    require(len(raw)==256*256*4,'S2 BCK must contain256x256dwords')
    return b''.join(raw[at:at+2]for at in range(0,len(raw),4))

def rgba565(raw):
    require(len(raw)%2==0,'Truncated RGB565')
    result=bytearray()
    for c, in struct.iter_unpack('<H',raw):
        r=(c>>11)&31;g=(c>>5)&63;b=c&31
        result.extend(((r<<3)|(r>>2),(g<<2)|(g>>4),(b<<3)|(b>>2),255))
    return bytes(result)

def png_rgba(width,height,raw):
    require(len(raw)==width*height*4,'RGBA extent differs')
    def chunk(kind,payload):return struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',binascii.crc32(kind+payload)&0xffffffff)
    rows=b''.join(b'\0'+raw[y*width*4:(y+1)*width*4]for y in range(height))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>2I5B',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(rows,6))+chunk(b'IEND',b'')

def export_sky(game_root,track_id,condition,output):
    require(type(track_id)is int and 0<=track_id<=6,'Unknown S2 track index')
    require(type(condition)is int and 0<=condition<=2,'Unknown original condition')
    game_root=Path(game_root);output=Path(output)
    require(sha((game_root/'S2_3DFX.EXE').read_bytes())==EXE_SHA256,'Original S2 executable profile differs')
    archive=f'GFX/MAP{track_id+1}H{condition&1}2.DAT';entry=f'MAP{track_id+1}.BCK'
    original,provenance=archive_entry(game_root/archive,entry);texels=bck_rgb565(original)
    encoded=png_rgba(256,256,rgba565(texels));relative=f'textures/sky-{track_id}-{condition&1}.png';target=output/relative
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():require(target.read_bytes()==encoded,'Refusing to replace a different sky asset')
    else:target.write_bytes(encoded)
    return {'path':relative,'width':256,'height':256,'format':'rgb565','address_mode':'repeat','filter':'linear',
        'sha256':sha(encoded),'source_texel_sha256':sha(texels),'source':'original-owned-S2-DAT-BCK-low16',
        'track_id':track_id,'condition':condition,'night_bit':condition&1,'archive':archive,**provenance}

def export_capture_sky(memory,game_root,output):
    return export_sky(game_root,memory.rd32(memory.link(0x151684,4)),memory.rd32(memory.link(0x151688,4)),output)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--game-root',type=Path,required=True)
    p.add_argument('--track-id',type=int,required=True);p.add_argument('--condition',type=int,default=0);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();descriptor=export_sky(a.game_root,a.track_id,a.condition,a.output)
    print(json.dumps(descriptor,indent=2))
if __name__=='__main__':main()
