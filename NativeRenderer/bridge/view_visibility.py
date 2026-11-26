# SPDX-License-Identifier: GPL-3.0-only
"""Original per-view own-car hide, from 349b8 -> 20cfc.

The game temporarily hides scene entries followed+BF0 (body) and +BF8
(shadow) in camera modes2/5, then restores them before the frame wait.
Only body meshes are exported by this bridge. Scene IDs come from the
original index, never proximity or image classification.
"""
import struct

from live_api import NotReady

FOLLOWED_OFFSET = 0xADC
BODY_INDEX_OFFSET = 0xBF0
CAR_RECORD_SIZE = 0xCC8
SCENE_ENTRY_SIZE = 28
MAX_SCENE_ENTRIES = 1024
HIDE_MODES = {2, 5}


class VisibilitySceneChanged(NotReady):
    """The cached original car table no longer validates the followed ID."""


class ViewVisibility:
    def __init__(self, ram_size):
        self.ram_size = ram_size
        self.followed = None

    def reset(self):
        self.followed = None

    def _record(self, pointer):
        return pointer if 0 < pointer <= self.ram_size - CAR_RECORD_SIZE else None

    def prime(self, memory, owner):
        self.followed = self._record(memory.rd32(owner + FOLLOWED_OFFSET))

    def ranges(self, owner):
        result = [(owner + FOLLOWED_OFFSET, 4)]
        if self.followed is not None:
            result.append((self.followed + BODY_INDEX_OFFSET, 4))
        return result

    def hidden(self, mode, owner, data, table, cars):
        # This fresh pointer and its dependent record come from one atomic
        # frame-wait batch. A pointer change schedules the new dependent
        # address for the next batch; never interpret an old record as new.
        followed = self._record(struct.unpack('<I', data[owner + FOLLOWED_OFFSET])[0])
        if followed != self.followed:
            self.followed = followed
            if mode in HIDE_MODES:
                raise NotReady('Followed car pointer changed; acquiring its fresh scene index')
        if mode not in HIDE_MODES:
            return []
        if followed is None:
            raise NotReady('Bumper view has no valid followed car record')
        raw = data.get(followed + BODY_INDEX_OFFSET)
        if raw is None or len(raw) != 4:
            raise NotReady('Followed car scene index was not in this atomic frame')
        index = struct.unpack('<I', raw)[0]
        identifier = f'scene:{index}'
        original = next((car for car in cars if car['id'] == identifier), None)
        offset = index * SCENE_ENTRY_SIZE
        if (index >= MAX_SCENE_ENTRIES or original is None
                or offset + SCENE_ENTRY_SIZE > len(table)):
            raise VisibilitySceneChanged('Followed body index is outside the captured car table')
        name = table[offset:offset + 8].split(b'\0', 1)[0]
        pointer, slot = struct.unpack_from('<I8xI', table, offset + 12)
        expected = original['name'].encode('ascii', errors='strict')
        if (not name.startswith(b'auto') or name != expected
                or pointer != original['guest_address'] or slot == 0xFFFFFFFF):
            raise VisibilitySceneChanged('Followed body name/instance does not match the captured car')
        return [identifier]
