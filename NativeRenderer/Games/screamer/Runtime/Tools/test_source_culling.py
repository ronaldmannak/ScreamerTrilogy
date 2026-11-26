"""Source-normal culling exceptions; no game execution or external inputs."""
from array import array
from collections import Counter
from pathlib import Path
import tempfile,unittest
from export_scene import Scene,polygon_double_sided
class SourceCulling(unittest.TestCase):
 def test_conforming_quad_uses_one_sided_policy(self):
  self.assertFalse(polygon_double_sided([(0,0,0),(2,0,0),(2,2,0),(0,2,0)],[0,1,2,3],(0,0,-1)))
 def test_zero_and_nonfinite_source_normal_retain_two_sides(self):
  v=[(0,0,0),(2,0,0),(0,2,0)]
  for normal in [(0,0,0),(float('nan'),0,1),(float('inf'),0,1)]:
   self.assertTrue(polygon_double_sided(v,[0,1,2],normal))
 def test_any_wrong_fan_marks_whole_original_polygon(self):
  # First fan conforms, second fan opposes it: an authored concave quad.
  self.assertTrue(polygon_double_sided([(0,0,0),(4,0,0),(2,2,0),(4,1,0)],[0,1,2,3],(0,0,-1)))
 def test_zero_area_fan_does_not_force_otherwise_valid_face_two_sided(self):
  self.assertFalse(polygon_double_sided([(0,0,0),(1,0,0),(2,0,0),(0,1,0)],[0,1,2,3],(0,0,-1)))
 def test_reversed_source_fan_retains_previous_two_sided_rendering(self):
  self.assertTrue(polygon_double_sided([(0,0,0),(1,0,0),(0,1,0)],[0,2,1],(0,0,-1)))
 def test_same_material_splits_batches_without_rewinding_or_remeshing(self):
  class Fixture(Scene):
   def __init__(self,path):
    self.output=path;self.track=1;self.counts=Counter();self.unsupported=Counter();self.vertices=array('f');self.normals=array('f');self.groups={};self.instances=[];self.models={0:{'parts':1,'levels':[[1],[0],[0]]}};self.materials={0:{'type':0x80}};self.palette=[(255,255,255)]*256;self.textures=[];self.low=[float('inf')]*3;self.high=[-float('inf')]*3;self.provenance={}
   def objects(self):return iter([dict(id='fixture',model=0,flags=0,position=[0,0,0],angles=[0,0,0],animation=0)])
   def model(self,index):return self.models[index]
   def placement(self,*unused):return [[1,0,0],[0,1,0],[0,0,1]],[0,0,0]
   def part(self,*unused):return {'name':'fixture','vertices':[(0,0,0),(1,0,0),(0,1,0)],'uv':[(0,0)]*3,'polygons':[dict(material=0,color=0,indices=[0,1,2],record_normal=(0,0,-1)),dict(material=0,color=0,indices=[0,1,2],record_normal=(0,0,0))]}
  with tempfile.TemporaryDirectory()as folder:
   scene=Fixture(Path(folder)/'scene').export();self.assertEqual([b['double_sided']for b in scene['batches']],[False,True]);self.assertEqual(scene['vertices']['stride'],36);self.assertEqual(scene['vertices']['count'],6);self.assertEqual(scene['indices']['count'],6);self.assertEqual(scene['statistics']['double_sided_polygons'],1)
if __name__=='__main__':unittest.main(verbosity=2)
