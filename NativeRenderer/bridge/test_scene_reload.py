"""Race-reload regressions using bounded fake API bytes; no game/network/input."""
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest

from live_api import NotReady
from live_bridge import Layout, PoseFeed, Session
import test_live_bridge as fixtures


class ByteAPI:
    native_batch=True
    def __init__(self,values,caller):
        self.values=values;self.caller=caller;self.requests=[]
    def batch(self,ranges,helper):
        self.requests.append(tuple(ranges))
        return {address:self.values[address] for address,_ in ranges},{'caller_link':self.caller}


def cached_feed():
    layout=Layout(fixtures.metadata());feed=PoseFeed(None,layout);a=feed.address
    feed.cars=[{'id':'scene:1','name':'auto1','model':100,
                'guest_address':0x400000,'billboard':False}]
    feed.owner=0x500000;feed.camera_address=feed.owner+0xa64
    feed.epoch_key=(2,0,2,6,0x600000,0x610000)
    values={address:bytes(size) for address,size in feed.ranges()}
    values[a['helper']]=b'\x50\xa1'+struct.pack('<I',a['pending'])+bytes.fromhex('83f8037cf658c3')
    values[a['pending']]=struct.pack('<I',4)
    values[a['clocks']]=struct.pack('<2f',1,1.1)
    values[a['track']]=struct.pack('<4I',6,2,0,2)
    values[a['flags']]=struct.pack('<I',1)
    values[a['rows']]=struct.pack('<I',0x600000)
    values[a['models']]=struct.pack('<I',0x610000)
    values[a['view']]=struct.pack('<I',feed.owner)
    values[feed.camera_address]=struct.pack('<6i',0,0,0,10,20,30)
    table=bytearray(values[a['scene']]);struct.pack_into('<I',table,28+12,0x400000)
    values[a['scene']]=bytes(table)
    values[0x400000]=struct.pack('<2I7i',100,0,100,200,300,0,0,0,-1)
    feed.api=ByteAPI(values,0x4f793)
    return feed,values


class InvalidatedPointerTests(unittest.TestCase):
    def assert_dropped(self,feed):
        self.assertEqual(feed.cars,[])
        self.assertIsNone(feed.owner);self.assertIsNone(feed.camera_address)
        self.assertIsNone(feed.epoch_key)
        self.assertEqual(feed.cache_generation,1)

    def assert_raw_recovery(self,feed):
        pose=feed.read()
        self.assertEqual(pose['status'],'race')
        self.assertIsNone(pose['camera'])
        self.assertEqual(pose['cache_generation'],1)
        ranges=feed.api.requests[-1]
        self.assertNotIn(0x400000,{address for address,_ in ranges})
        self.assertNotIn(0x500a64,{address for address,_ in ranges})
        return pose

    def test_unchanged_car_and_camera_still_emit_actual_pose(self):
        feed,_=cached_feed();pose=feed.read()
        self.assertIsNotNone(pose['camera'])
        self.assertEqual(pose['instances'][0]['position'],[100,200,300])
        self.assertEqual(feed.cache_generation,0)

    def test_replaced_car_pointer_invalidates_then_reads_raw_metadata(self):
        feed,values=cached_feed();table=bytearray(values[feed.address['scene']])
        struct.pack_into('<I',table,28+12,0x410000);values[feed.address['scene']]=bytes(table)
        with self.assertRaisesRegex(NotReady,'table'):feed.read()
        self.assert_dropped(feed);self.assert_raw_recovery(feed)

    def test_replaced_model_invalidates_then_reads_raw_metadata(self):
        feed,values=cached_feed();raw=bytearray(values[0x400000])
        struct.pack_into('<I',raw,0,101);values[0x400000]=bytes(raw)
        with self.assertRaisesRegex(NotReady,'model'):feed.read()
        self.assert_dropped(feed);self.assert_raw_recovery(feed)

    def test_new_camera_owner_invalidates_and_returns_new_owner_metadata(self):
        feed,values=cached_feed();values[feed.address['view']]=struct.pack('<I',0x510000)
        pose=feed.read()
        self.assert_dropped(feed)
        self.assertEqual(pose['camera_owner'],0x510000)
        self.assertEqual(pose['cache_generation'],1)
        self.assertIsNone(pose['camera'])
        self.assert_raw_recovery(feed)

    def test_world_mapping_change_invalidates_old_scene_addresses(self):
        feed,values=cached_feed();values[feed.address['rows']]=struct.pack('<I',0x620000)
        pose=feed.read();self.assert_dropped(feed)
        self.assertEqual(pose['scene_key'][-2],0x620000)
        self.assert_raw_recovery(feed)


