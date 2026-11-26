# Runtime validation

Validated 2026-11-24 on the development Apple Silicon Mac. All fixture
outputs are temporary diagnostic data, not distributable game assets.

1. `bundle_runtime.py` produced a self-contained fixture with 120 ARM64
   Mach-O files. Every imported non-system dependency resolved inside the
   bundle after rewriting, and every copied Mach-O plus the Python framework
   passed strict signature validation.
2. The private `dosbox --version` exited 0. This specifically verifies the
   SDL2-compat -> dynamically loaded SDL3 dependency that an `otool -L`-only
   closure misses. No SDL3 environment override was needed.
3. With PATH restricted to `/usr/bin:/bin`, inherited PYTHONPATH and
   `__PYVENV_LAUNCHER__` cleared, and PYTHONHOME set to the fixture's
   `Contents/Resources/Python`, the actual private interpreter loaded its own
   standard library. JSON, SSL, hashlib, ctypes, fcntl, SQLite, lzma, bz2,
   zlib, readline, urllib and subprocess imported successfully. A child
   launched through `sys.executable` inherited the private prefix.
4. The private Python then ran `Execution/launch_engine.py` with the
   fixture's private engine, isolated temporary persistent data and session,
   dummy video/audio, loopback port 9097, and a 25-second limit. It published
   a valid relocated LE layout and exited normally at the limit; engine
   exit status was 0. There were no scripted keys or memory writes.
   Evidence is `/private/tmp/rally-live/packaged-runtime-test-session/`.
   This short startup check does not claim visual race validation.
5. The four synthetic source/patch/capture guard tests in
   `Execution/test_capture_probe.py` passed after the live-launch additions.

An earlier stock-engine bounded check established CoreAudio initialization
with dummy video. The custom engine's raw frame, atomic batch read and
release-all input endpoints returned successful responses before bundling;
only empty key release was tested. GUI input and the full native live race
remain the frontend's separate validation responsibility.

The test fixture is not notarized. This report does not establish behavior
on another machine or complete third-party redistribution compliance.
