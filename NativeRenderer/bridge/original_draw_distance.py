# SPDX-License-Identifier: GPL-3.0-only
"""Read original axial world far distance from a coherent guest snapshot.

These are game-specific LE link addresses, not host or raw EXE offsets. Each
original setter writes -D and +D as a neighboring pair; accept only a supported
executable, a bounded positive depth, and an exact matching signed pair.
"""
import struct

PROFILES={
 'screamer':{'sha256':'1246afc95463f96598d5fee764fc99c847b6d3e0bf8ca2268bd362c664bb28a3',
             'negative':0xd7cf0,'positive':0xd7cf4,'setter':0x8bd54},
 'screamer2':{'sha256':'e6c24c84650938f2baee5f4b571baa45bb09a93ba12dd24e3e1d2cefd9b6f3ec',
              'negative':0xd1190,'positive':0xd1194,'setter':0x849d4},
 'screamerrally':{'sha256':'9eac6e12ab309389bdda019cfa695bfbbc791fbda1a4634464a444fce35165d1',
                  'negative':0xcf470,'positive':0xcf474,'setter':0x82fa4},
}


def ranges(layout,game):
    p=PROFILES[game]
    if layout.metadata.get('executable_sha256')!=p['sha256']:return []
    return [(layout.link(p['negative'],8),8)]


def distance(layout,data,game):
    wanted=ranges(layout,game)
    if not wanted:return None
    address,size=wanted[0]
    for start,raw in data.items():
        offset=address-start
        if 0<=offset<=len(raw)-size:
            negative,positive=struct.unpack_from('<2i',raw,offset)
            return positive if 8192<=positive<=262144 and negative==-positive else None
    return None


def attach_camera(camera,value):
    if camera is not None and value is not None:
        camera['original_draw_distance']=value
        camera['original_far_plane']=value+128
    return camera
