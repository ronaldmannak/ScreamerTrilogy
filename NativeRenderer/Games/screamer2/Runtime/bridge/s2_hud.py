"""Exact original S2 Voodoo write provenance; no color keys or HUD rectangles.

The rear view is the sole opaque crop: its original3D render is copied at its
verified viewport. All ordinary UI uses only actual LFB/needle-write alpha.
"""
from pathlib import Path
import os

WIDTH,HEIGHT=640,480
MIRROR=(161,34,320,84)
PROFILE='screamer2-3dfx-original'

class HudPublisher:
 def __init__(self,directory):self.directory=Path(directory);self.identity=None;self.latest=None
 def publish(self,data,metadata,phase,mirror_enabled=False,camera_mode=None):
  width,height,stride=(int(metadata[k])for k in('width','height','stride'))
  if (width,height,stride)!=(WIDTH,HEIGHT,WIDTH*4)or len(data)!=stride*height:raise ValueError('Invalid original S2 HUD buffer')
  known=metadata.get('coverage_profile')==PROFILE
  # Attract artwork/text uses LFB. Player race also uses the three guarded
  # original gauge needle lines; require the engine to have observed them.
  complete=known and (phase=='attract'or metadata.get('complete')is True)
  sequence=int(metadata['sequence']);mirror=bool(mirror_enabled and camera_mode!=1 and phase=='race')
  identity=(sequence,phase,mirror,complete)
  if identity==self.identity:return self.latest
  alpha=data[3::4]
  if alpha.replace(b'\0',b'').replace(b'\xff',b''):raise ValueError('S2 write coverage is not binary')
  if metadata.get('coverage_pixels',alpha.count(255))!=alpha.count(255):raise ValueError('Inconsistent S2 coverage count')
  self.directory.mkdir(parents=True,exist_ok=True)
  path=self.directory/f'hud-{sequence%4}.bgra';temp=path.with_name('.'+path.name+f'.{os.getpid()}.tmp');temp.write_bytes(data);os.replace(temp,path)
  layer=dict(path=str(path),format='bgra8',premultiplied=True,x=0,y=0,width=WIDTH,height=HEIGHT,stride=stride,anchor='center',sequence=sequence)
  rects=[]
  if mirror:
   x,y,w,h=MIRROR;rects=[dict(x=x,y=y,width=w,height=h,anchor='center')]
  result=dict(schema='screamer-hud/v2',complete=complete,primary_hud_validated=known,source_width=WIDTH,source_height=HEIGHT,layers=[layer],rects=rects,sequence=sequence,verified_empty=not any(alpha),provenance='Exact final original Voodoo LFB writes and original three guarded needle lines',validation_scope='Transparent HUD source; original rear-view3D pixels only in verified mirror viewport',missing=[]if complete else['Waiting for recognized S2 coverage and original needle primitives'])
  self.identity,self.latest=identity,result;return result
