"""Graphics-policy/transport regressions; no sockets, emulator, or game inputs."""
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock,patch
from native_graphics_policy import GraphicsPolicy,frontend_heartbeat,exact_hud_ready,BOOTSTRAP_NS
from s1_native_client import S1NativeGraphics
from live_s1 import Bridge

N=10_000_000_000

def assets(epoch='track1-a'):return {'epoch':epoch,'world_scene':'/world.json','cars_scene':'/cars.json'}
def pose(now=N,mode=2):return {'status':'race','sample_monotonic_ns':now,'camera':{'rotation':[]},'original_hud_mode':mode}
def frontend(native=False):return {'native_render_requested':True,'native_assets_ready':True,'native_renderer_ready':native}
def hud(now=N,epoch='track1-a',mode=2):
    return {'path':'/hud.bgra','width':640,'height':480,'stride':2560,'capture_ns':now,'assets_epoch':epoch,
            'original_hud_mode':mode,'coverage':'original-ram-byte-writes','sequence':7}

class PolicyTests(unittest.TestCase):
    def args(self,**kw):
        value={'now':N,'pose':pose(),'assets':assets(),'assets_since':N-1,'hud':None,'frontend':frontend()};value.update(kw);return value
    def test_bootstrap_requires_current_assets_loaded_by_fresh_frontend(self):
        p=GraphicsPolicy()
        for changes in ({'assets':None},{'pose':None},{'pose':pose(N-150_000_001)},{'frontend':None},
                        {'frontend':dict(frontend(),native_assets_ready=False)},
                        {'frontend':dict(frontend(),native_render_requested=False)},{'pose':pose(mode=1)}):
            self.assertFalse(p.decide(**self.args(**changes))['ready'])
        self.assertEqual(p.decide(**self.args())['phase'],'bootstrap')
    def test_bootstrap_is_one_bounded_window_per_asset_view(self):
        p=GraphicsPolicy();first=p.decide(**self.args())
        self.assertTrue(first['ready']);self.assertFalse(first['renew'])
        second=p.decide(**self.args(now=N+100_000_000,pose=pose(N+100_000_000)))
        self.assertEqual(second['phase'],'bootstrap');self.assertFalse(second['renew'])
        expired=p.decide(**self.args(now=N+BOOTSTRAP_NS,pose=pose(N+BOOTSTRAP_NS)))
        self.assertFalse(expired['ready'])
        self.assertFalse(p.decide(**self.args(now=N+BOOTSTRAP_NS+1,pose=pose(N+BOOTSTRAP_NS+1)))['ready'])
    def test_native_requires_matching_exact_hud_and_actual_native_rendering(self):
        p=GraphicsPolicy();p.decide(**self.args())
        ready=p.decide(**self.args(hud=hud(),frontend=frontend(True)))
        self.assertEqual(ready['phase'],'native');self.assertTrue(ready['renew'])
    def test_hud_alone_does_not_extend_bootstrap_without_frontend_native_frame(self):
        p=GraphicsPolicy();p.decide(**self.args())
        later=N+BOOTSTRAP_NS
        self.assertFalse(p.decide(**self.args(now=later,pose=pose(later),hud=hud(later)))['ready'])
    def test_original_view_stale_pose_or_disconnect_immediately_disables_native(self):
        p=GraphicsPolicy()
        self.assertTrue(p.decide(**self.args(hud=hud(),frontend=frontend(True)))['ready'])
        for changes in ({'frontend':None},{'frontend':dict(frontend(True),native_render_requested=False)},
                        {'pose':pose(N-150_000_001)},{'stopped':True}):
            kwargs=self.args(hud=hud(),frontend=frontend(True));kwargs.update(changes)
            self.assertFalse(p.decide(**kwargs)['ready'])
    def test_native_success_consumes_bootstrap_and_later_stale_hud_fails_closed(self):
        p=GraphicsPolicy();p.decide(**self.args())
        self.assertEqual(p.decide(**self.args(hud=hud(),frontend=frontend(True)))['phase'],'native')
        later=N+251_000_000
        self.assertFalse(p.decide(**self.args(now=later,pose=pose(later),hud=hud(),frontend=frontend(True)))['ready'])
    def test_interrupted_bootstrap_cannot_restart_on_frontend_reconnect(self):
        p=GraphicsPolicy();p.decide(**self.args())
        self.assertFalse(p.decide(**self.args(frontend=None))['ready'])
        self.assertFalse(p.decide(**self.args())['ready'])
    def test_old_scene_or_mode_hud_cannot_enable_native(self):
        for h in (hud(epoch='old'),hud(mode=1),hud(N-250_000_001),hud(N+1)):
            self.assertFalse(exact_hud_ready(h,2,'track1-a',N-1,N))
        self.assertFalse(exact_hud_ready(hud(),2,'track1-a',N+1,N))
    def test_new_asset_epoch_gets_new_bootstrap_but_cannot_reuse_old_hud(self):
        p=GraphicsPolicy();p.decide(**self.args());later=N+BOOTSTRAP_NS
        result=p.decide(**self.args(now=later,pose=pose(later),assets=assets('new'),hud=hud(later),frontend=frontend(True)))
        self.assertEqual(result['phase'],'bootstrap')

