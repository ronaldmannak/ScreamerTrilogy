# SPDX-License-Identifier: GPL-3.0-only
"""Read-only original S1 PCX sky extraction and 83ca8 reference compositor."""
import hashlib, json, struct
from pathlib import Path


def decode_pcx(data):
    if len(data)<897 or data[:4]!=bytes((10,5,1,8)):
        raise ValueError('Expected original one-plane indexed PCX sky')
    x0,y0,x1,y1=struct.unpack_from('<4H',data,4)
    w,h=x1-x0+1,y1-y0+1
    planes=data[65];pitch=struct.unpack_from('<H',data,66)[0]
    if (x0,y0,w,h,planes,pitch)!=(0,0,512,256,1,512) or data[-769]!=12:
        raise ValueError('Unexpected original sky extent/palette')
    out=bytearray();pos=128;end=len(data)-769
    while len(out)<pitch*h:
        if pos>=end:raise ValueError('Truncated PCX image')
        value=data[pos];pos+=1
        if value>=192:
            count=value&63
            if pos>=end:raise ValueError('Truncated PCX run')
            value=data[pos];pos+=1
        else:count=1
        if len(out)+count>pitch*h:raise ValueError('PCX output overflow')
        out.extend(bytes((value,))*count)
    if pos!=end:raise ValueError('Unexpected trailing PCX image bytes')
    return bytes(out),data[-768:]


def draw_reference(indices,heading,top_offset,view_last_y,ground_index):
    """Exact 640-wide indexed software sky loop at link83ca8 (no world/HUD).

    top_offset is original signed link83f10, computed by sky code from pitch.
    This preserves its sequential seam reads and duplicated scanlines.
    """
    if len(indices)!=512*256 or not 0<=view_last_y<=400 or not 0<=ground_index<256:
        raise ValueError('Invalid original software sky input')
    heading_texel=((2047-heading)>>1)&511
    rows=512;skip=top_offset
    if top_offset<0:rows+=top_offset;skip=-top_offset
    source=(skip>>1)*512+heading_texel
    beyond=top_offset+512-view_last_y
    if beyond>0:rows-=beyond
    rows=max(0,rows>>1)
    output=bytearray()
    for _ in range(rows):
        row=indices[source:source+320]
        if len(row)!=320:raise ValueError('Sky source seam read exceeds original image')
        doubled=b''.join(bytes((i,i))for i in row)
        output.extend(doubled);output.extend(doubled)
        source+=512
    # Original fills through view_last_y+1 (inclusive) after the sky.
    size=(view_last_y+2)*640
    if len(output)>size:raise ValueError('Sky output exceeds original view')
    output.extend(bytes((ground_index,))*(size-len(output)))
    return bytes(output)


def sky_offset(pitch_sine_q14,center_y):
    # 83ca9..83cd3: 32-bit IMUL low word, SAR7, signed division toward0.
    product=(-54152*pitch_sine_q14)&0xffffffff
    product=product-(1<<32)if product&(1<<31)else product
    shifted=product>>7
    pitch=int(shifted/-54152)
    return pitch+center_y+40-512+2


def rgba_texture(indices, rgb666, padded=True):
    """Original source colors; optional neighboring rows preserve 83ca8 seam.

    Padded sourceS is512+S0 (source span remains320), divided by1536.
    SourceT is unchanged, divided by256. The spare extreme rows clamp only
    outside the supported primary-view source footprint.
    """
    if len(indices)!=512*256 or len(rgb666)!=768 or max(rgb666)>63:
        raise ValueError('Invalid original indexed sky/palette')
    palette=[bytes(tuple((v*259+33)>>6 for v in rgb666[i:i+3])+(255,))
             for i in range(0,768,3)]
    rows=[]
    for y in range(256):
        neighbors=[max(0,y-1),y,min(255,y+1)]if padded else[y]
        row=b''.join(indices[q*512:(q+1)*512]for q in neighbors)
        rows.append(b''.join(palette[index]for index in row))
    return (1536 if padded else 512),256,b''.join(rows)
