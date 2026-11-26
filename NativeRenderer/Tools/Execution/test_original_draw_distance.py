"""Bounded source-profile and signed depth-pair tests; no emulator or inputs."""
import struct,unittest
from original_draw_distance import PROFILES,ranges,distance,attach_camera
class Layout:
 def __init__(self,game):self.metadata={'executable_sha256':PROFILES[game]['sha256']}
 def link(self,address,size=1):return address+0x200000
class DistanceTests(unittest.TestCase):
 def test_each_profile_reads_exact_neighboring_signed_pair(self):
  for game,p in PROFILES.items():
   layout=Layout(game);address=layout.link(p['negative']);self.assertEqual(ranges(layout,game),[(address,8)])
   self.assertEqual(distance(layout,{address:struct.pack('<2i',-50000,50000)},game),50000)
 def test_coalesced_atomic_range_preserves_field_read(self):
  layout=Layout('screamer');address=layout.link(PROFILES['screamer']['negative'])
  self.assertEqual(distance(layout,{address-16:b'\0'*16+struct.pack('<2i',-43808,43808)+b'\0'*16},'screamer'),43808)
 def test_changing_or_uninitialized_depth_pair_is_not_published(self):
  layout=Layout('screamer2');address=layout.link(PROFILES['screamer2']['negative'])
  for a,b in ((0,0),(-50000,40000),(50000,50000),(-8191,8191),(-262145,262145)):
   self.assertIsNone(distance(layout,{address:struct.pack('<2i',a,b)},'screamer2'))
 def test_wrong_executable_profile_cannot_use_another_game_addresses(self):
  layout=Layout('screamer');self.assertEqual(ranges(layout,'screamer2'),[])
  self.assertIsNone(distance(layout,{},'screamer2'))
 def test_camera_far_plane_accounts_for_existing128_eye_offset(self):
  camera={'projection':{'near':128}};attach_camera(camera,50000)
  self.assertEqual(camera['original_far_plane'],50128);self.assertEqual(camera['original_draw_distance'],50000)
  self.assertEqual(camera['projection']['near'],128)
 def test_missing_pair_remains_optional(self):
  layout=Layout('screamerrally');self.assertIsNone(distance(layout,{},'screamerrally'))
  self.assertIsNone(attach_camera(None,50000))
if __name__=='__main__':unittest.main()
