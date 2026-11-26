#!/usr/bin/env python3
"""S2 profile/guard/protocol regressions; no network, game process or input events."""
from pathlib import Path
import base64,json,struct,sys,tempfile,unittest
from types import SimpleNamespace
from unittest.mock import patch,Mock
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).parent/'bridge'))
from guest_memory import SnapshotError
from live_bridge import Layout,PoseFeed,Session,LINK
from live_api import NotReady
from replay import camera_from_pose
SHA='e6c24c84650938f2baee5f4b571baa45bb09a93ba12dd24e3e1d2cefd9b6f3ec'
def metadata():return {'executable_sha256':SHA,'ram_size':16*1024*1024,'physical_ram_base':0,'pointer_bias':0,
 'objects':[{'index':2,'link_base':0x20000,'physical_base':0x1e1000,'virtual_size':0xd0ae0},
            {'index':6,'link_base':0x130000,'physical_base':0x2b2000,'virtual_size':0x74ee0}]}
class Guards(unittest.TestCase):
 def fixture(self,caller=0x50c6d):
  layout=Layout(metadata());feed=PoseFeed(None,layout);a=feed.address
  values={addr:bytes(size)for addr,size in feed.ranges()}
  values[a['helper']]=b'\x50\xa1'+struct.pack('<I',a['pending'])+bytes.fromhex('83f8027cf658c3')
  values[a['pending']]=struct.pack('<I',2);values[a['clocks']]=struct.pack('<2f',1,1.1)
  values[a['track']]=struct.pack('<4I',4,0,0,2);values[a['flags']]=struct.pack('<I',0x80)
  values[a['step']]=struct.pack('<f',.022);values[a['raw_step']]=struct.pack('<f',.02)
  info={'stack':{'data':base64.b64encode(struct.pack('<2I',0,layout.link(caller))).decode()}}
  class API:
   native_batch=True
   def batch(self,*args,**kwargs):return values,info
  feed.api=API();return feed,values
 def test_exact_s2_addresses_and_caller(self):
  self.assertEqual(LINK['flags'],0x151748);self.assertEqual(LINK['race_state'],0x13fac0)
  feed,_=self.fixture();value=feed.read();self.assertEqual(value['status'],'race');self.assertEqual(value['car_count'],4)
 def test_original_two_tick_wait_accepted_without_changing_simulation(self):
  feed,_=self.fixture();value=feed.read();self.assertAlmostEqual(value['timing']['raw_frame_step_seconds'],.02,places=6)
  self.assertAlmostEqual(value['timing']['smoothed_step_seconds'],.022,places=6)
 def test_rally_three_tick_guard_rejected(self):
  feed,values=self.fixture();values[feed.address['helper']]=values[feed.address['helper']].replace(bytes.fromhex('83f802'),bytes.fromhex('83f803'))
  with self.assertRaises(SnapshotError):feed.read()
 def test_wrong_relocated_counter_rejected(self):
  feed,values=self.fixture();raw=bytearray(values[feed.address['helper']]);struct.pack_into('<I',raw,2,feed.address['pending']+4);values[feed.address['helper']]=bytes(raw)
  with self.assertRaises(SnapshotError):feed.read()
 def test_menu_caller_classified_separately(self):
  feed,_=self.fixture(0x50bcb);self.assertEqual(feed.read()['status'],'menu')
 def test_attract_does_not_increment_real_race_clock_metrics(self):
  feed,values=self.fixture();feed.read();values[feed.address['clocks']]=struct.pack('<2f',1.02,1.122);feed.read()
  self.assertEqual(feed.unique_clocks,0);self.assertEqual(feed.active_race_ns,0)
 def test_rally_executable_profile_not_accepted(self):
  m=metadata();m['executable_sha256']='9eac6e12ab309389bdda019cfa695bfbbc791fbda1a4634464a444fce35165d1'
  with self.assertRaises(SnapshotError):Layout(m)
 def test_overlapping_or_outside_ram_maps_rejected(self):
  for value in (0x1e2000,0xffff00):
   m=metadata();m['objects'][1]['physical_base']=value
   with self.assertRaises(SnapshotError):Layout(m)
 def cached_fixture(self):
  feed,values=self.fixture();a=feed.address;owner=0x500000
  values[a['view']]=struct.pack('<I',owner)
  values[a['rows']]=struct.pack('<I',0x700000);values[a['models']]=struct.pack('<I',0x710000)
  feed.owner=owner;feed.camera_address=owner+0xa64;feed.epoch_key=(0,0,2,4,0x700000,0x710000)
  feed.cars=[{'id':'scene:0','model':10,'guest_address':0x600000}]
  for address,size in feed.ranges():values.setdefault(address,bytes(size))
  table=bytearray(values[a['scene']]);struct.pack_into('<I',table,12,0x600000);values[a['scene']]=bytes(table)
  values[0x600000]=struct.pack('<2I',10,0)+bytes(28)
  return feed,values
 def test_same_key_pointer_model_and_billboard_replacements_retire_cache(self):
  for change in ('pointer','model','billboard'):
   with self.subTest(change=change):
    feed,values=self.cached_fixture();oldkey=feed.epoch_key
    if change=='pointer':
     table=bytearray(values[feed.address['scene']]);struct.pack_into('<I',table,12,0x600100);values[feed.address['scene']]=bytes(table)
    else:values[0x600000]=struct.pack('<2I',11 if change=='model'else 10,0x8000 if change=='billboard'else 0)+bytes(28)
    with self.assertRaises(NotReady):feed.read()
    self.assertEqual(feed.cache_generation,1);self.assertIsNone(feed.epoch_key);self.assertIsNone(feed.owner);self.assertIsNone(feed.camera_address);self.assertEqual(feed.cars,[])
    raw=feed.read();self.assertEqual(raw['scene_key'],oldkey);self.assertEqual(raw['cache_generation'],1);self.assertIsNone(raw['camera'])
    self.assertNotIn(0x600000,[address for address,size in feed.ranges()])
 def test_same_key_camera_owner_replacement_returns_new_generation(self):
  feed,values=self.cached_fixture();values[feed.address['view']]=struct.pack('<I',0x520000)
  raw=feed.read();self.assertEqual(raw['cache_generation'],1);self.assertIsNone(raw['camera']);self.assertEqual(feed.cars,[])
