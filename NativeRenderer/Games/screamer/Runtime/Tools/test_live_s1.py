"""Synthetic regressions: no emulator, sockets or game input."""
import io
from pathlib import Path
import types
import unittest
from unittest.mock import Mock
from live_s1 import Bridge,NotReady,camera_pose,coalesce
import struct
import json


class Guards(unittest.TestCase):
    def bridge(self):
        args=types.SimpleNamespace(base_url='http://127.0.0.1:9099',input=Path('/nonexistent/input.json'),diagnostic_read_only=True,parent_pid=None)
        bridge=Bridge(args);bridge.scene_key=('MAP1',100,200,300);bridge.model_bases=[1234]
        bridge.cached_actors=[{'model':0,'guest_address':500,'list_index':0}];bridge.assets={'epoch':'old'};bridge.pose={'camera':{}}
        return bridge
    def test_same_map_actor_pointer_replacement_invalidates_all_assets(self):
        b=self.bridge();old=b.scene_key
        with self.assertRaises(NotReady):b.guard_actor(b.cached_actors[0],600,1234,0)
        self.assertIsNone(b.scene_key);self.assertIsNone(b.pose);self.assertIsNone(b.assets)
        self.assertEqual(b.cached_actors,[]);self.assertEqual(old[0],'MAP1')
    def test_same_model_index_new_heap_model_rebuilds(self):
        b=self.bridge()
        with self.assertRaises(NotReady):b.guard_actor(b.cached_actors[0],500,4321,0)
        self.assertIsNone(b.assets)
    def test_actor_model_id_replacement_rebuilds(self):
        b=self.bridge()
        with self.assertRaises(NotReady):b.guard_actor(b.cached_actors[0],500,1234,1)
        self.assertIsNone(b.scene_key)
    def test_invalidation_retires_pending_old_mesh_job(self):
        b=self.bridge();process=Mock();process.poll.return_value=0;log=io.BytesIO()
        b.job=(process,log,Path('/unused'),b.scene_key,Path('/unused'),b.generation)
        b.invalidate_scene('replacement')
        self.assertTrue(log.closed);self.assertIsNone(b.job)
    def test_unchanged_roster_preserves_scene(self):
        b=self.bridge();b.guard_actor(b.cached_actors[0],500,1234,0);self.assertIsNotNone(b.assets)
    def test_same_map_roster_growth_rebuilds_even_when_old_actors_unchanged(self):
        b=self.bridge();table=struct.pack('<3I',500,700,0)
        with self.assertRaises(NotReady):b.guard_roster(table)
        self.assertIsNone(b.scene_key);self.assertIsNone(b.assets)
    def test_disabled_actor_tag_preserves_guarded_identity(self):
        b=self.bridge();b.guard_actor(b.cached_actors[0],0xc0000000|500,1234,0);self.assertIsNotNone(b.assets)
    def test_unused_holes_preserve_original_slot_identity(self):
        b=self.bridge();b.cached_actors[0]['list_index']=1
        b.guard_roster(struct.pack('<4I',0xffffffff,0xc0000000|500,0xffffffff,0))
        self.assertIsNotNone(b.assets)
    def test_hole_moving_existing_pointer_invalidates_scene(self):
        b=self.bridge()
        with self.assertRaises(NotReady):b.guard_roster(struct.pack('<3I',0xffffffff,500,0))
        self.assertIsNone(b.assets)
    def test_failed_export_allows_retry_for_same_map_key(self):
        b=self.bridge();process=Mock();process.poll.return_value=1;process.returncode=1;log=io.BytesIO()
        b.job=(process,log,Path('/unused'),b.scene_key,Path('/unused'),b.generation)
        with self.assertRaises(NotReady):b.poll_job()
        self.assertIsNone(b.scene_key);self.assertIsNone(b.assets);self.assertGreater(b.retry_after,0)
    def test_old_export_generation_cannot_publish_after_replacement(self):
        b=self.bridge();process=Mock();process.poll.return_value=0;process.returncode=0;log=io.BytesIO()
        b.assets=None;b.job=(process,log,Path('/unused'),b.scene_key,Path('/unused'),b.generation-1)
        b.poll_job();self.assertIsNone(b.assets)
    def test_camera_uses_runtime_verified_projection(self):
        c=camera_pose(struct.pack('<6i',0,0,0,10,20,30))
        self.assertEqual(c['position'],[10,20,158]);self.assertEqual(c['projection']['fx'],256)
    def test_sparse_ranges_reject_ram_escape(self):
        with self.assertRaises(ValueError):coalesce([(16*1024*1024,4)])
    def test_normal_wait_miss_is_diagnostic_not_error(self):
        b=self.bridge();b.record_wait(NotReady('Guest is not at a completed-frame wait'))
        self.assertIsNone(b.last_error);self.assertEqual(b.wait_misses,1)
        self.assertEqual(b.last_wait_status,'Guest is not at a completed-frame wait')
        self.assertIsNotNone(b.assets)
    def test_normal_wait_miss_preserves_genuine_error_until_good_read(self):
        b=self.bridge();b.last_error='Original S1 wait guard failed'
        b.record_wait(NotReady('Guest is not at a completed-frame wait'))
        self.assertEqual(b.last_error,'Original S1 wait guard failed')
    def test_partial_hud_descriptor_matches_frontend_contract(self):
        profile=json.loads((Path(__file__).resolve().parent.parent/'hud-profile.json').read_text())
        self.assertFalse(profile['complete']);self.assertTrue(profile['primary_hud_validated'])
        self.assertTrue(profile['missing']);self.assertEqual(profile['required_original_hud_mode'],2)
        for r in profile['rects']:
            self.assertIn(r['anchor'],{'left','right','center'})
            self.assertGreater(r['width'],0);self.assertGreater(r['height'],0)
            self.assertGreaterEqual(r['x'],0);self.assertGreaterEqual(r['y'],0)
            self.assertLessEqual(r['x']+r['width'],640);self.assertLessEqual(r['y']+r['height'],480)


if __name__=='__main__':unittest.main()