class HeartbeatTests(unittest.TestCase):
    def test_strict_current_epoch_asset_timestamp_and_booleans(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'input.json'
            valid={'schema':'screamer-input/v1','epoch':'session-a','seq':4,'published_monotonic_ns':N,
                   'native_assets_epoch':'track1-a',**frontend()}
            path.write_text(json.dumps(valid));self.assertIsNotNone(frontend_heartbeat(path,'session-a','track1-a',N))
            for change in ({'epoch':'old'},{'native_assets_epoch':'old'},{'published_monotonic_ns':N-300_000_001},
                           {'published_monotonic_ns':N+50_000_001},{'native_renderer_ready':'true'},
                           {'seq':True},{'published_monotonic_ns':True}):
                path.write_text(json.dumps(dict(valid,**change)))
                self.assertIsNone(frontend_heartbeat(path,'session-a','track1-a',N))
    def test_missing_oversized_and_malformed_heartbeat_disable_renderer(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'input.json'
            for value in (None,'{broken','x'*65537):
                if value is not None:path.write_text(value)
                self.assertIsNone(frontend_heartbeat(path,'a','b',N))

class TransportTests(unittest.TestCase):
    def test_exact_bgra_requires_provenance_and_bounded_dimensions(self):
        api=Mock();raw=bytes(640*480*4)
        headers={'X-S1-Hud-Width':'640','X-S1-Hud-Height':'480','X-S1-Hud-Sequence':'7',
                 'X-S1-Hud-Capture-Ns':str(N),'X-S1-Hud-Mode':'2','X-S1-Hud-Coverage':'original-ram-byte-writes'}
        api.request.return_value=(raw,headers);client=S1NativeGraphics(api)
        data,meta=client.hud();self.assertEqual(data,raw);self.assertEqual(meta['original_hud_mode'],2)
        headers['X-S1-Hud-Coverage']='color-key'
        with self.assertRaises(ValueError):client.hud()
    def test_false_transition_is_sent_immediately_not_rate_limited(self):
        api=Mock();api.request.return_value=(json.dumps({'profile_sha256':__import__('s1_native_client').EXE_SHA256,'installed':True}).encode(),{})
        client=S1NativeGraphics(api);client.installed=True
        client.control(True);client.heartbeat(False)
        self.assertEqual(api.request.call_count,2)
        self.assertFalse(api.request.call_args.args[2]['renderer_ready'])

class BridgeStateTests(unittest.TestCase):
    def bridge(self):
        args=types.SimpleNamespace(base_url='http://127.0.0.1:9099',input=Path('/unused/input.json'),diagnostic_read_only=True,parent_pid=None)
        b=Bridge(args);b.pose=pose();b.assets=assets();b.assets_since=N-1;b.graphics.installed=True
        b.frame={'path':'/original.bgra','format':'bgra8','width':640,'height':480,'stride':2560,'sequence':7}
        return b
    def test_exact_hud_is_separate_alpha_layer_original_framebuffer_preserved(self):
        b=self.bridge();b.exact_hud=hud()
        with patch('live_s1.now_ns',return_value=N):state=b.state()
        self.assertEqual(state['mode'],'race');self.assertTrue(state['hud']['complete'])
        layer=state['hud']['layers'][0];self.assertEqual(layer['format'],'bgra8');self.assertTrue(layer['premultiplied'])
        self.assertEqual(layer['anchor'],'center');self.assertEqual(state['framebuffer']['path'],'/original.bgra')
        self.assertEqual(state['hud']['rects'],[])
    def test_stale_exact_hud_loses_completeness_no_rectangular_fallback(self):
        b=self.bridge();b.exact_hud=hud(N-250_000_001)
        with patch('live_s1.now_ns',return_value=N):state=b.state()
        self.assertFalse(state['hud']['complete']);self.assertEqual(state['hud']['layers'],[]);self.assertEqual(state['hud']['rects'],[])
    def test_initial_sky_payload_has_strict_rgb_vectors_even_before_pose(self):
        b=self.bridge();b.pose=None;b.assets=None
        with patch('live_s1.now_ns',return_value=N):state=b.state()
        self.assertFalse(state['sky']['enabled'])
        self.assertEqual(state['sky']['ground_rgb'],[0,0,0]);self.assertEqual(state['sky']['flat_rgb'],[0,0,0])
    def test_unsupported_view_keeps_original_framebuffer(self):
        b=self.bridge();b.pose=pose(mode=1);b.exact_hud=hud(mode=1)
        with patch('live_s1.now_ns',return_value=N):state=b.state()
        self.assertEqual(state['mode'],'framebuffer')

if __name__=='__main__':unittest.main()
