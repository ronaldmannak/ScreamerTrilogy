# SPDX-License-Identifier: GPL-3.0-only
"""Visual-only original Screamer Palm Town night assets in a session cache.

Screamer shipped Palm Town Night as MAP4, with a different route and grid.
Using its complete world on MAP1 would move scenery away from the simulation.
Instead the exporter matches named, geometrically identical surfaces and swaps
only their original authored material/palette. Dynamic IDs and poses stay MAP1.

No original fog condition is verified: MENU/track DTR expose no fog option or
bank, and SMG blends texture-mask strength with the framebuffer, not depth.
"""
import json
from pathlib import Path
import shutil
import uuid

SCHEMA='screamer-original-conditions/v1'
FOG_UNAVAILABLE_REASON='No original fog condition or authored fog bank has been verified for Screamer.'


def build_variants(game_root,track,output,day_scene,cars_scene=None,*,ram=None,physical=None):
    """Return renderer descriptors, writing derived assets only under output.

    The caller supplies the captured immutable RAM used for its baseline cars.
    No emulator API, guest writes, simulation timers, or signed resources are
    accessed. Imports resolve from S1's Tools directory already on sys.path.
    """
    track=int(track)
    result={'schema':SCHEMA,'original':'night' if track==4 else 'day',
            'fog':{'available':False,'reason':FOG_UNAVAILABLE_REASON}}
    if track not in (1,4):
        result['night']={'available':False,'reason':
            'Original Screamer night artwork is verified only for Palm Town and Palm Town Night.'}
        return result
    if cars_scene is None:
        result['night']={'available':False,'reason':'Waiting for the original live actor snapshot.'}
        return result
    from export_scene import Scene
    from export_dynamic import DynamicScene
    from s1_sky import export_sky

    game_root=Path(game_root);output=Path(output).resolve()
    day_scene=Path(day_scene).resolve()
    if not day_scene.is_file():raise ValueError('Missing original baseline S1 world')
    if output.exists():
        # The background exporter builds the cache. The live publisher only
        # validates this small descriptor; it never exports meshes in its loop.
        cached=json.loads((output/'conditions.json').read_text())
        if cached.get('schema')!=SCHEMA or cached.get('original')!=result['original']:
            raise ValueError('Invalid cached original S1 conditions')
        night=cached.get('night',{})
        if night.get('available') and not all(key in night for key in ('world_scene','cars_scene','sky_texture')):
            raise ValueError('Incomplete cached original S1 condition descriptor')
        for key in ('world_scene','cars_scene','sky_texture'):
            if key in night and not Path(night[key]).is_file():
                raise ValueError('Incomplete cached original S1 conditions')
        # Older session caches predate original Fog capability metadata. Add
        # the verified availability in memory, without rewriting cached assets.
        cached['fog']=result['fog']
        return cached
    if cars_scene is not None and (ram is None or physical is None):
        # Avoid substituting static car meshes or original poses when a live
        # dynamic snapshot has not been supplied by the guarded bridge.
        raise ValueError('Original captured RAM mapping is required for night car materials')
    output.parent.mkdir(parents=True,exist_ok=True)
    staging=output.with_name('.'+output.name+'.exporting-'+uuid.uuid4().hex)
    staging.mkdir()
    try:
        world=Scene(game_root,track,staging/'world',visual_track=4).export()
        if track==1 and not world['statistics'].get('authored_night_polygons'):
            raise ValueError('No compatible original Palm Town night surfaces')
        if cars_scene is not None:
            DynamicScene(game_root,track,staging/'cars',ram,physical,visual_track=4).export()
        export_sky(game_root,4,staging/'sky')
        descriptor={'available':True,'world_scene':str(output/'world/scene.json'),
            'sky_texture':str(output/'sky/texture.png'),
            'sky':{'kind':'s1','enabled':True,'ground_rgb':[0,0,0],
                   'flat_rgb':[0,0,0],'center_y':260,'view_last_y':400},
            # S1's original night art has no proven generic fog switch. Keep
            # the shared night-fog stage explicitly disabled.
            'night_fog':{'enabled':False,'near':6000.,'far':35000.,'color':[0,0,0]},
            'source':'Original MAP4 authored sky, COL and compatible materials; original race geometry retained'}
        if cars_scene is not None:descriptor['cars_scene']=str(output/'cars/scene.json')
        result['night']=descriptor
        (staging/'conditions.json').write_text(json.dumps(result,indent=2)+'\n')
        staging.rename(output)
    except (OSError,ValueError) as error:
        # Missing or unsupported night artwork must not disable the otherwise
        # valid baseline native renderer. Publish the reason for its menu.
        if staging.exists():shutil.rmtree(staging)
        result['night']={'available':False,'reason':str(error)}
        staging.mkdir()
        (staging/'conditions.json').write_text(json.dumps(result,indent=2)+'\n')
        staging.rename(output)
    finally:
        if staging.exists():shutil.rmtree(staging)
    return result
