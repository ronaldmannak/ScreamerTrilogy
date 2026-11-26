#!/usr/bin/env python3
"""Assert actual AppKit/Metal fullscreen geometry from the native probe log."""
import argparse,hashlib,json,math
from pathlib import Path

def check(log,run,source=None,widescreen=True):
    rows=[json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    phases={row['stage']:row for row in rows};result=json.loads(run.read_text())
    assert result.get('exit_code')==0 and not result.get('timeout'),result
    expected={'windowed_settled':(False,True),'fullscreen_settled':(True,True),
              'fullscreen_window_resolution_checkpoint':(True,False),'exit_settled':(False,True)}
    summary=[]
    for stage,(fullscreen,mode4k) in expected.items():
        assert stage in phases,('Missing phase',stage)
        row=phases[stage];m=row['metrics'];back=row['view_backing_rect'];wanted=(round(back['width']),round(back['height']))
        assert row['actual_fullscreen_style']is fullscreen,(stage,'fullscreen state')
        assert row['view_class']=='PreviewView',(stage,'not actual production view')
        assert row['display_driver_class']=='MetalDisplayDriver',(stage,'not actual production driver')
        for key in ['view_drawable_size','layer_drawable_size']:
            actual=(round(row[key]['width']),round(row[key]['height']));assert actual==wanted,(stage,key,actual,wanted)
        supplied=(m['drawable_width'],m['drawable_height']);assert supplied==wanted,(stage,'supplied',supplied,wanted)
        assert row['status_label_exists'],(stage,'Production game-overlay branch is absent')
        assert row['status_label_hidden'],(stage,'Original status label did not hide')
        assert any(c['active'] for c in row['status_label_width_constraints']),(stage,'Status width constraints are not active')
        screen_width=row['screen_frame']['width'];assert screen_width>0,(stage,'Owning screen is unavailable')
        if fullscreen:
            for key in ['view_frame','view_bounds','window_content_layout_rect']:
                assert abs(row[key]['width']-screen_width)<=2,(stage,key,'Fullscreen content is narrower than owning screen',row[key]['width'],screen_width)
        ax,ay=(16,9)if widescreen else(4,3)
        units=max(1,min(wanted[0]//ax,wanted[1]//ay))
        window_target=(units*ax,units*ay)
        target=(m['render_width'],m['render_height']);assert target==(((3840 if widescreen else 2880),2160)if mode4k else window_target),(stage,'render target',target)
        assert m['widescreen_selected']is widescreen,(stage,'aspect option')
        assert m['render_4k_selected']is mode4k,(stage,'render mode')
        aspect=m['presented_scene_aspect_ratio'];assert math.isfinite(aspect)and abs(aspect-(target[0]/target[1]))<1e-4,(stage,'presentation aspect',aspect)
        assert m['gpu_errors']==0,(stage,'GPU errors',m['gpu_errors'])
        summary.append({'stage':stage,'fullscreen':fullscreen,'mode_4k':mode4k,'view_points':[row['view_bounds']['width'],row['view_bounds']['height']],
                        'backing_layer_supplied':wanted,'render_target':target,'presented_scene_aspect_ratio':aspect,'screen_width':screen_width,'fullscreen_width_occupancy':row['fullscreen_width_occupancy'],'status_label_hidden':row['status_label_hidden'],
                        'presented_frames':m['presented_frames'],'stale_drawable_drops':m.get('stale_drawable_drops',0)})
    final=phases['final'];assert final['did_enter_count']>=1 and final['did_exit_count']>=1,('No actual fullscreen enter/exit')
    assert not final['actual_fullscreen_style'],('Still fullscreen at end')
    assert final['metrics']['presented_frames']>0,('No actual presentations')
    assert all(row['metrics']['gpu_errors']==0 for row in rows),('GPU error in transition')
    value={'passed':True,'exit_code':0,'timeout':False,'wall_seconds':result.get('wall_seconds'),'actual_fullscreen_entered':True,'actual_fullscreen_exited':True,
           'phases':summary,'final_presented_frames':final['metrics']['presented_frames'],'gpu_errors':0,'scope':'Production frontend classes including real game-overlay UI with sentinel livePath and placeholder framebuffer; no live services, engine, game, physics or inputs.'}
    if source:value['production_source_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    return value

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--log',type=Path,required=True);p.add_argument('--run',type=Path,required=True);p.add_argument('--source',type=Path);p.add_argument('--output',type=Path);p.add_argument('--original-aspect',action='store_true')
    a=p.parse_args();value=check(a.log,a.run,a.source,widescreen=not a.original_aspect);text=json.dumps(value,indent=2)+'\n'
    if a.output:a.output.write_text(text)
    print(text,end='')
if __name__=='__main__':main()
