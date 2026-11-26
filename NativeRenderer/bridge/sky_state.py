# SPDX-License-Identifier: GPL-3.0-only
"""Original Rally sky state and continuous reference mapping.

Port of Rick's frame::sky / prepare::sky_quads contract. Input is camera angles
in2048units/turn or the interpolated proper Rc^T rotation, not reflected viewR.
"""
import math,struct
LINKS={'enabled':0x123740,'flat_fill':0x123744,'ground':0x81e1c}


def rgb565(value):
    # Original constant-colour expansion, intentionally bitshift ratherthanreplicate.
    return [((value>>11)&31)<<3,((value>>5)&63)<<2,(value&31)<<3]

def ranges(layout):return [(layout.link(link,4),4)for link in LINKS.values()]

def state(layout,data):
    values={name:struct.unpack('<I',data[layout.link(link,4)])[0]for name,link in LINKS.items()}
    return {'enabled':bool(values['enabled']),'ground_rgb':rgb565(values['ground']),'flat_rgb':rgb565(values['flat_fill']),
            'source':'original-Rally-sky-flags-and-colours'}


def mapping(pitch_sine,heading_units,center_y=260,grid_height=400,pixel_scale_y=1.2,aspect=16/9):
    if not all(math.isfinite(v)for v in (pitch_sine,heading_units,center_y,grid_height,pixel_scale_y,aspect)) or aspect<=0:
        raise ValueError('Nonfinite/invalid sky mapping')
    s0=((2047-heading_units)%1024)*.25
    h=128*pitch_sine+center_y-470
    raw_bottom=511-abs(h);last=grid_height-1
    te=max(0.,(raw_bottom-last)*.5);bottom=min(raw_bottom,last)
    extension=159*(aspect/(640/(grid_height*pixel_scale_y))-1)*.5
    return {'s_texels':[s0-extension,s0+159+extension], 't_texels':[abs(h)*.5,255-te],
            'horizon_y':bottom*pixel_scale_y,'reference_height':grid_height*pixel_scale_y,'ground_visible':bottom<last}


def from_proper_rotation(row_major,**kwargs):
    if len(row_major)!=9:raise ValueError('Rotation requires9elements')
    pitch_sine=-row_major[7]
    heading=math.atan2(-row_major[6],row_major[8])*2048/math.tau
    return mapping(pitch_sine,heading,**kwargs)
