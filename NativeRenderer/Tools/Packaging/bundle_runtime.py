#!/usr/bin/env python3
"""Embed an ARM64 DOSBox and Homebrew framework Python into a staged .app.

Does not sign the outer app; the frontend packager must do that last.
"""

import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import uuid

MACH_MAGICS = {bytes.fromhex(h) for h in ('cffaedfe', 'cefaedfe', 'feedfacf', 'feedface', 'cafebabe', 'bebafeca', 'cafebabf', 'bfbafeca')}
SYSTEM = ('/usr/lib/', '/System/Library/')


def command(*args):
    result = subprocess.run([str(a) for a in args], check=True, text=True, capture_output=True)
    return result.stdout


def macho(path):
    return path.is_file() and path.open('rb').read(4) in MACH_MAGICS


def copy_fresh(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + '.staging-' + uuid.uuid4().hex)
    shutil.copyfile(source, temporary)
    temporary.chmod(source.stat().st_mode & 0o777)
    os.replace(temporary, destination)


def rpaths(path):
    lines = command('otool', '-arch', 'arm64', '-l', path).splitlines()
    values = []
    for i, line in enumerate(lines):
        if line.strip() == 'cmd LC_RPATH':
            for following in lines[i + 1:i + 4]:
                if following.strip().startswith('path '):
                    values.append(following.strip()[5:].split(' (offset ', 1)[0])
    return values


def install_id(path):
    lines = command('otool', '-arch', 'arm64', '-D', path).splitlines()
    return next((line.strip() for line in lines if line.strip() and not line.rstrip().endswith(':') and '(architecture ' not in line), None)


def dependencies(path):
    return [line.strip().split(' (', 1)[0] for line in command('otool', '-arch', 'arm64', '-L', path).splitlines()
            if line[:1].isspace() and ' (compatibility version ' in line]


def expand(token, loader, executable):
    if token.startswith('@loader_path/'):
        return loader.parent / token[len('@loader_path/'):]
    if token.startswith('@executable_path/'):
        return executable.parent / token[len('@executable_path/'):]
    return Path(token)


def resolve_dependency(name, source, executable):
    if name.startswith(SYSTEM):
        return None
    candidates = []
    if name.startswith('@rpath/'):
        for search in rpaths(source) + rpaths(executable):
            candidates.append(expand(search, source, executable) / name[len('@rpath/'):])
    else:
        candidates.append(expand(name, source, executable))
    for candidate in candidates:
        if str(candidate).startswith(SYSTEM):
            return None
        if candidate.is_file():
            return candidate.resolve()
    raise RuntimeError(f'Cannot resolve {name} from {source}; searched {candidates}')