class FakeJobs:
    def __init__(self,epoch):
        self.current={'epoch':epoch};self.starts=[]
    def start(self,epoch,data,metadata):
        self.current={'epoch':epoch};self.starts.append((epoch,data,metadata))
    def poll(self,epoch):
        return {'epoch':epoch} if self.current and self.current['epoch']==epoch else None


class PendingCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name)
        self.session=Session(SimpleNamespace(base_url='http://127.0.0.1:9096',input=root/'input.json',
            state=root/'state.json',cache_root=root/'cache',extractor_dir=root/'extractor',
            allow_isr_input=False,hud_profile=None))
        self.feed,values=cached_feed();self.session.feed=self.feed
        self.pose=self.feed.read()
        self.session.jobs=FakeJobs('old');self.session.race_epoch='old'
        self.session.scene_key=self.pose['scene_key'];self.session.scene_owner=self.pose['camera_owner']
        self.session.scene_cache_generation=0;self.session.previous_phase='race'
        self.session.previous_attract=False;self.session.assets={'epoch':'old'}
        self.session.last_capture_try=100
        self.captures=[]
        def capture(pose):
            self.captures.append(pose)
            return SimpleNamespace(data=b'new immutable RAM',metadata={'ram_sha256':'a'*64})
        self.feed.capture_race=capture

    def tearDown(self):self.temp.cleanup()

    def assert_throttle_then_capture(self,pose):
        self.session.handle_pose(pose,100.1)
        epoch=self.session.race_epoch
        self.assertNotEqual(epoch,'old');self.assertTrue(self.session.capture_pending)
        self.assertIsNone(self.session.assets);self.assertEqual(self.captures,[])
        self.session.handle_pose(pose,100.2)
        self.assertEqual(self.session.race_epoch,epoch)
        self.session.handle_pose(pose,100.3)
        self.assertEqual(self.session.race_epoch,epoch)
        self.assertEqual(len(self.captures),1)
        self.assertFalse(self.session.capture_pending)
        self.assertEqual(self.session.jobs.starts[0][0],epoch)
        self.assertEqual(self.session.assets['epoch'],epoch)

    def test_same_key_menu_transition_remains_pending_after_throttle(self):
        self.session.previous_phase='menu';self.assert_throttle_then_capture(self.pose)

    def test_same_key_attract_to_race_remains_pending_after_throttle(self):
        self.session.previous_attract=True;self.assert_throttle_then_capture(self.pose)

    def test_invalidated_car_generation_creates_pending_asset_epoch(self):
        self.feed.invalidate()
        pose=dict(self.pose,cache_generation=self.feed.cache_generation,camera=None,instances=[])
        self.assert_throttle_then_capture(pose)

    def test_owner_change_creates_pending_asset_epoch(self):
        pose=dict(self.pose,camera_owner=0x510000)
        self.assert_throttle_then_capture(pose)

    def test_missing_epoch_job_retries_even_with_matching_cached_game_key(self):
        self.session.jobs.current={'epoch':'different'}
        self.session.handle_pose(self.pose,100.1)
        self.assertTrue(self.session.capture_pending);self.assertEqual(self.session.race_epoch,'old')
        self.session.handle_pose(self.pose,100.3)
        self.assertEqual(len(self.captures),1);self.assertEqual(self.session.jobs.current['epoch'],'old')

    def test_not_ready_retry_keeps_epoch_until_capture_and_job_start_succeed(self):
        self.session.previous_phase='menu'
        original=self.feed.capture_race
        def transient(pose):
            self.feed.capture_race=original
            raise NotReady('temporarily outside frame wait')
        self.feed.capture_race=transient
        with self.assertRaises(NotReady):self.session.handle_pose(self.pose,100.3)
        epoch=self.session.race_epoch
        self.assertTrue(self.session.capture_pending)
        self.session.handle_pose(self.pose,100.4)
        self.assertEqual(self.session.race_epoch,epoch);self.assertEqual(self.captures,[])
        self.session.handle_pose(self.pose,100.6)
        self.assertEqual(self.session.race_epoch,epoch)
        self.assertEqual(len(self.captures),1);self.assertFalse(self.session.capture_pending)


if __name__=='__main__':unittest.main(verbosity=2)
