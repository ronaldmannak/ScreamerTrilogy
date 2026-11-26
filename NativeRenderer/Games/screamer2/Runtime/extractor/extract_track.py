#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Extract actual Screamer 2 S2_3DFX world geometry from an immutable DOS RAM snapshot.

The data layouts and transform rules follow Rick-Barber/ScreamerRally-Recomp's
documented reverse engineering and its GPL-3.0 native world/extract implementation.
This is an independent Python implementation, not a replacement game executable.
It reads a saved snapshot only and never connects to or writes to the running game.
"""

from array import array
from collections import Counter
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import sys
import uuid


PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / 'bridge'))

from extractor_profile import DEFAULT_PROFILE, load_profile

EXPECTED_EXE_SHA256 = DEFAULT_PROFILE['executable_sha256']
LINKS = DEFAULT_PROFILE['links']
SETUP_MODES = DEFAULT_PROFILE['setup_modes']
MAX_VERTICES_PER_PART = 8192
MAX_MODELS = 4096
MAX_POLYGON_ORDER = 65536
MAX_WORLD_OBJECTS = 100000
MAX_OUTPUT_VERTICES = 3000000


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def triple(reader, address, method='i32'):
    read = getattr(reader, method)
    width = 2 if method in {'i16', 'rd16'} else 4
    return [read(address + width * i) for i in range(3)]


def rotation(angles):
    # Row-major local->parent matrix. World is left-handed, with Y increasing up.
    a, b, c = [(angle & 2047) * math.tau / 2048 for angle in angles]
    sa, ca, sb, cb, sc, cc = math.sin(a), math.cos(a), math.sin(b), math.cos(b), math.sin(c), math.cos(c)
    return [[cc * cb - sc * sb * sa, -cc * sb * sa - sc * cb, -ca * sb],
            [sc * ca, cc * ca, -sa],
            [sc * cb * sa + cc * sb, cc * cb * sa - sc * sb, cb * ca]]


def apply_transform(matrix, translation, point):
    return [sum(matrix[row][column] * point[column] for column in range(3)) + translation[row]
            for row in range(3)]


def color565(value):
    r, g, b = (value >> 11) & 31, (value >> 5) & 63, value & 31
    return [((r << 3) | (r >> 2)) / 255, ((g << 2) | (g >> 4)) / 255,
            ((b << 3) | (b >> 2)) / 255, 1.0]


def write_array(path, values):
    if sys.byteorder != 'little':
        values.byteswap()
    with Path(path).open('wb') as stream:
        values.tofile(stream)


class TrackExtractor:
    def __init__(self, memory, *, with_textures=False, profile=None):
        self.profile = profile or DEFAULT_PROFILE
        if memory.executable_sha256 != self.profile["executable_sha256"]:
            raise ValueError("Snapshot executable does not match the selected extractor profile")
        self.links = self.profile["links"]
        self.setup_modes = self.profile["setup_modes"]
        self.memory = memory
        self.model_table = memory.pointer(memory.link(self.links['models']))
        self.rows = memory.pointer(memory.link(self.links['rows']))
        self.clock = memory.rd32(memory.link(self.links['clock']))
        self.model_pointers = []
        self.models = {}
        self.parts = {}
        self.materials = {}
        self.warnings = []
        self.counts = Counter()
        self.camera = self.read_camera()
        self.vertices = array('f')
        self.indices = array('I')
        self.instances = []
        self.bounds_min = [math.inf] * 3
        self.bounds_max = [-math.inf] * 3
        self.mode_counts = Counter()
        self.material_index_counts = Counter()
        self.with_textures = with_textures
        self.textures = []
        self.texture_indices = {}
        self.texture_statistics = {}
        self.batch_indices = {}
        self.batch_metadata = {}
        self.keyed_texture_indices = {}
        self.blended_texture_indices = {}
        self.output = None
        self.current_instance_id = None

    def warn(self, message):
        self.counts['warning_count'] += 1
        if len(self.warnings) < 100:
            self.warnings.append(str(message))

    def read_camera(self):
        r = self.memory
        try:
            p = r.pointer(r.link(self.links['camera']))
            if not p or not r.readable(p, 112):
                return None
            words = [r.i32(p + 4 * i) for i in range(28)]
            return {'address': p, 'angles': words[:3], 'position': words[3:6],
                    'matrixQ14': words[6:15], 'transposeQ14': words[18:27],
                    'source': 'original game camera structure, not a generated camera'}
        except (ValueError, IndexError, KeyError):
            return None

    def read_models(self):
        r = self.memory
        for index in range(MAX_MODELS):
            raw = r.rd32(self.model_table + 4 * index)
            if raw == 0xffffffff:
                self.counts['model_table_entries'] = index
                return
            self.model_pointers.append(r.translate_pointer(raw))
        raise ValueError('Model table is not terminated within 4096 entries')

    def libraries(self):
        r = self.memory
        records = []
        base = r.link(self.links['libraries'])
        for index in range(32):
            address = base + index * 0x2c
            data = r.pointer(address)
            if not data:
                continue
            name = r.bytes(address + 8, 16).split(b'\0')[0].decode('ascii', errors='replace')
            records.append({'slot': index, 'name': name, 'data_address': data})
        return records

    def model(self, index):
        if index in self.models:
            return self.models[index]
        if not 0 <= index < len(self.model_pointers):
            raise ValueError(f'Object references invalid model index {index}')
        r = self.memory
        address = self.model_pointers[index]
        if not r.readable(address, 0xc6):
            raise ValueError(f'Model {index} at {address:#x} is not readable')
        count = r.rd32(address + 0x14)
        if not 0 < count <= 13:
            raise ValueError(f'Model {index} has implausible part count {count}')
        result = dict(index=index, address=address, parts=count,
                      animation_frames=r.i32(address + 0x10),
                      material_base=r.pointer(address + 0xb4),
                      levels=[[r.rd32(address + 0x18 + 0x34 * level + 4 * slot)
                               for slot in range(13)] for level in range(3)])
        self.models[index] = result
        return result

    def part(self, model, offset):
        r = self.memory
        address = model['address'] + offset
        key = (model['address'], address)
        if key in self.parts:
            return self.parts[key]
        if not r.readable(address, 0x78):
            raise ValueError(f'Part header at {address:#x} is not readable')
        vertex_address = model['address'] + r.rd32(address + 0x1c)
        vertices = []
        for index in range(MAX_VERTICES_PER_PART):
            at = vertex_address + 6 * index
            x = r.i16(at)
            if x == 0x7fff:
                break
            vertices.append([x, r.i16(at + 2), r.i16(at + 4)])
        else:
            raise ValueError(f'Unterminated vertex table at {vertex_address:#x}')
        orders = [r.rd32(address + 0x28 + 4 * i) for i in range(16)]
        polygon_addresses = set()
        for offset in orders:
            if not offset:
                continue
            for index in range(MAX_POLYGON_ORDER):
                value = r.i16(address + offset + 2 * index)
                if value <= 0:
                    break
                polygon_addresses.add(address + value)
            else:
                raise ValueError(f'Unterminated polygon order at {address + offset:#x}')
        polygons = []
        for record in sorted(polygon_addresses):
            n = r.rd16(record + 6)
            if not 3 <= n <= 64:
                raise ValueError(f'Invalid polygon vertex count {n} at {record:#x}')
            offsets = [r.rd16(record + 8 + 2 * i) for i in range(n)]
            if any(value % 6 or value // 6 >= len(vertices) for value in offsets):
                raise ValueError(f'Invalid vertex reference in polygon {record:#x}')
            polygons.append({'address': record, 'material': r.i16(record + 4),
                             'vertices': [value // 6 for value in offsets],
                             'color565': r.rd16(record + 2)})
        uv_offset = r.rd32(address + 0x24)
        uv_address = model['address'] + uv_offset
        has_uv = bool(uv_offset) and r.readable(uv_address, len(vertices) * 6)
        uv = [[r.i16(uv_address + 6 * i) / 256, r.i16(uv_address + 6 * i + 2) / 256]
              if has_uv else [0.0, 0.0] for i in range(len(vertices))]
        name = r.bytes(address + 0x68, 16).split(b'\0')[0].decode('ascii', errors='replace')
        result = dict(address=address, vertices=vertices, uv=uv, polygons=polygons, name=name)
        self.parts[key] = result
        self.counts['unique_parts'] += 1
        self.counts['unique_part_vertices'] += len(vertices)
        self.counts['unique_part_polygons'] += len(polygons)
        return result

    def placement(self, model, slot):
        r = self.memory
        level_zero = model['address'] + model['levels'][0][slot]
        address = model['address'] + r.rd32(level_zero + 0xc)
        if model['animation_frames'] >= 0:
            # Capture the actual loaded animation phase. This prototype freezes it.
            frame = ((model['animation_frames'] * self.clock) & 0xffffffff) >> 16
            at = address + 0x1c + frame * 0x30
            values = [r.i16(at + 2 * i) for i in range(12)]
            matrix = [[values[row + 3 * col] / 16384 for col in range(3)] for row in range(3)]
            return matrix, values[9:12]
        return rotation(triple(r, address + 4)), triple(r, address + 0x10)

    def material(self, model, offset):
        address = model['material_base'] + offset
        if address in self.materials:
            return self.materials[address]
        r = self.memory
        kind = r.rd32(address)
        mode = None
        if not kind & 15 and kind < 0x200:
            routine = r.pointer(r.link(self.links['dispatch']) + kind)
            try:
                mode = self.setup_modes.get(r.to_link(routine))
            except (ValueError, KeyError):
                pass
        frames = []
        frame_base, frame_material = model['material_base'], address
        if mode == 5:
            environment = r.pointer(r.link(self.links['environment']))
            if environment:
                frame_base = frame_material = environment
        frame_offset = r.rd32(frame_material + 4)
        if mode != 2 and frame_offset:
            pointer = frame_base + frame_offset
            n = r.rd32(pointer)
            if n <= 256 and r.readable(pointer + 8, 4 * n):
                frames = [r.rd32(pointer + 8 + 4 * i) for i in range(n)]
        result = dict(address=address, type=kind, mode=mode, texture_records=frames)
        self.materials[address] = result
        return result

    def objects(self):
        r = self.memory
        count = 0
        if not self.rows or not r.readable(self.rows, 1024):
            raise ValueError(f'World row table {self.rows:#x} is not readable')
        for row in range(256):
            raw_row = r.rd32(self.rows + 4 * row)
            if raw_row in (0, 0xffffffff):
                continue
            rp = r.translate_pointer(raw_row)
            for col in range(256):
                raw_cell = r.rd32(rp + 4 * col)
                if raw_cell in (0, 0xffffffff):
                    continue
                cp = r.translate_pointer(raw_cell)
                self.counts['cells'] += 1
                for listing in (0, 1):
                    base = r.pointer(cp + 4 * listing)
                    n = r.rd32(cp + 0x14 + 4 * listing)
                    if n > MAX_WORLD_OBJECTS or count + n > MAX_WORLD_OBJECTS:
                        raise ValueError(f'Implausible world object count in cell ({row},{col})')
                    if n and not r.readable(base, n * 0x40):
                        raise ValueError(f'Object list in cell ({row},{col}) is not readable')
                    for index in range(n):
                        address = base + 0x40 * index
                        count += 1
                        self.counts[f'objects_list_{listing}'] += 1
                        yield dict(id=f'cell:{row}:{col}:{listing}:{index}', address=address,
                                   cell=[row, col], listing=listing, model=r.rd32(address),
                                   flags=r.rd32(address + 4), position=triple(r, address + 8),
                                   angles=triple(r, address + 0x14), animation=r.i32(address + 0x20))
        self.counts['world_objects'] = count

    def add_object(self, obj):
        model = self.model(obj['model'])
        angles = obj['angles']
        if obj['flags'] & 0x8000:
            self.counts['frozen_billboards'] += 1
            camera_angles = self.camera['angles'] if self.camera else [0, 0, 0]
            angles = [(angles[0] - camera_angles[0]) & 2047,
                      -(angles[1] - camera_angles[1] + 1024) & 2047,
                      2047 - camera_angles[2]]
        object_rotation = rotation(angles)
        first_index = len(self.indices)
        part_names = []
        for slot in range(model['parts']):
            available = [(level, model['levels'][level][slot]) for level in range(3)
                         if model['levels'][level][slot]]
            if not available:
                continue
            level, offset = available[0]
            self.counts[f'parts_lod_{level}'] += 1
            part = self.part(model, offset)
            part_names.append(part['name'])
            part_rotation, translation = self.placement(model, slot)
            world_vertices = [apply_transform(object_rotation, obj['position'],
                                             apply_transform(part_rotation, translation, vertex))
                              for vertex in part['vertices']]
            for polygon in part['polygons']:
                material = self.material(model, polygon['material'])
                mode = material['mode']
                self.mode_counts[str(mode)] += 1
                frames = material['texture_records']
                phase = self.clock & 0x3fff if obj['animation'] < 0 else (
                    (obj['animation'] & 0xffff) >> 2 if obj['animation'] & 0x60000 else obj['animation'] >> 2)
                frame = max(0, min(len(frames) - 1, (len(frames) * phase) >> 14)) if frames else 0
                texture = self.texture_indices.get(frames[frame]) if frames else None
                if self.with_textures and texture is not None and mode == 1:
                    from texture_decode import export_keyed_variant
                    record = frames[frame]
                    if record not in self.keyed_texture_indices:
                        self.keyed_texture_indices[record] = len(self.textures)
                        self.textures.append(export_keyed_variant(self.memory, self.output, self.textures[texture], records=self.links["textures"]))
                    texture = self.keyed_texture_indices[record]
                elif self.with_textures and texture is not None and mode in (3, 6, 7):
                    from texture_decode import export_blended_variant
                    record = frames[frame]
                    if record not in self.blended_texture_indices:
                        self.blended_texture_indices[record] = len(self.textures)
                        self.textures.append(export_blended_variant(self.memory, self.output, self.textures[texture], records=self.links["textures"]))
                    texture = self.blended_texture_indices[record]
                # Explicit diagnostic flat colours until texture PNG export is enabled.
                rgba = color565(polygon['color565']) if mode == 2 else (
                    [1.0, 1.0, 1.0, 1.0] if self.with_textures and texture is not None else
                    [0.49, 0.43, 0.33, 1.0] if obj['listing'] == 0 else [0.36, 0.53, 0.32, 1.0])
                start = len(self.vertices) // 9
                if start + len(polygon['vertices']) > MAX_OUTPUT_VERTICES:
                    raise ValueError('Output exceeds the bounded three-million-vertex budget')
                for index in polygon['vertices']:
                    position = world_vertices[index]
                    if not all(math.isfinite(value) and abs(value) < 10000000 for value in position):
                        raise ValueError(f'Implausible transformed vertex in object {obj["id"]}')
                    self.vertices.extend(position + part['uv'][index] + rgba)
                    for axis in range(3):
                        self.bounds_min[axis] = min(self.bounds_min[axis], position[axis])
                        self.bounds_max[axis] = max(self.bounds_max[axis], position[axis])
                batch_key = (material['address'], texture, self.current_instance_id)
                if self.with_textures:
                    if batch_key not in self.batch_indices:
                        self.batch_indices[batch_key] = array('I')
                        self.batch_metadata[batch_key] = {'material_address': material['address'],
                            'texture': texture, 'mode': mode, 'alpha_test': mode == 1,
                            'blend': mode in (3, 6, 7)}
                        if self.current_instance_id is not None:
                            self.batch_metadata[batch_key]['instance_id'] = self.current_instance_id
                        if mode == 5:
                            self.batch_metadata[batch_key]['texgen'] = 'reflection'
                for corner in range(1, len(polygon['vertices']) - 1):
                    triangle = (start, start + corner, start + corner + 1)
                    self.indices.extend(triangle)
                    if self.with_textures:
                        self.batch_indices[batch_key].extend(triangle)
                self.material_index_counts[material['address']] += (len(polygon['vertices']) - 2) * 3
                self.counts['emitted_polygons'] += 1
        self.instances.append({**obj, 'part_names': part_names,
                               'first_index': first_index, 'index_count': len(self.indices) - first_index})
        self.counts['objects_with_geometry'] += int(len(self.indices) > first_index)

    def extract(self, output, provenance):
        output.mkdir(parents=True, exist_ok=False)
        self.output = output
        if self.with_textures:
            from texture_decode import export_textures
            self.textures, self.texture_indices, self.texture_statistics = export_textures(self.memory, output, records=self.links["textures"], record_count=self.profile["texture_record_count"])
        self.read_models()
        for obj in self.objects():
            self.add_object(obj)
        if not self.indices or not self.instances:
            raise ValueError('Snapshot contains no usable world geometry')
        if len(self.indices) % 3 or max(self.indices) >= len(self.vertices) // 9:
            raise ValueError('Internal index validation failed')
        if array('f').itemsize != 4 or array('I').itemsize != 4:
            raise ValueError('Expected four-byte native float and unsigned integer')
        batches = [{'first_index': 0, 'index_count': len(self.indices), 'texture': None}]
        if self.with_textures:
            grouped = array('I')
            batches = []
            for key in sorted(self.batch_indices, key=str):
                indices = self.batch_indices[key]
                batches.append({**self.batch_metadata[key], 'first_index': len(grouped), 'index_count': len(indices)})
                grouped.extend(indices)
            if len(grouped) != len(self.indices):
                raise ValueError('Texture grouping changed the triangle count')
            self.indices = grouped
            for instance in self.instances:
                instance['source_order_first_index'] = instance.pop('first_index')
                instance['source_order_index_count'] = instance.pop('index_count')
        write_array(output / 'vertices.bin', self.vertices)
        write_array(output / 'indices.bin', self.indices)
        scene = {
            'schema': 'screamer-scene/v1', 'title': self.profile['title'] + ': captured original track',
            'prototype': 'Static high-LOD world geometry only; not a playable game.',
            'provenance': provenance,
            'coordinates': {'handedness': 'left', 'up': '+Y', 'units': 'original game world units',
                            'vertices': 'absolute world positions', 'winding': 'original polygon order'},
            'vertices': {'file': 'vertices.bin', 'count': len(self.vertices) // 9,
                         'stride': 36, 'format': 'float32-le',
                         'attributes': {'position': {'offset': 0, 'components': 3},
                                        'uv': {'offset': 12, 'components': 2},
                                        'rgba': {'offset': 20, 'components': 4}}},
            'indices': {'file': 'indices.bin', 'count': len(self.indices), 'format': 'uint32-le'},
            'batches': batches,
            'textures': self.textures, 'texture_statistics': self.texture_statistics,
            'materials': list(self.materials.values()),
            'loaded_libraries': self.libraries(),
            'bounds': {'min': self.bounds_min, 'max': self.bounds_max},
            'camera': self.camera, 'instances': self.instances,
            'statistics': {**dict(self.counts), 'vertices': len(self.vertices) // 9,
                           'triangles': len(self.indices) // 3,
                           'materials': len(self.materials), 'material_modes': dict(self.mode_counts)},
            'warnings': self.warnings,
            'limitations': [('Original retained textures and UVs; one captured animation phase.' if self.with_textures
                             else 'Flat diagnostic colours except original RGB565 flat polygons.'),
                            'No moving cars, HUD, sky, audio, controls, or live interpolation.',
                            'Any animated scenery and billboards are frozen at snapshot time.'],
        }
        scene['files_sha256'] = {name: file_sha256(output / name) for name in ('vertices.bin', 'indices.bin')}
        if self.with_textures:
            scene['texture_statistics']['png_variants'] = len(self.textures)
            scene['texture_statistics']['keyed_variants'] = len(self.keyed_texture_indices)
            scene['texture_statistics']['blended_variants'] = len(self.blended_texture_indices)
        (output / 'scene.json').write_text(json.dumps(scene, indent=2) + '\n')
        return scene


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ram', type=Path, required=True)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--profile', type=Path, help='explicit validated extractor profile JSON')
    parser.add_argument('--textures', action='store_true', help='export retained original textures as PNG and group material batches')
    parser.add_argument('--executable', type=Path,
                        help='optional unmodified S2_3DFX.EXE, checked against the selected profile SHA256')
    args = parser.parse_args()
    from guest_memory import Snapshot
    profile = load_profile(args.profile) if args.profile else DEFAULT_PROFILE
    metadata = json.loads(args.metadata.read_text())
    provenance = {'ram_file': str(args.ram), 'ram_sha256': file_sha256(args.ram),
                  'metadata_file': str(args.metadata), 'snapshot': metadata,
                  'expected_original_executable_sha256': profile['executable_sha256'],
                  'extractor_profile': profile,
                  'source_project': 'https://github.com/Rick-Barber/ScreamerRally-Recomp',
                  'source_license': 'GPL-3.0-only',
                  'data_layout_sources': ['docs/re/native/world.md', 'docs/re/native/extract.md',
                                          'crates/sr-runtime/src/native/world.rs',
                                          'crates/sr-runtime/src/native/transforms.rs']}
    if args.executable:
        actual = file_sha256(args.executable)
        if actual != profile["executable_sha256"]:
            raise ValueError(f'Unrecognized profile source executable SHA256: {actual}')
        provenance['original_executable_sha256'] = actual
    memory = Snapshot.load(args.ram, args.metadata)
    if args.output.exists():
        raise ValueError(f'Refusing to replace an existing scene artifact: {args.output}')
    staging = args.output.with_name('.' + args.output.name + '.extracting-' + uuid.uuid4().hex)
    try:
        scene = TrackExtractor(memory, with_textures=args.textures, profile=profile).extract(staging, provenance)
        staging.rename(args.output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    print(json.dumps({'scene': str(args.output / 'scene.json'), 'statistics': scene['statistics'],
                      'bounds': scene['bounds'], 'camera': scene['camera']}, indent=2))


if __name__ == '__main__':
    main()
