# Private macOS runtime packaging

`bundle_runtime.py` embeds an ARM64 DOSBox engine and Homebrew framework
Python 3.14 into a freshly staged `.app`. Run this on macOS with Xcode command
line tools; the Homebrew installation is a **build-time** input only.

```sh
python3 bundle_runtime.py --app /path/to/Staged.app \
  --engine /path/to/custom/dosbox \
  --python-prefix /path/to/homebrew/opt/python@3.14
```

The custom engine must implement the Rally bridge endpoints. This helper
does not build DOSBox, copy game assets, copy the frontend, or sign the outer
app. It copies the engine's sibling `Resources` directory automatically;
`--engine-resources` overrides that directory. A nonempty existing Python
runtime is refused, so rebuild into a fresh app.

Runtime paths, relative to the app:

- `Contents/MacOS/dosbox`
- `Contents/MacOS/lib/`: all recursively imported non-system libraries,
  including SDL3 loaded dynamically by SDL2-compat.
- `Contents/Resources/Python/bin/python3.14`: the actual interpreter, rather
  than Homebrew's small Python.app launcher.
- `Contents/Resources/Python/lib`: relative link to the private standard
  library, allowing `PYTHONHOME=Contents/Resources/Python`.
- `Contents/Resources/runtime-manifest.json`: resolved runtime inventory.

The frontend starts the private interpreter with its normal executable path
and sets the following environment values using absolute paths derived from
its own bundle:

```text
PYTHONHOME=<app>/Contents/Resources/Python
PYTHONNOUSERSITE=1
PYTHONDONTWRITEBYTECODE=1
```

Remove inherited `PYTHONPATH` and `__PYVENV_LAUNCHER__`. Do not pass Python
`-E` or `-I`: these ignore `PYTHONHOME`. The session script can then launch
children through `sys.executable`; they inherit the same private runtime.

The packager thins imported code to ARM64, rewrites non-system dependencies
to bundle-relative `@loader_path` paths, removes build-time rpaths, signs
individual Mach-O files and the private Python framework, and verifies the
signatures. The engine receives `com.apple.security.cs.allow-jit`. Use
`--identity` for a signing identity; the default is ad-hoc. The frontend
packager must sign the **outer app last**, after copying all remaining
resources, and verify it with `codesign --verify --deep --strict`.

Validation completed in an isolated fixture: 120 Mach-O files packaged;
the engine's `--version` exited successfully; the private Python imported
JSON, SSL, hashing, ctypes, fcntl, SQLite, compression, readline, urllib,
and subprocess modules and spawned its own interpreter with only
`/usr/bin:/bin` on PATH. A bounded game launch is recorded separately in the
execution test report. These checks validate local loading, not notarization
or distribution on a different Mac. HTTPS certificate stores are not
packaged; the current bridge uses loopback HTTP only.

Redistributors must retain and comply with DOSBox's GPL license and source
obligations, Python's license, and the licenses of bundled dependencies.
The helper writes no game data or engine binaries into the source tree.
