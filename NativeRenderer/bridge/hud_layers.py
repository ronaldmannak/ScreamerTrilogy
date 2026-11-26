"""Exact original LFB coverage -> premultiplied transparent native HUD layers.

No color key, inpainting, generated glyphs, or framebuffer rectangles are used
for ordinary HUD. An optional original mirror view is the only opaque crop.
"""
from pathlib import Path
import os
from functools import lru_cache

WIDTH, HEIGHT = 640, 480
# These are source-pixel placement bounds already verified against the original
# game. They affect anchoring only: alpha always comes from actual LFB writes.
REGIONS = (
    (8, 4, 100, 82, 'left'),
    (450, 0, 190, 86, 'right'),
    (212, 10, 216, 26, 'center'),
    (12, 132, 100, 80, 'left'),
    (538, 132, 102, 80, 'right'),
    (469, 320, 171, 160, 'right'),
)
MIRROR = (322, 28, 318, 84)


def mirror_rectangle(enabled, camera_mode, anchor='right'):
    """Original ViewMap::mirror: .5*x+322, 1.2*y+28, grid height70."""
    if not enabled or camera_mode == 1:
        return []
    x,y,w,h = MIRROR
    return [dict(x=x,y=y,width=w,height=h,anchor=anchor)]


def _row_runs(alpha):
    """Exact binary alpha spans; C-level searches avoid per-screen-pixel loops."""
    if alpha.replace(b'\0',b'').replace(b'\xff',b''):
        raise ValueError('The original LFB coverage mask must use binary alpha')
    start=0
    while start < len(alpha):
        start=alpha.find(b'\xff',start)
        if start<0:break
        end=alpha.find(b'\0',start)
        if end<0:end=len(alpha)
        yield start,end
        start=end


@lru_cache(maxsize=2)
def _ownership_rows(mirror):
    regions=list(REGIONS)+([(*MIRROR,'right')] if mirror else [])
    rows=[]
    for y in range(HEIGHT):
        active=[v for v in regions if v[1]<=y<v[1]+v[3]]
        edges=sorted({0,WIDTH,*[v[0] for v in active],*[v[0]+v[2] for v in active]})
        segments=[]
        for x0,x1 in zip(edges,edges[1:]):
            choices={v[4] for v in active if v[0]<=x0<v[0]+v[2]}
            segments.append((x0,x1,next(iter(choices)) if len(choices)==1 else None,len(choices)))
        rows.append(tuple(segments))
    return tuple(rows)


def split_overlay(data,width=WIDTH,height=HEIGHT,stride=None,edge_anchors=True,
                  mirror_enabled=False,camera_mode=None):
    """Return disjoint cropped BGRA layers and an honest anchoring policy.

    Unknown or overlapping ownership keeps the entire alpha layer in the
    original centred safe area. It never keys the world or discards UI pixels.
    Keeping one original transform is preferable to splitting unknown messages.
    """
    stride=stride or width*4
    if (width,height)!=(WIDTH,HEIGHT) or stride<width*4 or stride>65536 or len(data)!=stride*height:
        raise ValueError('Rally overlay must be a complete 640x480 BGRA buffer')
    ownership=_ownership_rows(bool(mirror_enabled and camera_mode!=1))
    spans=[];unknown=conflicts=0;pixels=0
    for y in range(height):
        row=data[y*stride:y*stride+width*4]
        alpha=row[3::4]
        for x0,x1 in _row_runs(alpha):
            pixels+=x1-x0
            # Original full-width LFB bands follow Rick's stretch anchor=2.
            # They are geometry/coverage classifications, never a color key.
            if x0==0 and x1==width:
                spans.append((y,x0,x1,'stretch'));continue
            for left,right,choice,count in ownership[y]:
                start,end=max(x0,left),min(x1,right)
                if start>=end:continue
                if not count:unknown+=end-start
                elif count>1:conflicts+=end-start
                spans.append((y,start,end,choice or 'center'))
    center_all=(not edge_anchors or bool(unknown or conflicts))
    groups={}
    for y,x0,x1,anchor in spans:
        anchor='center' if center_all and anchor!='stretch' else anchor
        groups.setdefault(anchor,[]).append((y,x0,x1))
    layers=[]
    for anchor,runs in sorted(groups.items()):
        x=min(v[1] for v in runs);right=max(v[2] for v in runs)
        y=min(v[0] for v in runs);bottom=max(v[0] for v in runs)+1
        w,h=right-x,bottom-y;output=bytearray(w*h*4)
        for row,x0,x1 in runs:
            src=row*stride+x0*4;dest=((row-y)*w+x0-x)*4
            output[dest:dest+(x1-x0)*4]=data[src:src+(x1-x0)*4]
        layers.append(dict(x=x,y=y,width=w,height=h,stride=w*4,format='bgra8',
                           anchor=anchor,premultiplied=True,pixels=bytes(output)))
    return layers,dict(coverage_pixels=pixels,unmapped_pixels=unknown,
        conflicting_anchor_pixels=conflicts,anchor_policy='center-safe-area' if center_all else 'verified-edge-regions')


class HudPublisher:
    """Publish complete ring-buffer files before the state refers to them."""
    def __init__(self,directory):
        self.directory=Path(directory);self.sequence=None;self.last=None

    def publish(self,data,metadata,mirror_enabled=False,camera_mode=None,edge_anchors=True):
        sequence=int(metadata['sequence'])
        complete=metadata.get('complete') is True
        identity=(sequence,bool(mirror_enabled),camera_mode,bool(edge_anchors),complete)
        if identity==self.sequence:return self.last
        width,height,stride=(int(metadata[k]) for k in ('width','height','stride'))
        layers,analysis=split_overlay(data,width,height,stride,edge_anchors,mirror_enabled,camera_mode)
        self.directory.mkdir(parents=True,exist_ok=True)
        result=[]
        for layer in layers:
            value=dict(layer);pixels=value.pop('pixels')
            path=self.directory/f"hud-{value['anchor']}-{sequence%4}.bgra"
            temp=path.with_name('.'+path.name+f'.{os.getpid()}.tmp')
            temp.write_bytes(pixels);os.replace(temp,path)
            value['path']=str(path);value['sequence']=sequence;result.append(value)
        mirror_anchor='center' if analysis['anchor_policy']=='center-safe-area' else 'right'
        hud=dict(schema='screamer-hud/v2',complete=complete,source_width=width,source_height=height,
            format='bgra8-premultiplied',sequence=sequence,layers=result,
            rects=mirror_rectangle(mirror_enabled,camera_mode,mirror_anchor),
            verified_empty=not result,provenance='exact Voodoo LFB write coverage; final original framebuffer colors',
            analysis=analysis)
        self.sequence,self.last=identity,hud
        return hud
