"""Production S1 state publisher regression; no emulator, network or inputs."""
from pathlib import Path
import json,types,unittest
from unittest.mock import patch
from live_s1 import Bridge,now_ns

class OriginalS1CullPublication(unittest.TestCase):
    def bridge(self):
        args=types.SimpleNamespace(base_url='http://127.0.0.1:9',input=Path('/nonexistent/s1-sign-cull-input.json'),diagnostic_read_only=True,parent_pid=None)
        bridge=Bridge(args);stamp=now_ns()
        bridge.graphics.installed=True
        bridge.assets={'epoch':'original-s1-assets','world_scene':'/owned/scene.json','cars_scene':'/owned/cars.json'}
        bridge.assets_since=stamp-1
        bridge.pose={'status':'race','sample_monotonic_ns':stamp,'original_hud_mode':2,
                     'camera':{'position':[0,0,128]},'instances':[]}
        bridge.exact_hud={'capture_ns':stamp,'assets_epoch':'original-s1-assets','original_hud_mode':2,
                          'coverage':'original-ram-byte-writes','width':640,'height':480,'stride':2560,
                          'sequence':1,'path':'/owned/hud.bgra'}
        return bridge

    @patch('live_s1.LiveAPI.request',side_effect=AssertionError('No emulator request permitted'))
    def test_native_race_publishes_original_backface_rule(self,request):
        bridge=self.bridge();state=json.loads(json.dumps(bridge.state()))
        self.assertEqual(state['schema'],'screamer-live/v1')
        self.assertEqual(state['mode'],'race');self.assertTrue(state['assets_ready']);self.assertTrue(state['hud']['complete'])
        self.assertIs(state.get('cull_back_faces'),True)
        request.assert_not_called()

    @patch('live_s1.LiveAPI.request',side_effect=AssertionError('No emulator request permitted'))
    def test_culling_does_not_bypass_unsupported_view_fallback(self,request):
        bridge=self.bridge();bridge.pose['original_hud_mode']=1;state=bridge.state()
        self.assertEqual(state['mode'],'framebuffer');self.assertFalse(state['hud']['complete'])
        self.assertIs(state.get('cull_back_faces'),True)
        request.assert_not_called()

    @patch('live_s1.LiveAPI.request',side_effect=AssertionError('No emulator request permitted'))
    def test_culling_does_not_bypass_stale_pose_fallback(self,request):
        bridge=self.bridge();bridge.pose['sample_monotonic_ns']=now_ns()-1_000_000_000;state=bridge.state()
        self.assertEqual(state['mode'],'framebuffer');self.assertFalse(state['assets_ready']);self.assertIsNone(state['assets'])
        self.assertIs(state.get('cull_back_faces'),True)
        request.assert_not_called()

if __name__=='__main__':unittest.main()
