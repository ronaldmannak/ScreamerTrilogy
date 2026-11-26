"""Synthetic bridge safety tests: no emulator, network, keys or user files."""
import base64
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from guest_memory import SnapshotError
from input_lease import InputLease,KeyboardOutput,canonical
from live_api import LiveAPI,NotReady
from live_bridge import Layout,PoseFeed,Session,atomic_json
from clock_shared import now_ns


def metadata():
    return {"executable_sha256":"9eac6e12ab309389bdda019cfa695bfbbc791fbda1a4634464a444fce35165d1",
            "physical_ram_base":0,"ram_size":16777216,"pointer_bias":0,
            "objects":[{"index":2,"link_base":0x20000,"physical_base":0x1E1000,"virtual_size":0xCEDC0},
                       {"index":6,"link_base":0x120000,"physical_base":0x2B0000,"virtual_size":0x77B10}]}


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix="rally-live-tests-")
        self.path=Path(self.directory.name)/"input.json"
        self.lease=InputLease(self.path,"test")
        self.seq=0
    def tearDown(self):self.directory.cleanup()
    def write(self,keys=(),counts=None,focused=True,epoch="test"):
        self.seq+=1
        atomic_json(self.path,{"schema":"screamer-input/v1","epoch":epoch,"seq":self.seq,
                              "focused":focused,"pressed_keys":list(keys),"press_counts":counts or {}})
    def test_fast_released_tap_survives_until_minimum_pulse(self):
        self.write(counts={"enter":1})
        self.assertEqual(self.lease.desired(100),{"enter"})
        self.assertEqual(self.lease.desired(100.05),{"enter"})
        self.assertEqual(self.lease.desired(100.09),set())
    def test_held_key_stale_lease_releases(self):
        self.write(["up"])
        self.assertEqual(self.lease.desired(100),{"up"})
        self.assertEqual(self.lease.desired(100.51),set())
    def test_focus_loss_cancels_held_and_latched_keys(self):
        self.write(["up"],{"enter":1});self.lease.desired(100)
        self.write(focused=False)
        self.assertEqual(self.lease.desired(100.01),set())
    def test_old_bridge_epoch_is_rejected(self):
        self.write(["up"],epoch="previous-process")
        self.assertEqual(self.lease.desired(100),set())
        self.assertIn("epoch",self.lease.error)
    def test_unknown_key_is_rejected_without_partial_input(self):
        self.write(["up","nonexistent"])
        self.assertEqual(self.lease.desired(100),set())
    def test_aliases_and_function_keys_are_canonical(self):
        self.assertEqual(canonical("return"),"enter")
        self.assertEqual(canonical("ctrl"),"lctrl")
        self.assertEqual(canonical("F12"),"f12")


class LayoutTests(unittest.TestCase):
    def test_real_profile_maps_code_and_data(self):
        m=Layout(metadata())
        self.assertEqual(m.link(0x504DC),0x2114DC)
        self.assertEqual(m.to_link(0x2114DC),0x504DC)
    def test_mode_flags_and_race_state_are_distinct_verified_addresses(self):
        from live_bridge import LINK
        self.assertEqual(LINK['flags'],0x1436DC)
        self.assertEqual(LINK['race_state'],0x13146C)
    def test_overlapping_or_outside_ram_maps_rejected(self):
        for field,value in [("physical_base",0x1E1100),("physical_base",0xFFFFFF),("link_base",0x30000)]:
            m=metadata();m["objects"][1][field]=value
            with self.subTest(field=field,value=value),self.assertRaises(SnapshotError):Layout(m)
    def test_wrong_source_profile_and_bias_rejected(self):
        for values in [{"executable_sha256":"0"*64},{"pointer_bias":1}]:
            m=metadata();m.update(values)
            with self.assertRaises(SnapshotError):Layout(m)


class FakeKeys:
    native_keys=True
    def __init__(self):self.calls=[]
    def keys(self,keys):self.calls.append(set(keys))


class KeyboardTests(unittest.TestCase):
    def test_release_once_then_stop_forcing_zero_state(self):
        api=FakeKeys();output=KeyboardOutput(api,None)
        with patch("input_lease.time.monotonic",return_value=100):
            output.send({"up"});output.send(set());output.send(set());output.send(set())
        self.assertEqual(api.calls,[{"up"},set()])
    def test_held_state_renews_engine_watchdog_lease(self):
        api=FakeKeys();output=KeyboardOutput(api,None)
        with patch("input_lease.time.monotonic",return_value=100):output.send({"up"})
        with patch("input_lease.time.monotonic",return_value=100.2):output.send({"up"})
        self.assertEqual(len(api.calls),2)


