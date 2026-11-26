# Importing owned game data

The public apps contain renderer/runtime code and tools. They do not contain original DOS executables, disc images, textures, music, loading artwork or pre-exported scenes. On first launch, each app copies a supported installation supplied by its user into that app's Application Support directory. The source files remain unchanged.

Supported selections are an installed GOG/wrapper `.app`, an extracted DOS installation folder, a GOG macOS `.pkg`, or a `.dmg` containing an installation or package. Packages are expanded with `pkgutil --expand-full`; installer scripts are never executed. Disk images are mounted read-only. Importing requires neither Xcode nor Rosetta.

Only the recognized original versions whose checksums are listed in `import_game.py` are supported. A raw CD image alone does not contain the required installed DOS layout; extract/install the DOS data first. Windows GOG installers, archives and alternative game revisions are not currently handled by the importer.

For Screamer and Screamer 2, the installation needs its DOS program, data directories and original CD cue/image pair (`SCREAM.DAT` / `SCREAM.gog`, or `GAME.DAT` / `GAME.GOG`). Rally needs a folder containing `SR/` and `cd/srally.cue` plus `cd/srally.img`. The code validates both Classic and Upgraded executable versions before copying.

Screamer 2 Upgraded also needs the recognized genuine DOS `GLIDE2X.OVL` driver. If the selected installation lacks it, the import screen asks for an owned driver file or an owned Rally `.app`/folder containing it. The importer copies that driver locally and does not download or redistribute it.

A successful import contains:

- `game/`: the user's original DOS installation and disc data.
- `SelectionBackground.png`: original loading artwork decoded locally from the user's files.
- `S1Scenes/track1` through `track6` for Screamer: original scene data exported locally without running the game.
- `manifest.json`: completion record, file sizes and SHA-256 hashes.

The importer rejects symbolic links, special files, ambiguous DOS filenames and cue references outside the copied disc folder. It verifies recognized executables, required archives and the disc image before publishing the import. Files are staged beside the destination and published only after validation; failures and cancellation remove staging and preserve any previous completed import. Imported DOS code is never executed by the importer.

The application bundle stays immutable. Saves and writable game sessions remain separate from `Content/`.

## Command line

The app uses its private Python runtime; developers may use Python 3.9 or later from the source checkout:

```sh
python3 -B NativeRenderer/Importer/import_game.py \
  --game screamer \
  --source '/path/to/owned/Screamer.app' \
  --destination '/path/to/private/support/Content' \
  --resources '/path/to/public/Screamer.app/Contents/Resources'
```

Add `--glide '/path/to/owned/GLIDE2X.OVL'` for Screamer 2 when needed. `--probe` checks a selected source without copying. `--validate` instead checks an existing `--destination`, with no `--source` required. Startup validation checks recorded file sizes and hashes of critical executables/archives; `--deep` additionally hashes every imported file, including CD images. Every successful or failed operation prints one JSON result with `ok`, `game`, `content_root`, `error_code` and `message`; success exits 0, a handled failure exits 2.

Tests use synthetic data and contain no original game payloads:

```sh
python3 -B -m unittest discover -s NativeRenderer/Importer -p 'test_*.py' -v
```
