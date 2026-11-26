# SPDX-License-Identifier: GPL-3.0-only
"""Verified original S1 indexed PCX sky and atomic sky-state contract."""
import hashlib,json,struct
from pathlib import Path
from archive_formats import archive,require
from export_scene import ARCHIVE_SHA,png
from s1_sky_source import decode_pcx,rgba_texture

LINKS={'pointer':0x1214e8,'ground':0x8a7bc,'view_last_y':0x8a7c4,'center_y':0x8a7dc,'pitch_sine_q14':0x824cc}


def export_sky(game_root,track,output):
    require(track in ARCHIVE_SHA,'Unknown original S1 sky track')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    name=f'GFX/MAP{track}H.DAT';raw,_,read=archive(Path(game_root)/name)
    require(hashlib.sha256(raw).hexdigest()==ARCHIVE_SHA[track],'Original S1 sky archive hash mismatch')
    pcx=read(f'MAP{track}.BCK');indices,_=decode_pcx(pcx);col=read(f'MAP{track}.COL')
    require(len(col)==768 and max(col)<=63,'Unknown original S1 sky RGB666 palette')
    palette=[[(v*259+33)>>6 for v in col[i:i+3]] for i in range(0,768,3)]
    width,height,pixels=rgba_texture(indices,col,padded=True)
    image=png(width,height,pixels);(output/'texture.png').write_bytes(image)
    result={'schema':'screamer1-sky/v1','track':track,'texture':'texture.png','width':width,'height':height,'source_width':512,'source_height':256,
        'source_s_bias':512,'source_s_span':320,'seam':'original-sequential-row-spill',
        'palette_rgb':palette,'archive':name,'entry':f'MAP{track}.BCK',
        'pcx_sha256':hashlib.sha256(pcx).hexdigest(),'indices_sha256':hashlib.sha256(indices).hexdigest(),
        'palette_sha256':hashlib.sha256(col).hexdigest(),'png_sha256':hashlib.sha256(image).hexdigest(),
        'source':'original-S1-PCX-and-MAP-COL'}
    (output/'sky.json').write_text(json.dumps(result,separators=(',',':'))+'\n')
    return result


def ranges(layout):return [(layout.link(link),4)for link in LINKS.values()]


def sky_state(layout,read,palette,phase):
    values={name:struct.unpack('<i'if name=='pitch_sine_q14'else'<I',read(layout.link(link),4))[0]for name,link in LINKS.items()}
    pointer=values['pointer'];ground=values['ground'];view=values['view_last_y'];center=values['center_y']
    valid=(phase in {'race','attract'} and 0x10000<=pointer<=16*1024*1024-512*256
           and 1<=view<=400 and 0<center<400 and -16384<=values['pitch_sine_q14']<=16384
           and ground==(ground&255)*0x01010101 and isinstance(palette,list) and len(palette)==256)
    color=palette[ground&255] if valid else [0,0,0]
    return {'kind':'s1','enabled':bool(valid),'ground_rgb':color,'flat_rgb':color,
        'center_y':center if 0<center<400 else 260,'view_last_y':view if 1<=view<=400 else 400,
        'original_view_last_y':view,'pitch_sine_q14':values['pitch_sine_q14'],
        'source':'original-S1-PCX-and-83ca8'}