def python_layout(prefix):
    prefix = prefix.expanduser().resolve(strict=True)
    framework = prefix / 'Frameworks/Python.framework'
    if not framework.is_dir():
        raise RuntimeError('--python-prefix must contain Frameworks/Python.framework')
    versions = sorted(p for p in (framework / 'Versions').iterdir() if p.is_dir() and not p.is_symlink() and p.name.startswith('3.14'))
    if len(versions) != 1:
        raise RuntimeError('Expected one Python 3.14 framework version')
    version = versions[0]
    # Framework bin/python is a small launcher that posix_spawns Python.app.
    # Embed the actual interpreter directly so the private prefix is sufficient.
    executable = version / 'Resources/Python.app/Contents/MacOS/Python'
    library = version / 'Python'
    stdlib = version / 'lib/python3.14'
    if not all(p.exists() for p in (executable, library, stdlib / 'encodings')):
        raise RuntimeError('Incomplete framework Python layout')
    return prefix, version, executable.resolve(), library.resolve(), stdlib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', required=True, type=Path)
    parser.add_argument('--engine', required=True, type=Path)
    parser.add_argument('--python-prefix', required=True, type=Path)
    parser.add_argument('--engine-resources', type=Path)
    parser.add_argument('--identity', default='-', help='Nested code identity, default ad-hoc')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('This packager requires macOS install_name_tool, lipo and codesign')
    app = args.app.expanduser().resolve()
    if app.suffix != '.app':
        parser.error('--app must end in .app')
    engine = args.engine.expanduser().resolve(strict=True)
    prefix, version, python_exe, python_library, stdlib = python_layout(args.python_prefix)
    macos, resources = app / 'Contents/MacOS', app / 'Contents/Resources'
    libdir, pyroot = macos / 'lib', resources / 'Python'
    if pyroot.exists():
        raise RuntimeError('Python runtime already exists; package into a freshly staged app')
    macos.mkdir(parents=True, exist_ok=True)
    resources.mkdir(parents=True, exist_ok=True)
    libdir.mkdir(exist_ok=True)
    pyversion = pyroot / 'Python.framework/Versions/3.14'
    pyversion.mkdir(parents=True)
    shutil.copytree(stdlib, pyversion / 'lib/python3.14',
                    ignore=shutil.ignore_patterns('site-packages', '__pycache__', '*.pyc'))
    (pyversion / 'Resources').mkdir()
    shutil.copyfile(version / 'Resources/Info.plist', pyversion / 'Resources/Info.plist')
    framework = pyroot / 'Python.framework'
    (framework / 'Versions/Current').symlink_to('3.14')
    (framework / 'Python').symlink_to('Versions/Current/Python')
    (framework / 'Resources').symlink_to('Versions/Current/Resources')
    # Keep the public PYTHONHOME contract at Resources/Python. Python's usual
    # prefix/lib/python3.14 lookup follows this entirely bundle-relative link.
    (pyroot / 'lib').symlink_to('Python.framework/Versions/Current/lib')
    shutil.copyfile(prefix / 'LICENSE', pyroot / 'LICENSE')
    engine_target = macos / 'dosbox'
    python_target = pyroot / 'bin/python3.14'
    library_target = pyversion / 'Python'
    mapping = {engine: engine_target, python_exe: python_target, python_library: library_target}
    contexts = {engine: engine, python_exe: python_exe, python_library: python_exe}
    for source, destination in list(mapping.items()):
        copy_fresh(source, destination)
    for target in (pyversion / 'lib/python3.14').rglob('*'):
        if target.is_file() and not target.is_symlink() and macho(target):
            source = (stdlib / target.relative_to(pyversion / 'lib/python3.14')).resolve()
            mapping[source] = target
            contexts[source] = python_exe
    pending = collections.deque(mapping)
    edges = {}
    dynamic_dependencies = []
    while pending:
        source = pending.popleft()
        identity = install_id(source)
        edges[source] = []
        # SDL2-compat dlopens SDL3 by name; it is intentionally absent from
        # LC_LOAD_DYLIB and therefore cannot be found by an otool-only closure.
        if source.name.startswith('libSDL2-') and b'@loader_path/libSDL3.dylib' in source.read_bytes():
            # Already portable engines have no LC_RPATH entries: SDL2's
            # explicit dlopen path resolves beside its loader in that case.
            adjacent = source.parent / 'libSDL3.dylib'
            sdl3 = adjacent.resolve() if adjacent.is_file() else resolve_dependency(
                '@rpath/libSDL3.dylib', source, contexts[source])
            if sdl3 not in mapping:
                mapping[sdl3] = libdir / 'libSDL3.dylib'
                contexts[sdl3] = contexts[source]
                copy_fresh(sdl3, mapping[sdl3])
                pending.append(sdl3)
            dynamic_dependencies.append({'loader': str(mapping[source].relative_to(app)),
                                         'library': str(mapping[sdl3].relative_to(app))})
        for dependency in dependencies(source):
            if dependency == identity:
                continue
            resolved = resolve_dependency(dependency, source, contexts[source])
            if resolved is None:
                continue
            if resolved not in mapping:
                name = resolved.name
                if any(p.name == name and s != resolved for s, p in mapping.items()):
                    name = resolved.stem + '-' + hashlib.sha256(str(resolved).encode()).hexdigest()[:8] + resolved.suffix
                mapping[resolved] = libdir / name
                contexts[resolved] = contexts[source]
                copy_fresh(resolved, mapping[resolved])
                pending.append(resolved)
            edges[source].append((dependency, resolved))
    entitlements = resources / 'engine-entitlements.plist'
    entitlements.write_bytes(plistlib.dumps({'com.apple.security.cs.allow-jit': True}))
    for source, destination in mapping.items():
        architectures = command('lipo', '-archs', destination).split()
        if 'arm64' not in architectures:
            raise RuntimeError(f'No ARM64 slice: {source}: {architectures}')
        if architectures != ['arm64']:
            temporary = destination.with_name(destination.name + '.arm64')
            command('lipo', destination, '-thin', 'arm64', '-output', temporary)
            temporary.chmod(destination.stat().st_mode & 0o777)
            os.replace(temporary, destination)
        if install_id(source):
            command('install_name_tool', '-id', '@rpath/' + destination.name, destination)
        for old, resolved in edges[source]:
            relative = os.path.relpath(mapping[resolved], destination.parent)
            command('install_name_tool', '-change', old, '@loader_path/' + relative, destination)
        # Every imported non-system edge is now explicit @loader_path. Do not
        # retain Homebrew's relative paths that can also escape the app bundle.
        for search in rpaths(destination):
            command('install_name_tool', '-delete_rpath', search, destination)
    for destination in sorted(set(mapping.values()), key=lambda p: len(p.parts), reverse=True):
        invocation = ['codesign', '--force', '--sign', args.identity]
        if destination == engine_target:
            invocation += ['--entitlements', entitlements]
        command(*invocation, destination)
        command('codesign', '--verify', '--strict', destination)
        for dependency in dependencies(destination):
            if dependency == install_id(destination) or dependency.startswith(SYSTEM):
                continue
            if not dependency.startswith('@loader_path/'):
                raise RuntimeError(f'Nonportable load command in {destination}: {dependency}')
            if not (destination.parent / dependency[len('@loader_path/'):]).resolve().is_file():
                raise RuntimeError(f'Missing bundled dependency in {destination}: {dependency}')
    command('codesign', '--force', '--sign', args.identity, framework)
    command('codesign', '--verify', '--deep', '--strict', framework)
    engine_resources = args.engine_resources
    if engine_resources is None:
        engine_resources = next((p for p in (engine.parent / 'Resources', engine.parent.parent / 'Resources') if p.is_dir()), None)
    if engine_resources:
        source_resources = engine_resources.resolve()
        if source_resources != resources.resolve():
            for source in source_resources.rglob('*'):
                if source.is_file():
                    destination = resources / source.relative_to(source_resources)
                    if destination.exists() and source.read_bytes() != destination.read_bytes():
                        raise RuntimeError(f'Engine resource conflicts with app resource: {destination}')
                    if not destination.exists():
                        copy_fresh(source, destination)
    configuration = {
        'schema_version': 1,
        'engine': 'Contents/MacOS/dosbox',
        'python': 'Contents/Resources/Python/bin/python3.14',
        'python_home': 'Contents/Resources/Python',
        'python_environment': {'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1'},
        'nested_code_signed': True, 'outer_app_signing_required': True,
        'dynamic_dependencies': dynamic_dependencies,
        'binaries': [{'source': str(s), 'path': str(d.relative_to(app))} for s, d in mapping.items()],
    }
    (resources / 'runtime-manifest.json').write_text(json.dumps(configuration, indent=2) + '\n')
    print(json.dumps({'app': str(app), 'engine': str(engine_target), 'python': str(python_target),
                      'python_home': str(pyroot), 'bundled_macho_files': len(mapping),
                      'manifest': str(resources / 'runtime-manifest.json')}, indent=2))


if __name__ == '__main__':
    main()