class BatchTests(unittest.TestCase):
    def test_atomic_batch_rejects_different_address(self):
        api=LiveAPI("http://127.0.0.1:9096")
        result={"ranges":[{"address":101,"size":4,"data":base64.b64encode(b"1234").decode()}]}
        with patch.object(api,"request",return_value=(json.dumps(result).encode(),{})):
            with self.assertRaises(SnapshotError):api.batch([(100,4)],1000)
    def test_atomic_batch_rejects_short_data(self):
        api=LiveAPI("http://127.0.0.1:9096")
        result={"ranges":[{"address":100,"size":4,"data":base64.b64encode(b"123").decode()}]}
        with patch.object(api,"request",return_value=(json.dumps(result).encode(),{})):
            with self.assertRaises(SnapshotError):api.batch([(100,4)],1000)
    def test_only_plain_loopback_origin_allowed(self):
        for address in ["https://127.0.0.1","http://example.org","http://user@localhost","http://localhost/path"]:
            with self.assertRaises(SnapshotError):LiveAPI(address)

    def wait_fixture(self):
        layout=Layout(metadata());feed=PoseFeed(None,layout)
        values={address:bytes(size) for address,size in feed.ranges()};a=feed.address
        values[a['helper']]=b'\x50\xa1'+struct.pack('<I',a['pending'])+bytes.fromhex('83f8037cf658c3')
        values[a['pending']]=struct.pack('<I',4)
        values[a['clocks']]=struct.pack('<2f',1,1.1)
        values[a['track']]=struct.pack('<4I',6,2,0,2)
        values[a['flags']]=struct.pack('<I',0x1)
        info={'stack':{'data':base64.b64encode(struct.pack('<2I',0,layout.link(0x4F793))).decode()}}
        return feed,values,info
    def test_atomic_completed_frame_accepts_elapsed_minimum_ticks(self):
        feed,values,info=self.wait_fixture()
        class API:
            native_batch=True
            def batch(self,*args,**kwargs):return values,info
        feed.api=API()
        self.assertEqual(feed.read()['status'],'race')
    def test_player_telemetry_reads_verified_record_fields(self):
        feed,values,info=self.wait_fixture();raw=bytearray(values[feed.address['cars']])
        struct.pack_into('<f',raw,0x500,80.5);struct.pack_into('<3f',raw,0x55c,100,20,-50)
        struct.pack_into('<f',raw,0xc7c,4321);struct.pack_into('<I',raw,0xc80,3)
        values[feed.address['cars']]=bytes(raw);values[feed.address['step']]=struct.pack('<f',.033)
        class API:
            native_batch=True
            def batch(self,*args,**kwargs):return values,info
        feed.api=API();telemetry=feed.read()['player_telemetry']
        self.assertEqual(telemetry['gear_raw'],3)
        self.assertEqual(telemetry['speed_game_units'],80.5)
        self.assertEqual(telemetry['velocity_world_units_per_second'],[100,20,-50])
    def test_pause_gap_ends_clock_rate_interval_without_losing_unique_states(self):
        feed,values,info=self.wait_fixture()
        class API:
            native_batch=True
            def batch(self,*args,**kwargs):return values,info
        feed.api=API()
        with patch('live_bridge.now_ns',side_effect=[1_000_000_000,1_000_000_000]):feed.read()
        values[feed.address['clocks']]=struct.pack('<2f',1.03,1.13)
        with patch('live_bridge.now_ns',side_effect=[16_000_000_000,16_000_000_000]):feed.read()
        self.assertEqual(feed.unique_clocks,2)
        self.assertEqual(feed.clock_transitions,0)
        self.assertEqual(feed.active_race_ns,0)
        values[feed.address['clocks']]=struct.pack('<2f',1.06,1.16)
        with patch('live_bridge.now_ns',side_effect=[16_030_000_000,16_030_000_000]):feed.read()
        self.assertEqual(feed.unique_clocks,3)
        self.assertEqual(feed.clock_transitions,1)
        self.assertEqual(feed.active_race_ns,30_000_000)
    def test_clock_metric_keeps_jitter_inside_contiguous_active_interval(self):
        feed,values,info=self.wait_fixture()
        class API:
            native_batch=True
            def batch(self,*args,**kwargs):return values,info
        feed.api=API()
        with patch('live_bridge.now_ns',side_effect=[1_000_000_000,1_000_000_000]):feed.read()
        values[feed.address['clocks']]=struct.pack('<2f',1.09,1.19)
        with patch('live_bridge.now_ns',side_effect=[1_110_000_000,1_110_000_000]):feed.read()
        self.assertEqual(feed.active_race_ns,110_000_000)
        self.assertEqual(feed.clock_transitions,1)
    def test_attract_mode_never_reports_player_telemetry(self):
        feed,values,info=self.wait_fixture();values[feed.address['flags']]=struct.pack('<I',0x80)
        class API:
            native_batch=True
            def batch(self,*args,**kwargs):return values,info
        feed.api=API();self.assertIsNone(feed.read()['player_telemetry'])
    def test_legacy_group_keeps_three_tick_boundary_guard(self):
        feed,values,info=self.wait_fixture();info['caller_link']=0x4F793
        class API:native_batch=False
        feed.api=API()
        with patch.object(feed,'_legacy',return_value=(values,info)):
            with self.assertRaises(NotReady):feed.read()


class StateRegressionTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix="rally-live-state-tests-")
        root=Path(self.directory.name)
        self.session=Session(SimpleNamespace(base_url="http://127.0.0.1:9096",input=root/"input.json",
                    state=root/"state.json",cache_root=root/"cache",extractor_dir=root/"extractor",
                    allow_isr_input=False,hud_profile=None))
        self.session.race_epoch="race1"
        self.session.assets={"epoch":"race1","scene":str(root/"world/scene.json"),"cars":str(root/"cars/scene.json")}
        self.pose={"status":"race","flags":0x1,"sample_monotonic_ns":1_000_000_000,
                   "camera":{"position":[0,0,0]},"instances":[]}
    def tearDown(self):self.directory.cleanup()
    def test_paused_or_stale_race_forces_framebuffer(self):
        with patch("live_bridge.now_ns",return_value=1_200_000_000):value=self.session.state(self.pose)
        self.assertEqual(value["status"],"paused")
        self.assertEqual(value["mode"],"framebuffer")
        self.assertFalse(value["assets_ready"])
    def test_attract_race_preserves_original_framebuffer(self):
        self.pose["flags"]=0xA0
        with patch("live_bridge.now_ns",return_value=1_010_000_000):value=self.session.state(self.pose)
        self.assertEqual(value["status"],"attract")
        self.assertEqual(value["mode"],"framebuffer")
        self.assertFalse(value['diagnostic_native_attract'])
    def test_explicit_diagnostic_attract_native_remains_labelled_and_disables_input(self):
        root=Path(self.directory.name)
        session=Session(SimpleNamespace(base_url='http://127.0.0.1:9096',input=root/'input.json',
            state=root/'state.json',cache_root=root/'cache',extractor_dir=root/'extractor',
            allow_isr_input=False,hud_profile=None,diagnostic_native_attract=True))
        session.race_epoch=self.session.race_epoch;session.assets=self.session.assets
        self.pose['flags']=0x80
        with patch('live_bridge.now_ns',return_value=1_010_000_000):value=session.state(self.pose)
        self.assertEqual(value['status'],'attract')
        self.assertTrue(value['is_attract'])
        self.assertEqual(value['mode'],'race')
        self.assertTrue(value['assets_ready'])
        self.assertTrue(value['diagnostic_native_attract'])
        self.assertEqual(value['input']['method'],'disabled-read-only-diagnostic')
        self.assertEqual(value['metrics']['distinct_race_clock_states'],0)
    def test_explicit_diagnostic_stale_attract_still_falls_back(self):
        self.session.diagnostic_native_attract=True;self.pose['flags']=0x80
        with patch('live_bridge.now_ns',return_value=1_200_000_000):value=self.session.state(self.pose)
        self.assertEqual(value['status'],'attract')
        self.assertEqual(value['mode'],'framebuffer')
        self.assertFalse(value['assets_ready'])
    def test_fresh_race_publishes_canonical_asset_keys(self):
        with patch("live_bridge.now_ns",return_value=1_010_000_000):value=self.session.state(self.pose)
        self.assertEqual(value["mode"],"race")
        self.assertEqual(value["assets"]["world_scene"],self.session.assets["scene"])
        self.assertEqual(value["assets"]["cars_scene"],self.session.assets["cars"])
    def test_duplicate_completed_state_retains_first_pose_timestamp(self):
        pose=dict(self.pose,frame_clock_bits='clock1',scene_key=(2,0,2),camera_owner=0x300000)
        self.assertTrue(self.session.retain_pose(pose))
        duplicate=dict(pose,sample_monotonic_ns=1_010_000_000,acquisition_ms=2)
        self.assertFalse(self.session.retain_pose(duplicate))
        self.assertIs(self.session.last_pose,pose)
        self.assertEqual(self.session.pose_sequence,1)
        with patch('live_bridge.now_ns',return_value=1_020_000_000):state=self.session.state()
        self.assertEqual(state['sample_monotonic_ns'],1_000_000_000)
        self.assertEqual(state['published_monotonic_ns'],1_020_000_000)
        advanced=dict(duplicate,frame_clock_bits='clock2')
        self.assertTrue(self.session.retain_pose(advanced))
        self.assertEqual(self.session.pose_sequence,2)
    def test_scene_or_camera_owner_change_starts_a_new_pose_identity(self):
        pose=dict(self.pose,frame_clock_bits='clock1',scene_key=(2,0,2),camera_owner=0x300000)
        self.session.retain_pose(pose)
        self.assertTrue(self.session.retain_pose(dict(pose,scene_key=(3,0,2))))
        self.assertTrue(self.session.retain_pose(dict(pose,camera_owner=0x310000)))
    def test_timestamp_clock_is_shared_across_processes(self):
        before=now_ns()
        command=[sys.executable,"-c",f"import sys;sys.path.insert(0,{str(Path(__file__).resolve().parent)!r});from clock_shared import now_ns;print(now_ns())"]
        child=int(subprocess.check_output(command,text=True).strip())
        after=now_ns()
        self.assertLessEqual(before,child)
        self.assertLessEqual(child,after)


if __name__=="__main__":unittest.main(verbosity=2)
