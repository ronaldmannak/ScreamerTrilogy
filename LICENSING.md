# Source and bundled component licenses

The default license for this project's first-party source, build/import/publication tools and documentation is **GPL-3.0-only**, in [LICENSE](LICENSE). Component licenses and existing per-file notices take precedence over that default. Original game content is excluded from these grants.

| Component | License and attribution |
| --- | --- |
| `NativeRenderer/` renderer, launcher and extractor/bridge adaptations | GPL-3.0-only; [license](NativeRenderer/LICENSE) and [third-party notices](NativeRenderer/THIRD_PARTY_NOTICES.md). Reverse-engineering/source contributions from Rick Barber's ScreamerRally-Recomp are credited there. |
| `NativeRenderer/Tools/Engine/` DOSBox source modifications/build recipe | GPL-2.0-or-later; [license](NativeRenderer/Tools/Engine/LICENSE-DOSBOX), pinned upstream archive, patches and source recipe retained. The engine runs as a separate process. |
| `wrappers/*/shaders/trilogy-widescreen.glsl` | GPL-2.0-or-later, as marked by the original DOSBox Staging SPDX notices in each shader. |
| AkitaOnRails/rea-screamer-trilogy enhancement source and adapted patch recipes in `wrappers/` | MIT option; retain the [MIT license](wrappers/screamerrally/enhancement-sources/LICENSE-MIT), [pinned provenance](wrappers/screamerrally/enhancement-sources/source-metadata.json) and each wrapper's `THIRD-PARTY-NOTICES.txt`. This does not relicense those contributions under the repository default. |
| Python and other libraries in downloadable runtimes | Their respective licenses; include the actual runtime's license files and dependency inventory. These binaries are not present in the source snapshot. |

The GPL source license applies to our tools and adaptations; it grants no rights to the original games. Screamer, Screamer 2 and Screamer Rally executables, disc images, music, sounds, textures, meshes, loading screens and original icons belong to their respective rights holders. Users must supply their own authorized copies. A binary or asset appearing in another public repository is not evidence of permission to redistribute it.

## Binary releases

A public app must contain only the frontend, engine/runtime, import/extraction tools and redistributable support files. Import owned game data into private Application Support storage on the user's Mac. The locally installed complete apps and checkpoint archives include original game data and are **not public release artifacts**.

When distributing GPL-covered binaries, provide their complete corresponding source, build/install scripts, exact modifications, applicable notices and license texts under the relevant GPL terms. For the DOSBox component, retain the pinned upstream source as well as this repository's patches and recipe; a link to this repository alone is not the complete engine source. Review and include the licenses of every bundled dependency, including Python, SDL and libraries in `runtime-manifest.json`.

This source tree's MIT notices and GPL texts do not substitute for the dependency-specific notices required in a packaged app. Code signing and notarization also do not establish rights to redistribute game content.
