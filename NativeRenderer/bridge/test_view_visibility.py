"""Synthetic tests for original per-view visibility and live publication."""
import struct
import unittest
from unittest.mock import patch

from live_api import NotReady
from live_bridge import PoseFeed
import test_live_bridge as bridge_tests
from view_visibility import (ViewVisibility, VisibilitySceneChanged,
                             FOLLOWED_OFFSET, BODY_INDEX_OFFSET)


class ViewVisibilityTests(unittest.TestCase):
    def fixture(self):
        view = ViewVisibility(16*1024*1024)
        owner, followed, index, instance = 0x330000, 0x2B96C8, 157, 0x99D30
        view.followed = followed
        table = bytearray((index+1)*28)
        table[index*28:index*28+8] = b'auto1\0\0\0'
        struct.pack_into('<I', table, index*28+12, instance)
        struct.pack_into('<I', table, index*28+24, index)
        cars = [{'id':'scene:157','name':'auto1','guest_address':instance}]
        data = {owner+FOLLOWED_OFFSET:struct.pack('<I',followed),
                followed+BODY_INDEX_OFFSET:struct.pack('<I',index)}
        return view, owner, followed, data, table, cars

    def test_exact_original_scene_index_hides_only_in_modes_two_and_five(self):
        view, owner, _, data, table, cars = self.fixture()
        for mode in (2,5):
            with self.subTest(mode=mode):
                self.assertEqual(view.hidden(mode,owner,data,table,cars),['scene:157'])
        for mode in (1,3,4,6):
            with self.subTest(mode=mode):
                self.assertEqual(view.hidden(mode,owner,data,table,cars),[])

    def test_changed_pointer_requires_new_atomic_dependent_index(self):
        view, owner, followed, data, table, cars = self.fixture()
        fresh = followed+0xCC8
        data[owner+FOLLOWED_OFFSET] = struct.pack('<I',fresh)
        with self.assertRaises(NotReady):view.hidden(2,owner,data,table,cars)
        self.assertEqual(view.ranges(owner),[(owner+FOLLOWED_OFFSET,4),(fresh+BODY_INDEX_OFFSET,4)])
        with self.assertRaises(NotReady):view.hidden(2,owner,data,table,cars)
        data[fresh+BODY_INDEX_OFFSET] = struct.pack('<I',157)
        self.assertEqual(view.hidden(2,owner,data,table,cars),['scene:157'])

    def test_chase_view_keeps_player_while_refreshing_pointer(self):
        view, owner, followed, data, _, _ = self.fixture()
        data[owner+FOLLOWED_OFFSET] = struct.pack('<I',followed+0xCC8)
        self.assertEqual(view.hidden(4,owner,data,b'',[]),[])
        self.assertEqual(view.followed,followed+0xCC8)

    def test_invalid_pointer_never_becomes_a_guest_read(self):
        view, owner, _, data, table, cars = self.fixture()
        for pointer in (0,16*1024*1024-1,0xFFFFFFFF):
            with self.subTest(pointer=pointer):
                data[owner+FOLLOWED_OFFSET] = struct.pack('<I',pointer)
                with self.assertRaises(NotReady):view.hidden(2,owner,data,table,cars)
                self.assertEqual(view.ranges(owner),[(owner+FOLLOWED_OFFSET,4)])

    def test_index_must_select_an_exported_original_car(self):
        view, owner, followed, data, table, cars = self.fixture()
        for index in (156,1024,0xFFFFFFFF):
            with self.subTest(index=index):
                data[followed+BODY_INDEX_OFFSET] = struct.pack('<I',index)
                with self.assertRaises(VisibilitySceneChanged):view.hidden(2,owner,data,table,cars)

    def test_name_pointer_and_live_scene_slot_are_validated(self):
        for mutation in ('name','pointer','terminator'):
            view, owner, _, data, table, cars = self.fixture()
            if mutation=='name':table[157*28:157*28+8]=b'auto2\0\0\0'
            elif mutation=='pointer':struct.pack_into('<I',table,157*28+12,0x99D70)
            else:struct.pack_into('<I',table,157*28+24,0xFFFFFFFF)
            with self.subTest(mutation=mutation),self.assertRaises(VisibilitySceneChanged):
                view.hidden(2,owner,data,table,cars)

    def test_reset_discards_dependent_pointer(self):
        view, owner, *_ = self.fixture()
        view.reset()
        self.assertEqual(view.ranges(owner),[(owner+FOLLOWED_OFFSET,4)])


class FeedVisibilityTests(unittest.TestCase):
    def test_pose_feed_batches_fresh_follow_pointer_and_dependent_record(self):
        feed, _, _ = bridge_tests.BatchTests().wait_fixture()
        feed.owner = 0x330000
        feed.camera_address = feed.owner+0xA64
        feed.cars = [{'id':'scene:157','guest_address':0x99D30}]
        feed.visibility.followed = 0x2B96C8
        ranges=feed.ranges()
        self.assertIn((feed.owner+FOLLOWED_OFFSET,4),ranges)
        self.assertIn((0x2B96C8+BODY_INDEX_OFFSET,4),ranges)
        feed.invalidate()
        self.assertIsNone(feed.visibility.followed)

    def test_completed_pose_publishes_exact_hidden_id(self):
        feed, values, info = bridge_tests.BatchTests().wait_fixture()
        owner, followed, instance, index = 0x330000,0x2B96C8,0x99D30,157
        feed.owner=owner;feed.camera_address=owner+0xA64
        feed.cars=[{'id':'scene:157','name':'auto1','guest_address':instance,'model':1590}]
        feed.visibility.followed=followed
        feed.epoch_key=(2,0,2,6,0,0)
        a=feed.address;values[a['view']]=struct.pack('<I',owner)
        values[owner+0xAE4]=struct.pack('<I',2)
        values[owner+FOLLOWED_OFFSET]=struct.pack('<I',followed)
        values[followed+BODY_INDEX_OFFSET]=struct.pack('<I',index)
        values[feed.camera_address]=bytes(24)
        table=bytearray((index+1)*28);table[index*28:index*28+8]=b'auto1\0\0\0'
        struct.pack_into('<I',table,index*28+12,instance)
        struct.pack_into('<I',table,index*28+24,index)
        values[a['scene']]=bytes(table)
        values[instance]=struct.pack('<9I',1590,1,0,0,0,0,0,0,0)
        class API:
            native_batch=True
            def batch(self,*args,**kwargs):return values,info
        feed.api=API()
        self.assertEqual(feed.read()['hidden_instance_ids'],['scene:157'])
        values[owner+0xAE4]=struct.pack('<I',4)
        self.assertEqual(feed.read()['hidden_instance_ids'],[])


class VisibilityStateTests(unittest.TestCase):
    def setUp(self):
        self.fixture=bridge_tests.StateRegressionTests()
        self.fixture.setUp()
        self.session,self.pose=self.fixture.session,self.fixture.pose

    def tearDown(self):
        self.fixture.tearDown()

    def test_hidden_ids_publish_and_change_pose_identity(self):
        pose=dict(self.pose,frame_clock_bits='clock1',camera_mode=2,
                  hidden_instance_ids=['scene:157'])
        self.session.retain_pose(pose)
        with patch('live_bridge.now_ns',return_value=1_010_000_000):state=self.session.state()
        self.assertEqual(state['hidden_instance_ids'],['scene:157'])
        self.assertTrue(self.session.retain_pose(dict(pose,hidden_instance_ids=[])))
        with patch('live_bridge.now_ns',return_value=1_010_000_000):state=self.session.state()
        self.assertEqual(state['hidden_instance_ids'],[])
