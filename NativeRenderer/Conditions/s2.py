# SPDX-License-Identifier: GPL-3.0-only
"""Decode owned Screamer 2 Night banks into a separate render-only asset set.

The original 3dfx loader selects MAPnH12 and ENVPn12 for condition & 1.
This module never changes that condition, executes guest code, or changes the
captured camera, car identities, simulation, or baseline extraction.
"""
from array import array
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import struct

from original_3dfx import RawAssets, rotation, transform, write_array

NIGHT_TRACKS = frozenset((0, 1, 2, 3, 5))
EXE_SHA256 = 'e6c24c84650938f2baee5f4b571baa45bb09a93ba12dd24e3e1d2cefd9b6f3ec'
MAX_OBJECTS = 100000
MAX_VERTICES = 3000000


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def field(raw, offset, fmt='<I'):
    require(0 <= offset <= len(raw) - struct.calcsize(fmt), 'Original MMP field exceeds its file')
    values = struct.unpack_from(fmt, raw, offset)
    return values[0] if len(values) == 1 else values


def objects(grid):
    """Read original file-relative MMP lists, with independent bounded extents."""
    require(len(grid) >= 1024, 'Original MMP is missing its row table')
    count = 0
    for row in range(256):
        row_at = field(grid, row * 4)
        if row_at == 0xffffffff:
            continue
        require(row_at <= len(grid) - 1024, 'Original MMP row exceeds its file')
        for col in range(256):
            cell = field(grid, row_at + 4 * col)
            if cell == 0xffffffff:
                continue
            for listing in (0, 1):
                base = field(grid, cell + 4 * listing)
                size = field(grid, cell + 0x14 + 4 * listing)
                count += size
                require(size <= MAX_OBJECTS and count <= MAX_OBJECTS, 'Original MMP object budget exceeded')
                require(not size or base <= len(grid) - size * 0x40, 'Original MMP object list exceeds its file')
                for index in range(size):
                    at = base + index * 0x40
                    yield {'id': f'cell:{row}:{col}:{listing}:{index}', 'cell': [row, col], 'listing': listing,
                           'model': field(grid, at), 'flags': field(grid, at + 4),
                           'position': list(field(grid, at + 8, '<3i')),
                           'angles': list(field(grid, at + 0x14, '<3i')),
                           'animation': field(grid, at + 0x20, '<i'),
                           'reflection_phase': field(grid, at + 0x3c)}


