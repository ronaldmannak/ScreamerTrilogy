"""Cross-process clock shared with CACurrentMediaTime on macOS.

Python3.9's macOS time.monotonic epoch is process-local. Live producer/consumer
timestamps therefore use the underlying Mach absolute clock explicitly.
"""
import ctypes
import sys
import time


if sys.platform == "darwin":
    class _Timebase(ctypes.Structure):
        _fields_ = [("numer",ctypes.c_uint32),("denom",ctypes.c_uint32)]
    _library=ctypes.CDLL(None)
    _library.mach_absolute_time.restype=ctypes.c_uint64
    _scale=_Timebase()
    if _library.mach_timebase_info(ctypes.byref(_scale)) or not _scale.denom:
        raise RuntimeError("Cannot initialize the shared Mach timestamp clock")
    def now_ns():
        return _library.mach_absolute_time()*_scale.numer//_scale.denom
else:
    now_ns=time.monotonic_ns
