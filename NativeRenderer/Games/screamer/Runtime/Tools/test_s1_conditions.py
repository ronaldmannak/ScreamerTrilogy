"""Original night artwork contracts; synthetic data, no emulator or inputs."""
from collections import Counter
import copy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

from export_scene import Scene,palette_effect_rgba
sys.path.insert(0,str(Path(__file__).resolve().parents[4]))
from Conditions.s1 import build_variants,SCHEMA


class OriginalEffects(unittest.TestCase):
    def test_e0_is_opacity_not_palette_color(self):
        palette=[(2,3,4)]*256;palette[197]=(255,202,40)
        self.assertEqual(palette_effect_rgba(0,palette),(255,255,255,0))
        self.assertEqual(palette_effect_rgba(31,palette),(255,255,255,255))
        self.assertEqual(palette_effect_rgba(32,palette),(0,0,0,0))
        self.assertEqual(palette_effect_rgba(41,palette),(0,0,0,153))
        self.assertEqual(palette_effect_rgba(47,palette),(0,0,0,255))
        self.assertEqual(palette_effect_rgba(48,palette),(255,202,40,0))
        self.assertEqual(palette_effect_rgba(63,palette),(255,202,40,255))
        with self.assertRaises(ValueError):palette_effect_rgba(64,palette)

    def test_effect_sidecar_preserves_straight_rgb_even_at_zero_alpha(self):
        with tempfile.TemporaryDirectory() as folder:
            scene=Scene.__new__(Scene);scene.output=Path(folder)
            (scene.output/'textures').mkdir();scene.track=1;scene.phase=0
            scene.mlb=bytes([0,31,32,41]);scene.palette=[(2,3,4)]*256
            scene.texture_ids={};scene.textures=[]
            material={'type':0xe0,'frames':[0],'width':4,'height':1}
            self.assertEqual(scene.texture(material,-1),0)
            entry=scene.textures[0]
            self.assertEqual((scene.output/entry['rgba_file']).read_bytes(),
                             bytes([255,255,255,0,255,255,255,255,0,0,0,0,0,0,0,153]))
            self.assertEqual((entry['width'],entry['height']),(4,1))

    def part(self):
        return {'name':'original-building','vertices':[(0,0,0),(8,0,0),(0,8,0)],
            'uv':[(0,0),(255,0),(0,255)],
            'polygons':[{'indices':[0,1,2],'record_normal':(0,0,-1),'material':0,'color':1}]}

    def scene(self,candidates):
        scene=Scene.__new__(Scene)
        scene.materials={0:{'type':0x10}}
        scene.visual_source=types.SimpleNamespace(materials={16:{'type':0x10},32:{'type':0x10}})
        scene.visual_parts={'original-building':candidates};scene.visual_matches={};scene.counts=Counter()
        return scene

    def test_extra_night_faces_never_replace_day_geometry(self):
        day=self.part();before=copy.deepcopy(day);night=copy.deepcopy(day)
        night['vertices'].append((0,0,8));night['uv'].append((255,255))
        night['polygons'][0]['material']=16
        night['polygons'].append(dict(night['polygons'][0],indices=[0,1,3]))
        scene=self.scene([night]);source,art=scene.surface(day,day['polygons'][0])
        self.assertIs(source,scene.visual_source);self.assertEqual(art['material'],16)
        self.assertEqual(day,before)

    def test_incompatible_uv_keeps_original_day_surface(self):
        day=self.part();night=copy.deepcopy(day);night['polygons'][0]['material']=16;night['uv'][1]=(128,0)
        scene=self.scene([night]);source,art=scene.surface(day,day['polygons'][0])
        self.assertIs(source,scene);self.assertIs(art,day['polygons'][0])

    def test_ambiguous_named_art_is_not_guessed(self):
        day=self.part();a=copy.deepcopy(day);b=copy.deepcopy(day)
        a['polygons'][0]['material']=16;b['polygons'][0]['material']=32
        scene=self.scene([a,b]);self.assertIs(scene.surface(day,day['polygons'][0])[0],scene)

    def test_other_tracks_report_unavailable_without_generating_files(self):
        for track in (2,3,5,6):
            value=build_variants('/missing',track,'/missing','/missing','/missing')
            self.assertEqual(value['schema'],SCHEMA);self.assertEqual(value['original'],'day')
            self.assertFalse(value['night']['available'])

    def test_original_night_cache_is_only_read_by_live_publisher(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);world=root/'world.json';world.write_text('{}')
            cars=root/'cars.json';cars.write_text('{}');sky=root/'sky.png';sky.write_bytes(b'fixture')
            cache=root/'cache';cache.mkdir()
            descriptor={'schema':SCHEMA,'original':'night','night':{'available':True,
                'world_scene':str(world),'cars_scene':str(cars),'sky_texture':str(sky)}}
            (cache/'conditions.json').write_text(json.dumps(descriptor))
            # No RAM, physical mapping, game files or exporters are needed to
            # read already-completed work from the child asset process.
            self.assertEqual(build_variants('/missing',4,cache,world,cars),descriptor)
            sky.unlink()
            with self.assertRaises(ValueError):build_variants('/missing',4,cache,world,cars)

    def test_missing_night_assets_preserve_baseline_and_cache_unavailable(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);world=root/'world.json';world.write_text('{}')
            cars=root/'cars.json';cars.write_text('{}');cache=root/'cache'
            value=build_variants(root/'missing-game',1,cache,world,cars,ram=b'',physical=lambda n:n)
            self.assertFalse(value['night']['available']);self.assertTrue(value['night']['reason'])
            self.assertEqual(world.read_text(),'{}');self.assertEqual(cars.read_text(),'{}')
            self.assertEqual(build_variants('/missing',1,cache,world,cars),value)


if __name__=='__main__':unittest.main(verbosity=2)
