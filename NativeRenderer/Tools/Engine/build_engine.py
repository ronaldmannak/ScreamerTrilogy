#!/usr/bin/env python3
"""Build the pinned ARM64 DOSBox engine with the local live-game bridge."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

VERSION = '0.83.1'
ARCHIVE_SHA256 = '14c3703369e56125a425aea8ebb1a425823df58f9769f3e48b1b8ebbf2c6cf09'
PATCH_HASHES = {
    'system-libs.patch': '838fe6ea1ba409d33b3301d5f53b9a8c80893e3754c208f4d62e689035228891',
    'zlib-1.patch': 'aecb0c7cc96de7acb862bd3b850ecbf79b5bb5dd379012586eb68f8f3495f457',
    'zlib-2.patch': '219438a2110b49f0a9b62e0e547c35db7cdce3f7fa40feb5d529529fe07fe5bb',
    'rally-bridge.patch': '8bc6421e964d32b032f2c513648ca8356ca64571c4f989a13d956a97a17fd3ec',
    'unified-engine.patch': 'd0d00379b52fde1367af55ee04e721a40e04bcc6f6b52366c40a97150ff1ab9f',
    's1-conventional-hud.patch': 'ec1e58fa4333fa92b7ff2ce6fedae7a57d64bed8b034e4edcfd3b40b2d4617b4',
    's1-display-hud.patch': '47abdc390c1276681a461f01c055846dcb58dc23fb3f9c37d2fed1bdcc6a1c49',
    's1-hud-cohort.patch': 'bdd528e4fdfdda68a430f9a199b86093c3fd680cbbaec294beeff7172063448e',
    's2-hud-coverage.patch': '8000e231f47d61422488c1c58f0d7bd2ebc6ab03e61d339f68d9da9b83fd699f',
    's1-minimap-shade.patch': '2a341b2b660c0b3e6ab77fe4b17ba72cef6be85619a9c6eecf483144828d141c',
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*arguments, **kwargs):
    subprocess.run(list(map(str, arguments)), check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='Fresh build directory')
    parser.add_argument('--archive', type=Path, help='Optional previously downloaded official archive')
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    output = args.output.expanduser().resolve()
    if output.exists():
        parser.error('--output must not exist')
    for name, expected in PATCH_HASHES.items():
        if sha256(root / name) != expected:
            parser.error('Pinned engine patch hash mismatch: ' + name)
    output.mkdir(parents=True)
    archive = output / 'dosbox.tar.gz'
    if args.archive:
        shutil.copyfile(args.archive, archive)
    else:
        url = f'https://github.com/dosbox-staging/dosbox-staging/archive/refs/tags/v{VERSION}.tar.gz'
        with urllib.request.urlopen(url, timeout=60) as response, archive.open('wb') as destination:
            shutil.copyfileobj(response, destination)
    if sha256(archive) != ARCHIVE_SHA256:
        raise RuntimeError('Official source archive hash mismatch')
    # The archive is pinned above; still refuse paths/links escaping the staging root.
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            destination = (output / member.name).resolve()
            destination.relative_to(output)
            if member.issym() or member.islnk():
                target = (destination.parent / member.linkname).resolve() if member.issym() else (output / member.linkname).resolve()
                target.relative_to(output)
            if member.isdev() or member.isfifo():
                raise RuntimeError('Unexpected special archive member')
        bundle.extractall(output)
    source = output / f'dosbox-staging-{VERSION}'
    for name in PATCH_HASHES:
        run('patch', '-p1', '-i', root / name, cwd=source)
    manifest = {'version': VERSION, 'archive_sha256': ARCHIVE_SHA256,
                'patches': {name: sha256(root / name) for name in PATCH_HASHES}}
    (output / 'build-provenance.json').write_text(json.dumps(manifest, indent=2) + '\n')
    if args.prepare_only:
        print(source)
        return
    build = output / 'build'
    run('cmake', '-S', source, '-B', build, '-G', 'Ninja', '-DOPT_TESTS=OFF',
        '-DUSE_SYSTEM_LIBS=ON', '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_OSX_ARCHITECTURES=arm64',
        '-DCMAKE_EXE_LINKER_FLAGS=-Wl,-rpath,/opt/homebrew/opt/libslirp/lib -Wl,-undefined,dynamic_lookup')
    run('cmake', '--build', build, '--parallel', min(os.cpu_count() or 4, 8))
    print(build / 'dosbox')


if __name__ == '__main__':
    main()
