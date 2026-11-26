# Attribution

The scene extractor and memory/transform contracts were developed from the reverse engineering and source in [Rick-Barber/ScreamerRally-Recomp](https://github.com/Rick-Barber/ScreamerRally-Recomp), distributed under GPL-3.0. The local prototype source is licensed under GPL-3.0-only; a copy is in `LICENSE`.

Relevant upstream sources include:

- `docs/re/native/world.md`, `extract.md`, and the documented camera/material conventions.
- `crates/sr-runtime/src/native/{world,extract,transforms,textures,frame}.rs`.
- The separation of static scene data and dynamic frame data in `sr-scene`.

The macOS renderer itself is Objective-C++ and Metal. It does not directly execute the Windows x86 runtime or use its Windows exception handling or write-watch rollback mechanism.

The live application bundles a locally built ARM64 DOSBox Staging 0.83.1 runtime. `Tools/Engine` retains its exact source/patch recipe and GPL-2.0-or-later license. The separate engine process owns original game execution; the Objective-C++ renderer consumes read-only snapshots. `Tools/Packaging` bundles Python 3.14 and the engine/Python dependency closure; its runtime manifest lists the actual imported libraries. Python's license is copied with its private standard library. No runtime binary is committed in this source subtree.

Screamer, Screamer 2 and Screamer Rally executables and original assets are owned by their respective rights holders. They are supplied by the user, kept outside version control, and are not included with the prototype source.

Public apps built with `Tools/Packaging/build_public.py` exclude original game data. The bundled importer copies the user's owned files and generates artwork/scenes in private Application Support storage. The app bundle remains unchanged.
