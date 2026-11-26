import math,struct,tempfile,unittest
from pathlib import Path
from sky_assets import bck_rgb565,rgba565,archive_entry
from sky_state import mapping,from_proper_rotation,rgb565

class SkyTests(unittest.TestCase):
    def test_bck_keeps_original_low_word(self):
        pixels=[0xf800,0x07e0,0x001f,0xffff]*16384
        source=b''.join(struct.pack('<HH',v,i&65535)for i,v in enumerate(pixels))
        self.assertEqual(bck_rgb565(source),struct.pack('<65536H',*pixels))
        self.assertEqual(rgba565(bck_rgb565(source)[:8]),bytes((255,0,0,255,0,255,0,255,0,0,255,255,255,255,255,255)))
    def test_invalid_bck_and_archive_rejected(self):
        with self.assertRaises(ValueError):bck_rgb565(bytes(131072))
        with tempfile.TemporaryDirectory()as d:
            p=Path(d)/'bad.dat';p.write_bytes(bytes(40))
            with self.assertRaises(ValueError):archive_entry(p,'MAP30.BCK')
    def test_reference_horizon_and_wide_uv(self):
        plain=mapping(0,0,aspect=4/3);wide=mapping(0,0,aspect=16/9)
        self.assertAlmostEqual(plain['horizon_y'],361.2)
        self.assertEqual(plain['t_texels'],[105,255])
        self.assertAlmostEqual(wide['s_texels'][0],plain['s_texels'][0]-26.5)
        self.assertAlmostEqual(wide['s_texels'][1],plain['s_texels'][1]+26.5)
    def test_sky_period_and_constant_colour(self):
        self.assertEqual(mapping(.1,5),mapping(.1,1029))
        self.assertEqual(rgb565(0x4288),[64,80,64])
    def test_interpolated_rotation_matches_angle_mapping(self):
        for pitch in (-100,-1,0,1,100):
            for heading in (0,8,512,1024,2040):
                a,b=pitch*math.tau/2048,heading*math.tau/2048
                # Rc^T, roll0; only the finalrowisneeded bysky.
                r=[0,0,0,0,0,0,-math.cos(a)*math.sin(b),-math.sin(a),math.cos(a)*math.cos(b)]
                x=from_proper_rotation(r);y=mapping(math.sin(a),heading)
                for key in ('horizon_y',):self.assertAlmostEqual(x[key],y[key],places=8)
                for a,b in zip(x['s_texels'],y['s_texels']):self.assertAlmostEqual((a-b)%256,0,places=8)
    def test_nonfinite_mapping_rejected(self):
        with self.assertRaises(ValueError):mapping(math.nan,0)
if __name__=='__main__':unittest.main()
