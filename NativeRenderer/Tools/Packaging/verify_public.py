#!/usr/bin/env python3
"""Reject original game payloads in source-built public app candidates.

The public builder starts from source and copies only explicit runtime inputs.
This independent check catches known game asset paths/formats and proves that
its sole bootstrap mesh is our authored, untextured loading placeholder. It is
an additional packaging check, not a copyright scanner for arbitrary files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

GAME_EXTENSIONS = {'.exe', '.gog', '.img', '.iso', '.cue', '.ovl', '.pcx', '.bkk', '.lbm', '.mlb', '.unr'}
GAME_DIRS = {'game', 'cars', 's1scenes', 'replay', 'textures', 'captures'}
GAME_NAMES = {'gameicon.icns', 'selectionbackground.png', 'scream.dat', 'game.dat'}
BOOTSTRAP_FILES = {
    'vertices.bin': b''.join(struct.pack('<9f', *p, 0., 0., .04, .04, .06, 1.)
                           for p in [(-1., -1., 0.), (1., -1., 0.), (0., 1., 0.)]),
    'indices.bin': struct.pack('<3I', 0, 1, 2),
}


def verify_public(app):
    app = Path(app).resolve(strict=True)
    resources = app / 'Contents/Resources'
    profile = json.loads((resources / 'SelectionConfig.json').read_text())
    if profile.get('requires_import') is not True or profile.get('game') not in ('screamer', 'screamer2', 'screamerrally'):
        raise ValueError('App must require an owned-game import')
    scene = resources / 'Scene'
    if set(p.name for p in scene.iterdir()) != {'scene.json', *BOOTSTRAP_FILES}:
        raise ValueError('Public bootstrap contains unexpected files')
    metadata = json.loads((scene / 'scene.json').read_text())
    if metadata.get('schema') != 'screamer-public-bootstrap/v1' or metadata.get('textures') != []:
        raise ValueError('Public bootstrap must be an authored, untextured placeholder')
    for name, expected in BOOTSTRAP_FILES.items():
        if (scene / name).read_bytes() != expected:
            raise ValueError('Public bootstrap mesh differs from authored source: ' + name)
    files = []
    for path in sorted(app.rglob('*')):
        relative = path.relative_to(app)
        if path.is_symlink():
            try:
                path.resolve(strict=True).relative_to(app)
            except (ValueError, FileNotFoundError) as exc:
                raise ValueError('App symlink escapes its bundle: ' + str(relative)) from exc
            continue
        if any(part.lower() in GAME_DIRS for part in relative.parts) or path.name.lower() in GAME_NAMES:
            raise ValueError('Original game content path in public app: ' + str(relative))
        if not path.is_file():
            continue
        if path.suffix.lower() in GAME_EXTENSIONS:
            raise ValueError('Original game format in public app: ' + str(relative))
        if path.suffix.lower() == '.bin' and (path.parent != scene or path.name not in BOOTSTRAP_FILES):
            raise ValueError('Unrecognized binary asset in public app: ' + str(relative))
        if '_CodeSignature' in relative.parts:
            continue
        files.append({'path': str(relative), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    return {'schema': 'screamer-public-verification/v1', 'game': profile['game'],
            'requires_import': True, 'original_game_payloads_found': False,
            'bootstrap': 'authored untextured triangle', 'file_count': len(files), 'files': files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', type=Path)
    parser.add_argument('--manifest', type=Path, help='Write an external verification report')
    args = parser.parse_args()
    try:
        result = verify_public(args.app)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, str(error) + '\n')
    if args.manifest:
        args.manifest.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'files'}, indent=2))


if __name__ == '__main__':
    main()
