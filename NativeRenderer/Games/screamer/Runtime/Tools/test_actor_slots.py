"""Original disabled tags and sparse scene-list identity; no game or inputs."""
import struct,unittest
from export_dynamic import actor_slots,actor_pointer
class ActorSlots(unittest.TestCase):
    def test_disabled_pointer_and_holes_before_zero(self):
        raw=[0x2000,0xffffffff,0xc009f3e0,0xffffffff,0,0x9000]
        self.assertEqual(list(actor_slots(struct.pack('<6I',*raw))),[(0,0x2000,0x2000),(2,0xc009f3e0,0x9f3e0)])
    def test_unrecognized_active_sign_bit_stays_rejected(self):
        with self.assertRaises(ValueError):actor_pointer(0x80002000)
    def test_missing_zero_terminator_is_rejected(self):
        with self.assertRaises(ValueError):list(actor_slots(struct.pack('<3I',0x2000,0xffffffff,0x3000)))
    def test_partial_entry_is_rejected(self):
        with self.assertRaises(ValueError):list(actor_slots(b'abc'))
