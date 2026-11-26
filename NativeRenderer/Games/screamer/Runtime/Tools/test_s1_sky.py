"""Original sky decoder and sparse atomic state checks; no game execution."""
import struct,unittest
from s1_sky import sky_state,LINKS
from s1_sky_source import sky_offset,rgba_texture,draw_reference
class Layout:
 def link(self,address):return address
class SkyStateTests(unittest.TestCase):
 def state(self,changes=None,phase='race'):
  values={'pointer':0x5d9064,'ground':0x18181818,'view_last_y':400,'center_y':260,'pitch_sine_q14':-503}
  values.update(changes or {});data={LINKS[k]:struct.pack('<I',v&0xffffffff) for k,v in values.items()}
  return sky_state(Layout(),lambda address,size:data[address],[[i,i,i] for i in range(256)],phase)
 def test_original_snapshot_fields_and_palette_ground(self):
  s=self.state();self.assertTrue(s['enabled']);self.assertEqual(s['kind'],'s1');self.assertEqual(s['center_y'],260)
  self.assertEqual(s['view_last_y'],400);self.assertEqual(s['ground_rgb'],[24,24,24]);self.assertEqual(sky_offset(-503,260),-213)
 def test_menus_and_invalid_original_fields_disable_sky(self):
  self.assertFalse(self.state(phase='menu')['enabled'])
  for change in ({'pointer':0},{'pointer':16*1024*1024},{'ground':0x01020304},{'view_last_y':401},
                 {'view_last_y':0},{'center_y':0},{'pitch_sine_q14':16385}):
   self.assertFalse(self.state(change)['enabled'])
 def test_disabled_state_has_explicit_clear_colour(self):
  s=self.state({'pointer':0});self.assertEqual(s['ground_rgb'],[0,0,0]);self.assertEqual(s['flat_rgb'],[0,0,0])
class TextureSeamTests(unittest.TestCase):
 def test_neighbor_rows_preserve_original_sequential_source_seam(self):
  indices=bytes(y%64 for y in range(256)for x in range(512));col=bytes(v%64 for v in range(768))
  width,height,rgba=rgba_texture(indices,col,padded=True)
  self.assertEqual((width,height),(1536,256))
  for heading in (0,1142,1660,2047):
   reference=draw_reference(indices,heading,-213,400,24)
   s0=((2047-heading)>>1)&511
   for x in (0,2,100,638):
    idx=reference[x];at=(106*1536+512+s0+x//2)*4
    expected=bytes([(v*259+33)>>6 for v in col[idx*3:idx*3+3]]+[255])
    self.assertEqual(rgba[at:at+4],expected)
if __name__=='__main__':unittest.main()
