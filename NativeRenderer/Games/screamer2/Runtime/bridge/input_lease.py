"""Complete held-key state with tap counters, focus release and stale leases."""
import base64
import json
from pathlib import Path
import struct
import time
import urllib.error

from guest_memory import SnapshotError


SCANCODES = dict(zip("1234567890", range(2, 12)))
SCANCODES.update(dict(zip("qwertyuiop", range(0x10, 0x1A))))
SCANCODES.update(dict(zip("asdfghjkl", range(0x1E, 0x27))))
SCANCODES.update(dict(zip("zxcvbnm", range(0x2C, 0x33))))
SCANCODES.update({"up":0x48,"down":0x50,"left":0x4B,"right":0x4D,"enter":0x1C,"escape":1,
                  "space":0x39,"tab":0xF,"backspace":0xE,"lshift":0x2A,"rshift":0x36,
                  "lctrl":0x1D,"rctrl":0x1D,"lalt":0x38,"ralt":0x38})
SCANCODES.update({f"f{i}":0x3A+i for i in range(1,11)})
SCANCODES.update({"f11":0x57,"f12":0x58})
ALIASES = {"return":"enter","esc":"escape","shift":"lshift","ctrl":"lctrl","alt":"lalt"}


def canonical(key):
    if not isinstance(key, str):
        raise SnapshotError("Input key names must be strings")
    key = ALIASES.get(key.lower(), key.lower())
    if key not in SCANCODES:
        raise SnapshotError(f"Unsupported input key: {key}")
    return key


class InputLease:
    def __init__(self, path, epoch, stale_seconds=.5, tap_seconds=.08):
        self.path, self.epoch = Path(path), epoch
        self.stale_seconds, self.tap_seconds = stale_seconds, tap_seconds
        self.signature = None
        self.last_seen = 0
        self.held, self.pulses, self.counts = set(), {}, {}
        self.focused = False
        self.sequence = -1
        self.error = None

    def desired(self, now=None):
        now = time.monotonic() if now is None else now
        try:
            stat = self.path.stat()
            signature = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
            if stat.st_size > 65536:
                raise SnapshotError("Input state exceeds64KiB")
            if signature != self.signature:
                value = json.loads(self.path.read_bytes())
                if (not isinstance(value, dict) or value.get("schema") != "screamer-input/v1"
                        or value.get("epoch") != self.epoch or not isinstance(value.get("focused"), bool)):
                    raise SnapshotError("Input schema/epoch/focus does not match the current bridge")
                seq = value.get("seq", value.get("sequence"))
                if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
                    raise SnapshotError("Input sequence must be a nonnegative integer")
                keys = value.get("pressed_keys", [])
                counts = value.get("press_counts", {})
                if not isinstance(keys, list) or len(keys)>128 or not isinstance(counts, dict) or len(counts)>128:
                    raise SnapshotError("Invalid bounded input table")
                keys = {canonical(key) for key in keys}
                parsed_counts = {}
                for key, count in counts.items():
                    if not isinstance(count, int) or isinstance(count, bool) or not 0 <= count < (1<<53):
                        raise SnapshotError("Invalid tap counter")
                    parsed_counts[canonical(key)] = count
                if seq < self.sequence:
                    self.counts, self.pulses = {}, {}  # A restarted frontend starts a new tap history.
                for key, count in parsed_counts.items():
                    if count > self.counts.get(key, 0):
                        self.pulses[key] = now + self.tap_seconds
                self.signature, self.sequence = signature, seq
                self.counts, self.focused = parsed_counts, value["focused"]
                self.held = keys if self.focused else set()
                if not self.focused:
                    self.pulses.clear()
                self.last_seen, self.error = now, None
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.error = str(error)
            self.held, self.pulses, self.focused = set(), {}, False
        if now - self.last_seen > self.stale_seconds:
            self.held, self.pulses, self.focused = set(), {}, False
        self.pulses = {key: expiry for key, expiry in self.pulses.items() if expiry > now}
        return self.held | set(self.pulses)


class KeyboardOutput:
    """Prefer normal engine keyboard events; restricted ISR-table fallback only."""
    def __init__(self, api, memory, allow_isr=False):
        self.api, self.memory, self.allow_isr = api, memory, allow_isr
        self.held = set()
        self.last_send = 0
        self.method = "not-yet-connected"

    def _isr(self, target):
        table = self.memory.link(0x50330, 128)
        routine = self.memory.link(0x503B0, 33)
        expected = bytearray.fromhex("601e060fa00fa8be30030300bf02000000b920000000fcf3a50fa90fa1071f61c3")
        struct.pack_into("<I", expected, 8, table)
        if self.api.read(routine, len(expected)) != expected:
            raise SnapshotError("Keyboard copy/layout guard failed; no input table written")
        codes = {SCANCODES[key] for key in target}
        previous_codes = {SCANCODES[key] for key in self.held}
        if codes == previous_codes:
            return
        for attempt in range(3):
            before = self.api.read(table, 128)
            after = bytearray(before)
            for code in codes | previous_codes:
                after[code] = 1 if code in codes else 0
            try:
                self.api.request("PUT", f"/api/v1/memory/{table}", bytes(after),
                                 {"Content-Type":"application/octet-stream", "If-Match":base64.b64encode(before).decode()}, limit=65536)
                return
            except urllib.error.HTTPError as error:
                if error.code != 412 or attempt == 2:
                    raise

    def send(self, target, force=False):
        now = time.monotonic()
        # Renew a live key lease; after one release, do not force zeros while
        # the original DOSBox window is handling its own physical keyboard.
        if not force and target == self.held and (not target or now-self.last_send < .15):
            return
        if self.api.native_keys is not False:
            try:
                self.api.keys(target)
                self.method = "normal-keyboard-api"
            except urllib.error.HTTPError as error:
                if error.code not in (404,405):
                    raise
        if self.api.native_keys is False:
            if not self.allow_isr:
                if target:
                    raise SnapshotError("Normal keyboard API is unavailable; guarded ISR fallback is not enabled")
                return
            self._isr(target)
            self.method = "guarded-isr-table-cas"
        self.held, self.last_send = set(target), now

    def release(self):
        self.send(set(), force=True)
