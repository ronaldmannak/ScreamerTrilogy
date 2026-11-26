#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Validate exported original scene buffers and material/texture references."""
from array import array
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys


def local_file(directory, name):
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError('Artifact file must use a relative path')
    path = (directory / name).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError('Artifact path escapes its directory')
    return path


def checked_blob(directory, name, expected_size, expected_hash):
    path = local_file(directory, name)
    if path.stat().st_size != expected_size:
        raise ValueError(f'Buffer size does not match scene metadata: {name}')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_hash:
        raise ValueError(f'Artifact hash mismatch: {name}')
    return data


def validate_scene(path):
    path = Path(path)
    if not 0 < path.stat().st_size <= 32 * 1024 * 1024:
        raise ValueError('Scene descriptor exceeds its size bound')
    scene = json.loads(path.read_text())
    directory = path.parent
    if scene.get('schema') != 'screamer-scene/v1':
        raise ValueError('Unsupported scene schema')
    v, i = scene['vertices'], scene['indices']
    if (v['stride'] != 36 or v['format'] != 'float32-le'
            or i['format'] != 'uint32-le' or not 0 < v['count'] <= 3000000
            or not 0 < i['count'] <= 18000000 or i['count'] % 3):
        raise ValueError('Invalid vertex/index layout or count')
    hashes = scene['files_sha256']
    vertex_bytes = checked_blob(directory, v['file'], v['count'] * 36, hashes[v['file']])
    index_bytes = checked_blob(directory, i['file'], i['count'] * 4, hashes[i['file']])
    vertices = array('f'); vertices.frombytes(vertex_bytes)
    indices = array('I'); indices.frombytes(index_bytes)
    if sys.byteorder != 'little':
        vertices.byteswap(); indices.byteswap()
    if any(not math.isfinite(value) for value in vertices) or max(indices) >= v['count']:
        raise ValueError('Invalid finite coordinates or out-of-range vertex index')
    textures = scene.get('textures', [])
    for texture in textures:
        p = local_file(directory, texture['path'])
        if p.stat().st_size > 4 * 1024 * 1024:
            raise ValueError('Texture exceeds its size bound')
        png = p.read_bytes()
        if (png[:8] != b'\x89PNG\r\n\x1a\n'
                or struct.unpack_from('>II', png, 16) != (texture['width'], texture['height'])
                or hashlib.sha256(png).hexdigest() != texture['sha256']):
            raise ValueError('PNG dimensions/hash mismatch')
        if 'rgba_file' in texture:
            checked_blob(directory, texture['rgba_file'], texture['width'] * texture['height'] * 4,
                         texture['rgba_sha256'])
    ranges, unresolved = [], []
    for batch in scene['batches']:
        begin, length = batch['first_index'], batch['index_count']
        if type(begin) is not int or type(length) is not int or begin < 0 or length <= 0 or begin % 3 or length % 3 or begin + length > len(indices):
            raise ValueError('Invalid triangle batch range')
        texture = batch.get('texture')
        if texture is not None and (type(texture) is not int or not 0 <= texture < len(textures)):
            raise ValueError('Out-of-range texture reference')
        if batch.get('mode') is None:
            unresolved.append({'material': batch.get('material_address'), 'issue': 'unknown material mode'})
        elif batch.get('mode') != 2 and texture is None:
            unresolved.append({'material': batch.get('material_address'), 'issue': 'missing texture'})
        ranges.append((begin, begin + length))
    end = 0
    for begin, stop in sorted(ranges):
        if begin != end:
            raise ValueError('Batch ranges overlap or leave unused indices')
        end = stop
    if end != len(indices):
        raise ValueError('Batch ranges do not cover the index buffer')
    instances = scene.get('dynamic_instances', [])
    identifiers = {item['id'] for item in instances}
    if len(identifiers) != len(instances):
        raise ValueError('Duplicate dynamic instance IDs')
    for instance in instances:
        if type(instance['model']) is not int or not 0 <= instance['model'] < 4096:
            raise ValueError('Invalid car model guard')
        actual = [n for n, batch in enumerate(scene['batches']) if batch.get('instance_id') == instance['id']]
        if actual != instance['batch_indices'] or not actual:
            raise ValueError('Car instance batches do not match their root IDs')
    result = {'scene': str(path), 'vertices': v['count'], 'triangles': len(indices) // 3,
              'textures': len(textures), 'batches': len(ranges), 'cars': len(instances),
              'unresolved_materials': unresolved, 'valid': not unresolved}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scene', type=Path)
    args = parser.parse_args()
    result = validate_scene(args.scene)
    print(json.dumps(result, indent=2))
    if not result['valid']:
        sys.exit(1)