class Protocol(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  args=SimpleNamespace(base_url='http://127.0.0.1:1234',input=self.root/'input.json',state=self.root/'state.json',cache_root=self.root/'assets',extractor_dir=self.root/'extractor',hud_profile=Path(__file__).parent/'hud-profile.json',read_only=True)
  self.s=Session(args);self.s.race_epoch='world1';self.s.assets={'epoch':'world1','scene':str(self.root/'world/scene.json'),'cars':str(self.root/'cars/scene.json')};self.s.frame={'width':640,'height':480}
  self.pose={'status':'race','flags':0x80,'sample_monotonic_ns':1_000_000_000,'camera':camera_from_pose([1,2,3],[0,0,0]),'instances':[],'frame_clock_bits':'a','scene_key':(0,0,2,4),'camera_owner':0x300000}
 def tearDown(self):self.temp.cleanup()
 def test_honest_attract_mode_and_period_with_read_only_input(self):
  with patch('live_bridge.now_ns',return_value=1_020_000_000):v=self.s.state(self.pose)
  self.assertEqual(v['mode'],'attract');self.assertEqual(v['status'],'attract');self.assertTrue(v['is_attract']);self.assertEqual(v['physics_period_ms'],20)
  self.assertEqual(v['input']['method'],'disabled-read-only-diagnostic');self.assertTrue(v['hud']['complete'])
 def test_real_race_hud_preserves_partial_validation_and_missing_items(self):
  self.pose['flags']=1
  with patch('live_bridge.now_ns',return_value=1_020_000_000):v=self.s.state(self.pose)
  self.assertEqual(v['status'],'race');self.assertFalse(v['hud']['complete']);self.assertTrue(v['hud']['primary_hud_validated']);self.assertTrue(v['hud']['missing'])
 def test_split_screen_profile_guard_falls_back(self):
  self.pose['flags']=0x41
  with patch('live_bridge.now_ns',return_value=1_020_000_000):v=self.s.state(self.pose)
  self.assertNotIn('hud',v)
 def test_camera_mode_is_forwarded_without_changing_projection(self):
  self.pose['camera_mode']=6
  with patch('live_bridge.now_ns',return_value=1_020_000_000):v=self.s.state(self.pose)
  self.assertEqual(v['camera_mode'],6);self.assertEqual(v['camera']['projection']['cy'],312)
 def test_hud_source_dimension_mismatch_not_published(self):
  self.s.frame['width']=800
  with patch('live_bridge.now_ns',return_value=1_020_000_000):v=self.s.state(self.pose)
  self.assertNotIn('hud',v)
 def test_stale_attract_falls_back_to_original_framebuffer(self):
  with patch('live_bridge.now_ns',return_value=1_200_000_000):v=self.s.state(self.pose)
  self.assertEqual(v['status'],'paused');self.assertEqual(v['mode'],'framebuffer');self.assertFalse(v['assets_ready']);self.assertNotIn('hud',v)
 def test_duplicate_frame_retains_original_pose_time(self):
  self.s.retain_pose(self.pose);self.assertFalse(self.s.retain_pose(dict(self.pose,sample_monotonic_ns=1_010_000_000)))
  self.assertEqual(self.s.last_pose['sample_monotonic_ns'],1_000_000_000);self.assertEqual(self.s.pose_sequence,1)
 def test_canonical_asset_paths_preserved(self):
  with patch('live_bridge.now_ns',return_value=1_020_000_000):v=self.s.state(self.pose)
  self.assertEqual(v['assets']['world_scene'],self.s.assets['scene']);self.assertEqual(v['assets']['cars_scene'],self.s.assets['cars'])
 def prepare_recovery(self):
  self.pose['cache_generation']=0
  self.s.scene_key=self.pose['scene_key'];self.s.scene_generation=0;self.s.previous_phase='race';self.s.previous_attract=True
  self.s.feed=SimpleNamespace(epoch_key=self.pose['scene_key'],capture_race=Mock(return_value=SimpleNamespace(data=b'newcapture',metadata={})))
  self.s.jobs.current={'epoch':'world1'}
  def started(epoch,*unused):self.s.jobs.current={'epoch':epoch}
  self.s.jobs.start=Mock(side_effect=started);self.s.jobs.poll=Mock(return_value=None)
 def test_same_key_invalidated_generation_starts_a_new_epoch_and_capture(self):
  self.prepare_recovery();self.pose['cache_generation']=1;self.s.feed.epoch_key=None
  self.s.handle_pose(self.pose,1)
  self.assertNotEqual(self.s.race_epoch,'world1');self.assertEqual(self.s.scene_generation,1)
  self.s.feed.capture_race.assert_called_once_with(self.pose);self.s.jobs.start.assert_called_once();self.assertFalse(self.s.capture_pending)
 def test_same_key_phase_capture_survives_250ms_throttle(self):
  self.prepare_recovery();self.s.previous_phase='menu';self.s.last_capture_try=1
  self.s.handle_pose(self.pose,1.1);new_epoch=self.s.race_epoch
  self.assertTrue(self.s.capture_pending);self.assertEqual(self.s.previous_phase,'race');self.s.feed.capture_race.assert_not_called()
  self.s.handle_pose(self.pose,1.4)
  self.assertEqual(self.s.race_epoch,new_epoch);self.s.feed.capture_race.assert_called_once();self.assertFalse(self.s.capture_pending)
 def test_capture_wait_miss_retries_without_churning_epoch(self):
  self.prepare_recovery();self.s.previous_phase='menu'
  memory=SimpleNamespace(data=b'capture',metadata={});self.s.feed.capture_race.side_effect=[NotReady('wait miss'),memory]
  with self.assertRaises(NotReady):self.s.handle_pose(self.pose,1)
  epoch=self.s.race_epoch;self.assertTrue(self.s.capture_pending);self.assertEqual(self.s.previous_phase,'race')
  self.s.handle_pose(self.pose,1.4)
  self.assertEqual(self.s.race_epoch,epoch);self.assertEqual(self.s.feed.capture_race.call_count,2);self.assertFalse(self.s.capture_pending)
if __name__=='__main__':unittest.main(verbosity=2)
