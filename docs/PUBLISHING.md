# Publishing the source and game-data-free apps

## What may go on GitHub

Publish this project's source, Metal shaders, launcher/import/extraction tools, DOSBox patches and build recipes, source-only tests, documentation and applicable license texts. Retain Rick Barber, AkitaOnRails and DOSBox Staging attribution and the other notices described in [LICENSING.md](../LICENSING.md).

Keep original game executables, discs, music, textures, meshes, loading art/icons, captures and data-bearing app/checkpoint archives private unless the rights holder grants redistribution permission. The same restriction applies to game assets extracted into a different format. Purchasing a game or finding its binaries in another repository does not establish redistribution permission. GOG's [sharing guidance](https://support.gog.com/hc/en-us/articles/212184489-Can-I-share-games-with-others) states that accounts and games are for personal use.

A public release can provide the frontend/runtime and import tools without game files. Users supply their own supported game copies. GPL-covered runtime binaries also need complete corresponding source and the applicable notices; see the [GNU GPL FAQ](https://www.gnu.org/licenses/gpl-faq.html#DistributingSourceIsInconvenient). For the DOSBox engine, preserve the exact pinned upstream source plus local patches/build instructions, not only the frontend source.

## Review and create a sanitized source snapshot

From the repository root:

```sh
python3 -m unittest discover -s Tools/Publication/tests -v
python3 Tools/Publication/audit_repository.py --history --report /tmp/screamer-source-audit.json
python3 Tools/Publication/export_source.py --output /tmp/ScreamerTrilogy-source.tar.gz
```

These commands do not launch games, access accounts, upload files or modify Git history. The source audit checks current tracked and new nonignored files. It rejects paths/types outside a source allowlist, binary/non-UTF-8 content, oversized files, long embedded data candidates, known credential patterns, symlinks and personal home-directory paths. The history option scans every reachable blob, including files subsequently deleted. It reports matching rule names without credential contents.

The audit is a heuristic aid, not a complete secrets or copyright review. In particular, it cannot determine the provenance of arbitrary small arrays or code snippets. Review patch provenance and license scope before publication. CI runs the same source checks on Linux using synthetic fixtures and no original game data.

Current documentation/metadata use portable path placeholders. Private historical checkpoints still contain old local machine paths; these are reported as warnings. There is no need to rewrite the working recovery history to prepare a fresh public source repository. The exporter creates a current-tree-only `.tar.gz` with `SOURCE-MANIFEST.json`, hashes and the source commit identity, and includes no `.git` directory. If starting a new public repository from this export, retain the upstream attribution/provenance records and license texts. Extract it into a separate hidden task worktree or an approved isolated staging directory; do not overwrite the working checkout. No remote repository is created automatically.

The exporter refuses an existing output file and refuses an output inside the repository. It includes nonignored new source files, so finish/review parallel edits and rerun tests before treating an export as final. Ignored local data remains ignored rather than being swept into the snapshot.

## Importing owned game files

The public app/import contract targets version **0.4.0 / build 13**. The import CLI is:

```sh
python3 NativeRenderer/Importer/import_game.py \
  --game screamer \
  --source "/path/to/owned/Screamer.app" \
  --destination "$HOME/Library/Application Support/Screamer Metal/Content" \
  --resources "/Applications/Screamer.app/Contents/Resources"
```

Game keys are `screamer`, `screamer2` and `screamerrally`. The default apps are `Screamer.app`, `Screamer 2.app` and `Screamer Rally.app`. Use the corresponding app's Resources directory. Internal support folders retain the legacy names (`Screamer Metal`, `Screamer 2 Metal`, or `Screamer Rally Metal`) to preserve existing imports, saves and settings. The source can be a supported existing GOG `.app`, an already extracted game folder, a GOG `.pkg`, or a GOG `.dmg`. Packages are expanded with `pkgutil --expand-full`; disk images are mounted read-only. Installer scripts are not executed. Raw ISO/disc images alone are not supported inputs. Rally imports require an owned supported Rally copy; availability of a download does not grant redistribution rights.

Import/extraction runs on the user's Mac and stores original data, generated loading art and native scene resources in private Application Support storage. A game-data-free release must not include that generated content, a prepopulated `Content` folder, an embedded original Classic game bundle, or game-derived icons. The public app should use its own redistributable placeholder design until import succeeds. Existing data-bearing local builders and working installed apps remain private recovery paths.

Screamer 2 also needs a supported, owned `GLIDE2X.OVL` driver. If absent, select an owned Rally folder or the driver file itself; the CLI accepts `--glide /path/to/owned/GLIDE2X.OVL`.

The bundled launcher can also import and validate without starting the engine:

```sh
"/Applications/Screamer.app/Contents/MacOS/GameLauncher" \
  --import-source "/path/to/owned/Screamer.app" \
  --support-directory "/absolute/path/to/isolated-support"
"/Applications/Screamer.app/Contents/MacOS/GameLauncher" \
  --validate-import --support-directory "/absolute/path/to/isolated-support"
```

An import runs to completion before the normal Classic/Upgraded selector. `--dry-run` reports an import requirement as JSON without opening UI or starting the game; it is mutually exclusive with import. `--support-directory` directs import/testing into a chosen isolated directory. It is not an automatic migration of existing saves.

## Building a public app candidate

On Apple Silicon macOS, build the [pinned patched engine](../NativeRenderer/Tools/Engine/README.md), install the build-time dependencies, and supply a clean official DOSBox Staging resources tree:

```sh
python3 NativeRenderer/Tools/Packaging/build_public.py \
  --engine /path/to/custom/dosbox \
  --engine-resources /path/to/official/DOSBox-Staging.app/Contents/Resources \
  --python-prefix /opt/homebrew/opt/python@3.14 \
  --output /path/to/fresh-public-build
```

The default builds all three game-data-free apps at version **0.4.0 / build 13**. The builder inspects bundled Mach-O deployment targets and declares the highest required macOS version for every app/helper. Current local candidates require **macOS 27.2**; older macOS support needs a compatible rebuild of DOSBox, Python and the dependency closure. It does not require original game data as a build input. The public apps must be inventoried separately from the complete private working copies; keep the latter for recovery.

See the import tool's `--help` and public packager's `--help` for their implemented options and current limitations. Do not label a binary release ready until import, launch, signing, corresponding-source packaging and the final no-game-data inventory have passed for that exact artifact. Notarization/Developer ID distribution remains a separate release step.
