import tempfile
import unittest
from pathlib import Path
from hud_layers import HudPublisher,split_overlay,mirror_rectangle


def image(points):
    data=bytearray(640*480*4)
    for x,y,bgra in points:data[(y*640+x)*4:(y*640+x+1)*4]=bytes(bgra)
    return bytes(data)


def recover(layers):
    result=bytearray(640*480*4);coverage=set()
    for layer in layers:
        w=layer['width'];raw=layer['pixels']
        for y in range(layer['height']):
            for x in range(w):
                at=(y*w+x)*4
                if not raw[at+3]:continue
                point=(layer['x']+x,layer['y']+y)
                if point in coverage:raise AssertionError('Duplicate alpha source pixel')
                coverage.add(point)
                dest=(point[1]*640+point[0])*4;result[dest:dest+4]=raw[at:at+4]
    return bytes(result),coverage


class ExactCoverage(unittest.TestCase):
    def test_source_pixels_survive_once_with_no_world_background(self):
        raw=image([(20,10,(34,56,78,255)),(600,20,(13,26,39,255)),(600,430,(7,210,7,255)),(300,20,(255,0,10,255))])
        layers,info=split_overlay(raw)
        rebuilt,coverage=recover(layers)
        self.assertEqual(rebuilt,raw);self.assertEqual(len(coverage),4)
        self.assertEqual({v['anchor'] for v in layers},{'left','right','center'})
        self.assertEqual(info['anchor_policy'],'verified-edge-regions')
    def test_unknown_center_message_uses_one_unchanged_transform(self):
        raw=image([(20,10,(0,20,70,255)),(100,250,(4,5,6,255)),(600,430,(10,20,30,255))])
        layers,info=split_overlay(raw)
        self.assertEqual([v['anchor'] for v in layers],['center'])
        self.assertEqual(recover(layers)[0],raw);self.assertEqual(info['unmapped_pixels'],1)
    def test_conflicting_progress_mirror_pixels_do_not_duplicate(self):
        raw=image([(350,30,(100,200,30,255)),(600,50,(40,50,60,255))])
        layers,info=split_overlay(raw,mirror_enabled=True,camera_mode=0)
        self.assertEqual(info['anchor_policy'],'center-safe-area')
        self.assertEqual(recover(layers)[0],raw)
    def test_wrong_dimensions_and_partial_buffers_are_rejected(self):
        for w,h,data in [(640,480,b''),(1280,720,bytes(1280*720*4))]:
            with self.assertRaises(ValueError):split_overlay(data,w,h)
    def test_full_width_band_stretches_without_reanchoring_other_elements(self):
        points=[(x,479,(0,0,0,255)) for x in range(640)]+[(20,10,(2,3,4,255)),(600,430,(7,8,9,255))]
        raw=image(points);layers,info=split_overlay(raw)
        self.assertEqual({l['anchor'] for l in layers},{'left','right','stretch'})
        self.assertEqual(recover(layers)[0],raw)
        self.assertEqual(info['anchor_policy'],'verified-edge-regions')
    def test_empty_verified_mask_can_be_published_without_fake_rectangle(self):
        layers,info=split_overlay(bytes(640*480*4))
        self.assertEqual(layers,[]);self.assertEqual(info['coverage_pixels'],0)
    def test_incomplete_engine_capability_does_not_claim_complete_hud(self):
        with tempfile.TemporaryDirectory() as d:
            p=HudPublisher(d);raw=image([(600,430,(1,2,3,255))]);m=dict(width=640,height=480,stride=2560,sequence=4)
            self.assertFalse(p.publish(raw,m)['complete'])
    def test_mirror_uses_only_exact_verified_viewport(self):
        self.assertEqual(mirror_rectangle(True,0),[dict(x=322,y=28,width=318,height=84,anchor='right')])
        self.assertEqual(mirror_rectangle(False,0),[]);self.assertEqual(mirror_rectangle(True,1),[])
    def test_publisher_uses_complete_files_and_identity(self):
        with tempfile.TemporaryDirectory() as d:
            p=HudPublisher(d);raw=image([(600,430,(1,2,3,255))]);m=dict(width=640,height=480,stride=2560,sequence=4,complete=True)
            j=p.publish(raw,m);self.assertIs(j,p.publish(raw,m))
            layer=j['layers'][0];self.assertEqual(Path(layer['path']).read_bytes(),bytes((1,2,3,255)))
            self.assertTrue(j['complete']);self.assertTrue(layer['premultiplied']);self.assertEqual(j['rects'],[])


if __name__=='__main__':unittest.main()

from overlay_api import paired_display
class PairedAPI(unittest.TestCase):
    def api(self,headers=None,body=None):
        size=640*480*4
        h={'X-Rally-Width':'640','X-Rally-Height':'480','X-Rally-Pitch':'2560','X-Rally-Sequence':'7',
           'X-Rally-Overlay-Offset':str(size),'X-Rally-Overlay-Size':str(size),'X-Rally-Overlay-Format':'bgra8-premultiplied'}
        h.update(headers or {})
        class API:
            def request(self,*args,**kwargs):return body if body is not None else bytes(size*2),h
        return API()
    def test_coherent_pair_has_one_sequence_for_frame_and_alpha(self):
        frame,f,overlay,o=paired_display(self.api());self.assertEqual(len(frame),len(overlay));self.assertEqual(f['sequence'],o['sequence'])
    def test_pair_size_or_format_mismatch_is_rejected(self):
        for api in [self.api(body=b'1'),self.api({'X-Rally-Overlay-Format':'rgb565'}),self.api({'X-Rally-Overlay-Offset':'5'})]:
            with self.assertRaises(ValueError):paired_display(api)
