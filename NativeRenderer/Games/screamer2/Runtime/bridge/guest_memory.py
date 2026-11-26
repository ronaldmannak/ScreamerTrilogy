"""Bounded, immutable guest-RAM reads for the isolated Screamer2 renderer prototype.

No guest address is a host pointer. Snapshot.load reads local files only; it
neither starts an emulator nor writes game memory. All typed reads are little
endian and all link addresses use explicit, validated LE object mappings.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Any


MAX_SNAPSHOT_BYTES = 128 * 1024 * 1024
UINT32_END = 1 << 32
SUPPORTED_EXECUTABLES = {
    "e6c24c84650938f2baee5f4b571baa45bb09a93ba12dd24e3e1d2cefd9b6f3ec": "Screamer2 S2_3DFX original",
}


class SnapshotError(ValueError):
    """Invalid snapshot metadata, profile or address mapping."""


class MemoryReadError(SnapshotError):
    """A requested guest range falls outside the captured RAM."""


def _integer(value: Any, name: str, minimum: int = 0, maximum: int = UINT32_END - 1) -> int:
    if isinstance(value, bool):
        raise SnapshotError(f"{name} must be an integer, not a boolean")
    try:
        result = int(value, 0) if isinstance(value, str) else value
    except ValueError as error:
        raise SnapshotError(f"{name} is not an integer") from error
    if not isinstance(result, int) or not minimum <= result <= maximum:
        raise SnapshotError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return result


def _field(mapping: dict, names: tuple[str, ...], default=None):
    values = [(name, mapping[name]) for name in names if name in mapping]
    if not values:
        if default is not None:
            return default
        raise SnapshotError(f"Missing metadata field: {names[0]}")
    # Numeric aliases may use either JSON integers or 0x strings.
    numbers = [_integer(value, name, -(UINT32_END - 1), UINT32_END) for name, value in values]
    if len(set(numbers)) != 1:
        raise SnapshotError(f"Conflicting metadata fields: {', '.join(name for name, _ in values)}")
    return numbers[0]


def _digest(value, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise SnapshotError(f"{name} must be a SHA-256 hex digest")
    return value.lower()


@dataclass(frozen=True)
class ObjectMap:
    index: int
    link_base: int
    physical_base: int
    virtual_size: int

    @property
    def runtime_base(self):
        return self.physical_base

    @property
    def size(self):
        return self.virtual_size


class Snapshot:
    """One atomically captured RAM image plus its LE relocation map.

    Metadata uses execution probe fields: physical_ram_base, ram_size,
    ram_sha256, executable_sha256, monotonic_ns, pointer_bias and objects
    [{index, link_base, physical_base, virtual_size}]. runtime_base/size are
    accepted aliases for physical_base/virtual_size. Missing hashes and
    ambiguous/overlapping maps fail closed.
    """

    def __init__(self, data: bytes, metadata: dict, *, max_bytes: int = MAX_SNAPSHOT_BYTES):
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise SnapshotError("RAM must be a bytes-like object")
        if not isinstance(metadata, dict):
            raise SnapshotError("Snapshot metadata must be a JSON object")
        limit = _integer(max_bytes, "max_bytes", 1, MAX_SNAPSHOT_BYTES)
        if not 0 < len(data) <= limit:
            raise SnapshotError(f"RAM size must be positive and no larger than {limit} bytes")
        self.data = bytes(data)
        self.base = _integer(_field(metadata, ("physical_ram_base", "ram_base"), 0), "physical_ram_base")
        self.size = _integer(_field(metadata, ("ram_size", "memory_size")), "ram_size", 1, limit)
        if self.size != len(self.data) or self.base + self.size > UINT32_END:
            raise SnapshotError("RAM size/base does not match the captured byte range")
        self.sha256 = hashlib.sha256(self.data).hexdigest()
        if self.sha256 != _digest(metadata.get("ram_sha256"), "ram_sha256"):
            raise SnapshotError("RAM SHA-256 does not match metadata")
        self.executable_sha256 = _digest(metadata.get("executable_sha256"), "executable_sha256")
        if self.executable_sha256 not in SUPPORTED_EXECUTABLES:
            raise SnapshotError("Executable profile is not a recognized STRT3FX build")
        self.monotonic_ns = _integer(metadata.get("monotonic_ns"), "monotonic_ns", 0, (1 << 64) - 1)
        self.pointer_bias = _integer(metadata.get("pointer_bias", 0), "pointer_bias",
                                     -(UINT32_END - 1), UINT32_END - 1)
        raw_objects = metadata.get("objects")
        if not isinstance(raw_objects, list) or not raw_objects or len(raw_objects) > 256:
            raise SnapshotError("objects must contain between 1 and 256 LE mappings")
        objects = []
        for number, item in enumerate(raw_objects, 1):
            if not isinstance(item, dict):
                raise SnapshotError("Each LE object mapping must be an object")
            obj = ObjectMap(
                _integer(_field(item, ("index", "number"), number), "object index", 1, 65535),
                _integer(item.get("link_base"), "link_base"),
                _integer(_field(item, ("physical_base", "runtime_base")), "physical_base"),
                _integer(_field(item, ("virtual_size", "size")), "virtual_size", 1, UINT32_END),
            )
            if obj.link_base + obj.virtual_size > UINT32_END or not self.readable(obj.physical_base, obj.virtual_size):
                raise SnapshotError(f"LE object {obj.index} lies outside the link/RAM range")
            objects.append(obj)
        if len({obj.index for obj in objects}) != len(objects):
            raise SnapshotError("Duplicate LE object index")
        for base_name in ("link_base", "physical_base"):
            ordered = sorted(objects, key=lambda obj: getattr(obj, base_name))
            for left, right in zip(ordered, ordered[1:]):
                if getattr(left, base_name) + left.virtual_size > getattr(right, base_name):
                    raise SnapshotError(f"Overlapping LE {base_name} mappings")
        self.objects = tuple(objects)
        self.metadata = copy.deepcopy(metadata)

    @classmethod
    def load(cls, ram_path, metadata_path, *, max_bytes: int = MAX_SNAPSHOT_BYTES):
        """Load local files after checking their sizes, then validate every field."""
        ram_path, metadata_path = Path(ram_path), Path(metadata_path)
        if not 0 < metadata_path.stat().st_size <= 1024 * 1024:
            raise SnapshotError("Metadata must be positive and at most 1 MiB")
        with metadata_path.open("rb") as handle:
            metadata_bytes = handle.read(1024 * 1024 + 1)
        if len(metadata_bytes) > 1024 * 1024:
            raise SnapshotError("Metadata grew beyond its size limit")
        try:
            metadata = json.loads(metadata_bytes)
        except (ValueError, UnicodeDecodeError) as error:
            raise SnapshotError("Snapshot metadata is not valid UTF-8 JSON") from error
        limit = _integer(max_bytes, "max_bytes", 1, MAX_SNAPSHOT_BYTES)
        if not 0 < ram_path.stat().st_size <= limit:
            raise SnapshotError(f"RAM file must be positive and at most {limit} bytes")
        with ram_path.open("rb") as handle:
            data = handle.read(limit + 1)
        return cls(data, metadata, max_bytes=limit)

    def readable(self, address: int, length: int = 1) -> bool:
        return (isinstance(address, int) and not isinstance(address, bool)
                and isinstance(length, int) and not isinstance(length, bool)
                and address >= self.base and length >= 0
                and address <= self.base + self.size
                and length <= self.base + self.size - address)

    def _offset(self, address: int, length: int) -> int:
        if not self.readable(address, length):
            raise MemoryReadError(f"Guest range {address!r} + {length!r} is outside captured RAM")
        return address - self.base

    def bytes(self, address: int, length: int) -> bytes:
        offset = self._offset(address, length)
        return self.data[offset:offset + length]

    def _unpack(self, address: int, format_code: str, length: int):
        return struct.unpack_from("<" + format_code, self.data, self._offset(address, length))[0]

    def rd8(self, address: int) -> int:
        return self._unpack(address, "B", 1)

    def rd16(self, address: int) -> int:
        return self._unpack(address, "H", 2)

    def rd32(self, address: int) -> int:
        return self._unpack(address, "I", 4)

    def i16(self, address: int) -> int:
        return self._unpack(address, "h", 2)

    def i32(self, address: int) -> int:
        return self._unpack(address, "i", 4)

    def f32(self, address: int) -> float:
        return self._unpack(address, "f", 4)

    def translate_pointer(self, value: int) -> int:
        value = _integer(value, "guest pointer")
        if value == 0:
            return 0
        return _integer(value + self.pointer_bias, "translated guest pointer")

    def pointer(self, address: int) -> int:
        """Read/translate a pointer; its eventual dereference still checks bounds."""
        return self.translate_pointer(self.rd32(address))

    def link(self, address: int, length: int = 1) -> int:
        address = _integer(address, "link address")
        length = _integer(length, "link range length", 1, UINT32_END)
        for obj in self.objects:
            offset = address - obj.link_base
            if 0 <= offset and length <= obj.virtual_size - offset:
                return obj.physical_base + offset
        raise MemoryReadError(f"Link range {address:#x} + {length:#x} is not in a mapped LE object")

    def to_link(self, physical_address: int, length: int = 1) -> int:
        """Inverse of link for a physical RAM pointer into a known LE object."""
        physical_address = _integer(physical_address, "physical address")
        length = _integer(length, "physical range length", 1, UINT32_END)
        for obj in self.objects:
            offset = physical_address - obj.physical_base
            if 0 <= offset and length <= obj.virtual_size - offset:
                return obj.link_base + offset
        raise MemoryReadError(f"Physical range {physical_address:#x} + {length:#x} is not in a mapped LE object")
