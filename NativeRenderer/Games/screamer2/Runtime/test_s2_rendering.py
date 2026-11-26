"""S2 original-source contracts, without launching or controlling the game."""
import sys,tempfile,unittest
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).parent
sys.path.insert(0,str(HERE/'bridge'if(HERE/'bridge').is_dir()else HERE/'Runtime/bridge'))
from s2_hud import HudPublisher
from s2_overlay_api import paired_display
from s2_sky_assets import bck_rgb565,rgba565
class SourceContracts(unittest.TestCase):
 def meta(self,**extra):return dict(width=640,height=480,stride=2560,sequence=7,coverage_profile='screamer2-3dfx-original',complete=False,**extra)
 def publish(self,metadata,phase='attract',mirror=False,mode=0):
  raw=bytearray(640*480*4);raw[4*100:4*100+4]=bytes([9,8,7,255])
  with tempfile.TemporaryDirectory()as root:
   hud=HudPublisher(root).publish(bytes(raw),metadata,phase,mirror,mode);pixels=Path(hud['layers'][0]['path']).read_bytes();return hud,pixels
 def test_attract_uses_exact_alpha_and_source_colors(self):
  hud,pixels=self.publish(self.meta());self.assertTrue(hud['complete']);self.assertEqual(pixels[400:404],bytes([9,8,7,255]));self.assertEqual(pixels[:400],bytes(400));self.assertEqual(hud['rects'],[])
 def test_race_waits_for_observed_guarded_needles(self):
  hud,_=self.publish(self.meta(),'race');self.assertFalse(hud['complete']);meta=self.meta();meta['complete']=True;hud,_=self.publish(meta,'race');self.assertTrue(hud['complete'])
 def test_unknown_engine_profile_never_claims_complete(self):
  meta=self.meta();meta['coverage_profile']='none';meta['complete']=True;hud,_=self.publish(meta);self.assertFalse(hud['complete']);self.assertFalse(hud['primary_hud_validated'])
 def test_mirror_is_only_opaque_crop_and_has_verified_viewport(self):
  hud,_=self.publish(self.meta(),'race',True,0);self.assertEqual(hud['rects'],[dict(x=161,y=34,width=320,height=84,anchor='center')]);hud,_=self.publish(self.meta(),'race',True,1);self.assertEqual(hud['rects'],[])
 def test_invalid_nonbinary_write_coverage_rejected(self):
  raw=bytearray(640*480*4);raw[3]=127
  with tempfile.TemporaryDirectory()as root:
   with self.assertRaises(ValueError):HudPublisher(root).publish(bytes(raw),self.meta(),'attract')
 def test_pair_api_retains_identical_display_sequence_and_profile(self):
  frame=bytes([11,22,33,255])*(640*480);overlay=bytes(len(frame));headers={'x-rally-width':'640','x-rally-height':'480','x-rally-pitch':'2560','x-rally-sequence':'29','x-rally-overlay-offset':str(len(frame)),'x-rally-overlay-size':str(len(overlay)),'x-rally-overlay-format':'bgra8-premultiplied','x-rally-coverage-profile':'screamer2-3dfx-original','x-rally-hud-complete':'1','x-rally-needle-primitives':'3'}
  class API:
   def request(self,*args,**kwargs):return frame+overlay,headers
  a,b,c,d=paired_display(API());self.assertEqual(a,frame);self.assertEqual(c,overlay);self.assertEqual(b['sequence'],d['sequence']);self.assertEqual(d['coverage_profile'],'screamer2-3dfx-original');self.assertTrue(d['complete']);self.assertEqual(d['needle_primitives'],3)
 def test_pair_rejects_truncated_overlay(self):
  class API:
   def request(self,*args,**kwargs):return b'',{'x-rally-width':'640','x-rally-height':'480','x-rally-pitch':'2560','x-rally-sequence':'29','x-rally-overlay-offset':'1228800','x-rally-overlay-size':'1228800'}
  with self.assertRaises(ValueError):paired_display(API())
 def test_original_bck_low_words_and_rgb565_primary_colors(self):
  words=(b'\0\xf8\xaa\xbb'+b'\xe0\x07\xcc\xdd')*(256*128);texels=bck_rgb565(words);self.assertEqual(texels[:4],b'\0\xf8\xe0\x07');self.assertEqual(rgba565(texels[:4]),bytes([255,0,0,255,0,255,0,255]))
if __name__=='__main__':unittest.main(verbosity=2)
