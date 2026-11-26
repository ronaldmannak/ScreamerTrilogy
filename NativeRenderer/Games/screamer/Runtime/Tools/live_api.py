"""Loopback-only DOSBox bridge protocol; normal keyboard input, bounded reads."""
import base64
import json
import struct
import urllib.error
import urllib.parse
import urllib.request

from guest_memory import SnapshotError


class NotReady(SnapshotError):
    pass


class LiveAPI:
    def __init__(self, origin, timeout=.3):
        url = urllib.parse.urlsplit(origin)
        if (url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1", "::1"}
                or url.username or url.password or url.path not in {"", "/"} or url.query or url.fragment):
            raise SnapshotError("Emulator API must be a plain loopback HTTP origin")
        self.origin, self.timeout = origin.rstrip("/"), timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.native_batch = self.native_keys = None
        self.requests = self.received_bytes = self.sent_bytes = 0

    def request(self, method, path, data=None, headers=None, limit=2*1024*1024, timeout=None):
        headers = dict(headers or {})
        if isinstance(data, dict):
            data = json.dumps(data, separators=(",", ":"), allow_nan=False).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.origin + path, data=data, headers=headers, method=method)
        with self.opener.open(request, timeout=timeout or self.timeout) as response:
            body, response_headers = response.read(limit + 1), dict(response.headers)
        if len(body) > limit:
            raise SnapshotError("Emulator API response exceeds its bounded read")
        self.requests += 1
        self.received_bytes += len(body)
        self.sent_bytes += len(data or b"")
        return body, response_headers

    def read(self, address, size):
        if not isinstance(address, int) or not isinstance(size, int) or address < 0 or size <= 0 or address+size > 16*1024*1024:
            raise SnapshotError("Guest read is outside the configured16MiB RAM")
        body, _ = self.request("GET", f"/api/v1/memory/{address}/{size}",
                               headers={"Accept": "application/octet-stream"}, limit=size, timeout=2 if size>65536 else None)
        if len(body) != size:
            raise SnapshotError("Short guest-memory read")
        return body

    def marker(self, clock_address, pending_address, helper, translate_link):
        body, _ = self.request("GET", f"/api/v1/memory/{clock_address}/8",
                               headers={"Accept": "application/json"}, limit=65536)
        result = json.loads(body)
        clocks = base64.b64decode(result["memory"]["data"], validate=True)
        registers = result["registers"]
        pc, sp = int(registers["eip"]), int(registers["esp"])
        if pc not in {helper+1, helper+6, helper+9}:
            raise NotReady("Guest is outside its completed-frame wait")
        pending = struct.unpack("<I", self.read(pending_address, 4))[0]
        caller = struct.unpack("<I", self.read(sp+4, 4))[0]
        return {"clocks": clocks, "pending": pending, "caller": translate_link(caller), "registers": registers}

    def batch(self, ranges, helper, *, wait=True, full=False):
        request = {"ranges": [{"address": int(address), "size": int(size)} for address, size in ranges]}
        if wait:
            request["require_eip_ranges"] = [{"address": helper+offset, "size": 1} for offset in (0, 6, 9)]
        limit = 24*1024*1024 if full else 2*1024*1024
        try:
            body, _ = self.request("POST", "/api/v1/rally/read", request, limit=limit, timeout=3 if full else None)
        except urllib.error.HTTPError as error:
            if error.code in (404, 405):
                self.native_batch = False
            if error.code in (409, 503):
                raise NotReady("Guest is not at a completed-frame wait") from error
            raise
        self.native_batch = True
        result = json.loads(body)
        if not isinstance(result.get("ranges"), list) or len(result["ranges"]) != len(ranges):
            raise SnapshotError("Atomic batch returned the wrong range count")
        decoded = {}
        for expected, item in zip(ranges, result["ranges"]):
            address, size = expected
            if item.get("address") != address or item.get("size", size) != size:
                raise SnapshotError("Atomic batch returned a different range")
            raw = base64.b64decode(item["data"], validate=True)
            if len(raw) != size:
                raise SnapshotError("Atomic batch returned a short range")
            decoded[address] = raw
        return decoded, result

    def keys(self, pressed):
        try:
            self.request("POST", "/api/v1/rally/keys", {"pressed_keys": sorted(pressed), "release_all": not pressed}, limit=65536)
        except urllib.error.HTTPError as error:
            if error.code in (404, 405):
                self.native_keys = False
            raise
        self.native_keys = True

    def frame(self):
        try:
            data, headers = self.request("GET", "/api/v1/rally/frame", limit=8192*8192*4, timeout=.5)
        except urllib.error.HTTPError as error:
            if error.code in (404, 503):
                raise NotReady("No framebuffer is available yet") from error
            raise
        headers = {key.lower(): value for key, value in headers.items()}
        width, height = int(headers["x-rally-width"]), int(headers["x-rally-height"])
        stride = int(headers["x-rally-pitch"])
        if not 0 < width <= 8192 or not 0 < height <= 8192 or not width*4 <= stride <= 8192*4 or len(data) != stride*height:
            raise SnapshotError("Invalid cached BGRA framebuffer dimensions")
        return data, {"width": width, "height": height, "stride": stride, "format": "bgra8",
                      "sequence": int(headers.get("x-rally-sequence", 0)),
                      "capture_ns": int(headers.get("x-rally-capture-ns", 0))}