class NightWorld:
    def __init__(self, assets, grid, output, *, camera=None, provenance=None, track_id=0, clock=0):
        self.assets, self.grid, self.output = assets, grid, Path(output)
        self.camera, self.provenance, self.track_id = camera, provenance or {}, track_id
        self.clock = clock
        self.vertices, self.normals, self.groups = array('f'), array('f'), {}
        self.low, self.high = [math.inf] * 3, [-math.inf] * 3
        self.instances, self.materials, self.counts = [], {}, Counter()

    def add_object(self, obj):
        model = self.assets.model(obj['model'])
        angles = obj['angles']
        if obj['flags'] & 0x8000:
            camera_angles = (self.camera or {}).get('angles', [0, 0, 0])
            angles = [(angles[0] - camera_angles[0]) & 2047,
                      -(angles[1] - camera_angles[1] + 1024) & 2047, 2047 - camera_angles[2]]
            self.counts['frozen_billboards'] += 1
        object_rotation = rotation(angles)
        instance = {**obj, 'part_names': []}
        for slot in range(model['parts']):
            available = [(level, model['levels'][level][slot]) for level in range(3)
                         if model['levels'][level][slot]]
            if not available:
                continue
            level, offset = available[0]
            self.counts[f'parts_lod_{level}'] += 1
            part = self.assets.part(model, offset)
            instance['part_names'].append(part.get('name', ''))
            matrix, translation = self.assets.placement(model, slot)
            vertices = [transform(object_rotation, obj['position'], transform(matrix, translation, vertex))
                        for vertex in part['vertices']]
            for polygon in part['polygons']:
                material = self.assets.material(polygon['material'])
                kind = material['type']
                require(kind in (0x10, 0x40, 0x60, 0x80, 0xa0, 0xe0, 0x100, 0x120),
                        f'Unsupported original S2 Night material {kind:#x}')
                animation = (self.clock & 0x3fff) << 2 if obj['animation'] < 0 else obj['animation']
                texture = None if kind == 0x80 else self.assets.texture(material, animation, obj['reflection_phase'])
                require(texture is not None or kind == 0x80, 'Original S2 Night texture is missing')
                # Texture decoding also identifies the authored 0x120 blend family.
                blend_mode = material.get('blend_mode', 'opaque')
                self.materials[polygon['material']] = material
                c = polygon['color']
                rgba = [((c >> 11) & 31) / 31, ((c >> 5) & 63) / 63, (c & 31) / 31, 1.] if kind == 0x80 else [1.] * 4
                start = len(self.vertices) // 9
                require(start + len(polygon['indices']) <= MAX_VERTICES, 'Original S2 Night vertex budget exceeded')
                for index in polygon['indices']:
                    position = vertices[index]
                    require(all(math.isfinite(v) and abs(v) < 10000000 for v in position),
                            'Original S2 Night transformed vertex is invalid')
                    self.vertices.extend(position + [value / 256 for value in part['uv'][index]] + rgba)
                    normal = [0., 0., 0.]
                    if kind == 0xa0:
                        require(part['flags'] & 0x2000 and index < len(part['normals']),
                                'Original S2 Night reflection normal table is missing')
                        authored = part['normals'][index]
                        require(all(math.isfinite(value) for value in authored) and
                                .99 < sum(value * value for value in authored) < 1.01,
                                'Original S2 Night reflection normal is invalid')
                        normal = transform(object_rotation, [0, 0, 0], transform(matrix, [0, 0, 0], authored))
                    self.normals.extend(normal)
                    for axis in range(3):
                        self.low[axis] = min(self.low[axis], position[axis])
                        self.high[axis] = max(self.high[axis], position[axis])
                key = (polygon['material'], texture, blend_mode)
                indices = self.groups.setdefault(key, array('I'))
                for corner in range(1, len(polygon['indices']) - 1):
                    indices.extend((start, start + corner, start + corner + 1))
                self.counts[f'material_{kind:#x}_polygons'] += 1
        self.instances.append(instance)

    def export(self):
        for obj in objects(self.grid):
            self.add_object(obj)
        indices, batches = array('I'), []
        for (offset, texture, blend_mode), values in sorted(self.groups.items(), key=lambda item: str(item[0])):
            material = self.materials[offset]
            batches.append({'first_index': len(indices), 'index_count': len(values), 'texture': texture,
                            'alpha_test': material['type'] in (0x40, 0x60, 0xe0), 'blend': blend_mode != 'opaque',
                            'blend_mode': blend_mode, 'source_material_offset': offset,
                            'source_material_type': material['type'], 'double_sided': True})
            if material['type'] == 0xa0:
                environment = self.assets.environment or self.assets
                count = len(environment.material(0)['frames']) if self.assets.environment else len(material['frames'])
                require(0 < count <= 1024, 'Original S2 Night environment frame count is invalid')
                frames = [self.assets.texture(material, 0, (index * 65536 + count - 1) // count)
                          for index in range(count)]
                batches[-1].update(texgen='original-reflection', reflection_scroll=[0., 0.], reflection_textures=frames)
            indices.extend(values)
        require(indices and len(indices) % 3 == 0 and max(indices) < len(self.vertices) // 9,
                'Original S2 Night mesh has invalid indices')
        write_array(self.output / 'vertices.bin', self.vertices)
        write_array(self.output / 'indices.bin', indices)
        require(len(self.normals) == len(self.vertices) // 3, 'Original S2 Night normals differ from the mesh extent')
        write_array(self.output / 'normals.bin', self.normals)
        scene = {'schema': 'screamer-scene/v1', 'title': f'Screamer 2: original Night track {self.track_id + 1}',
                 'provenance': self.provenance,
                 'coordinates': {'handedness': 'left', 'up': '+Y', 'units': 'original game world units',
                                 'vertices': 'absolute world positions', 'winding': 'original polygon order'},
                 'vertices': {'file': 'vertices.bin', 'count': len(self.vertices) // 9, 'stride': 36,
                              'format': 'float32-le', 'attributes': {'position': {'offset': 0, 'components': 3},
                              'uv': {'offset': 12, 'components': 2}, 'rgba': {'offset': 20, 'components': 4}}},
                 'indices': {'file': 'indices.bin', 'count': len(indices), 'format': 'uint32-le'},
                 'normals': {'file': 'normals.bin', 'count': len(self.normals) // 3, 'stride': 12,
                             'format': 'float32-le', 'space': 'vertex-local',
                             'source': 'Original authored normal table transformed with the static world geometry'},
                 'batches': batches, 'textures': self.assets.textures, 'materials': list(self.materials.values()),
                 'bounds': {'min': self.low, 'max': self.high}, 'camera': self.camera, 'instances': self.instances,
                 'statistics': {**self.counts, 'objects': len(self.instances), 'vertices': len(self.vertices) // 9,
                                'triangles': len(indices) // 3, 'textures': len(self.assets.textures)},
                 'limitations': ['Original texture animation uses the captured phase; animated part placements are frozen and billboards use the captured camera.'],
                 'files_sha256': {name: sha((self.output / name).read_bytes()) for name in ('vertices.bin', 'indices.bin', 'normals.bin')}}
        (self.output / 'scene.json').write_text(json.dumps(scene, indent=2) + '\n')
        return scene


def export_night(game_root, track_id, base_world_path, base_cars_path, output, *, capture,
                 read_entry, export_sky, export_cars=None):
    """Return a variant descriptor; only generated session-cache files are written."""
    require(type(track_id) is int and 0 <= track_id <= 6, 'Unknown original S2 track')
    original_condition = capture.rd32(capture.link(0x151688, 4))
    require(original_condition in (0, 1, 2), 'Unknown original S2 condition')
    result = {'schema': 'screamer-original-conditions/v1',
              'original': 'night' if original_condition & 1 else 'day'}
    if track_id not in NIGHT_TRACKS:
        result['night'] = {'available': False, 'reason': 'This original Screamer 2 track has no authored Night asset bank.'}
        return result
    game_root, output = Path(game_root), Path(output)
    require(sha((game_root / 'S2_3DFX.EXE').read_bytes()) == EXE_SHA256, 'Original S2 executable profile differs')
    require(not output.exists(), 'Refusing to overwrite an existing original Night cache')
    output.mkdir(parents=True)
    world = output / 'world'
    (world / 'textures').mkdir(parents=True)
    bank_path = game_root / f'GFX/MAP{track_id + 1}H12.DAT'
    env_path = game_root / f'GFX/ENVP{track_id + 1}12.DAT'
    entries, provenance = {}, {}
    for ext in ('UNR', 'MMP', 'MLB', 'HIC'):
        entries[ext], provenance[ext] = read_entry(bank_path, f'MAP{track_id + 1}.{ext}')
    env_mlb, provenance['ENV.MLB'] = read_entry(env_path, 'ENV.MLB')
    env_hic, provenance['ENV.HIC'] = read_entry(env_path, 'ENV.HIC')
    assets = RawAssets(entries['UNR'], entries['MLB'], entries['HIC'], world,
                       env_mlb=env_mlb, env_hic=env_hic)
    base_world = json.loads(Path(base_world_path).read_text())
    world_provenance = {'ram_sha256': capture.sha256, 'original_executable_sha256': EXE_SHA256,
                        'source': 'Owned original S2 Night MAP/ENV assets decoded offline; simulation unchanged',
                        'condition': 1, 'track_id': track_id, 'archive': f'GFX/{bank_path.name}',
                        'environment_archive': f'GFX/{env_path.name}', 'original_entries': provenance}
    NightWorld(assets, entries['MMP'], world, camera=base_world.get('camera'),
               provenance=world_provenance, track_id=track_id,
               clock=capture.rd32(capture.link(0x154770, 4))).export()
    sky = export_sky(game_root, track_id, 1, output)
    if export_cars is None:
        from rally import export_night_cars
        export_cars = export_night_cars
    cars_path = export_cars(game_root, Path(base_cars_path), output / 'cars',
                            game='screamer2', track_id=track_id, capture=capture)
    # Loader 0x37D55 disables Night haze for track index3. The other authored
    # Night tracks select the original black distance haze, never a blue tint.
    result['night'] = {'available': True, 'world_scene': str((world / 'scene.json').resolve()),
                       'cars_scene': str(Path(cars_path).resolve()),
                       'sky_texture': str((output / sky['path']).resolve()),
                       'sky': {'kind': 'rally', 'enabled': True, 'ground_rgb': [0, 0, 0], 'flat_rgb': [0, 0, 0]},
                       'night_fog': {'enabled': track_id != 3, 'near': 6000, 'far': 35000, 'color': [0, 0, 0]}}
    return result
