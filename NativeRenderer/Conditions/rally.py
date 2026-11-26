# SPDX-License-Identifier: GPL-3.0-only
"""Original Rally Night sky, cars, glass and authored light geometry.

Assets are decoded from an owned installation into the disposable race cache.
The immutable capture supplies existing identities and captured part poses;
no simulation memory, clocks, physics or original files are modified.
"""
from array import array
from collections import Counter
import json
import math
from pathlib import Path

from original_3dfx import RawAssets, archive_entry, png, require, rgb565, rotation, sha, transform, unpack, write_array

EXE_SHA256 = '9eac6e12ab309389bdda019cfa695bfbbc791fbda1a4634464a444fce35165d1'
SCHEMA = 'screamer-original-conditions/v1'
MAX_VERTICES = 3000000


def car_choices(capture, instances, game):
    """Join original loader configuration to captured scene roots, not mesh IDs."""
    result = {}
    if game == 'rally':
        require(len(instances) == 6, 'Rally Night requires the captured six-car cohort')
        for index in range(6):
            model = capture.rd32(capture.link(0x1435cc + index * 0x2c, 4))
            number = capture.rd32(capture.link(0x1435d0 + index * 0x2c, 4))
            entry = capture.rd32(capture.link(0x1296c8 + index * 0xcc8 + 0xbf0, 4))
            identifier = f'scene:{entry}'
            require(identifier not in result, 'Original Rally car scene roots overlap')
            result[identifier] = (model, number + 1)
    elif game == 'screamer2':
        for instance in instances:
            name = instance['name']
            require(name.startswith('auto') and name[4:].isdigit(), 'Unknown original S2 car scene name')
            number = int(name[4:])
            require(1 <= number <= 8, 'Original S2 car configuration exceeds bound')
            model = capture.rd32(capture.link(0x151690 + (number - 1) * 0x2c, 4))
            result[instance['id']] = (model, number)
    else:
        raise ValueError('Unknown original 3dfx car profile')
    require(set(result) == {value['id'] for value in instances}, 'Original car configurations do not match captured roots')
    require(all(0 <= model <= 9 and 1 <= number <= 8 for model, number in result.values()),
            'Original car archive identifiers exceed profile bounds')
    return result


def export_night_cars(game_root, base_cars_path, output, *, game='rally', track_id, capture=None, car_records=None, condition=1):
    """Return an absolute scene.json path, preserving every live pose identity.

    car_records is an optional explicit id -> (zero-based archive model,
    one-based AUTO number) map for offline tests. Normal callers use capture.
    """
    require(capture is not None, 'Night cars require an immutable captured part-pose snapshot')
    require(type(condition) is int and condition in (0, 1, 2), 'Unknown original car visual condition')
    night_bit = condition & 1
    game_root, output = Path(game_root), Path(output)
    base = json.loads(Path(base_cars_path).read_text())
    require(base.get('schema') == 'screamer-scene/v1', 'Unknown captured cars schema')
    require(base['provenance']['ram_sha256'] == capture.sha256, 'Night car capture provenance differs')
    dynamic = base.get('dynamic_instances', [])
    require(1 <= len(dynamic) <= 8, 'Original Night car cohort exceeds bound')
    choices = car_records if car_records is not None else car_choices(capture, dynamic, game)
    require(set(choices) == {value['id'] for value in dynamic}, 'Night car choices do not match captured roots')
    originals = {value['id']: value for value in base['instances']}
    require(len(originals) == len(dynamic), 'Captured car instances are ambiguous')
    require(not output.exists(), 'Refusing to overwrite an original Night car cache')
    output.mkdir(parents=True)
    env_path = game_root / f'GFX/ENVP{track_id + 1}{night_bit}2.DAT'
    env_mlb, env_mlb_source = archive_entry(env_path, 'ENV.MLB')
    env_hic, env_hic_source = archive_entry(env_path, 'ENV.HIC')
    provenance = {'ENV.MLB': env_mlb_source, 'ENV.HIC': env_hic_source}
    special_colors = tuple(capture.rd32(capture.link(address, 4)) & 0xfff for address in
                           ((0x173f9c, 0x173fa0, 0x173fa4) if game == 'rally' else ()))
    if not special_colors:
        special_colors = (0xedc, 0xedc, 0)
    vertices, normals, indices = array('f'), array('f'), array('I')
    textures, batches, instances, counts = [], [], [], Counter()
    low, high = [math.inf] * 3, [-math.inf] * 3
    for car_index, root in enumerate(dynamic):
        original = originals[root['id']]
        model_choice, number = choices[root['id']]
        require(0 <= model_choice <= 9 and 1 <= number <= 8, 'Original Night car selection exceeds bound')
        car_archive = game_root / f'GFX/CARS{model_choice + 1}{night_bit}2.DAT'
        entries = {}
        for ext in ('3DX', 'MLB', 'HIC'):
            entries[ext], source = archive_entry(car_archive, f'AUTO{number}.{ext}')
            provenance[f'{car_index}:{ext}'] = source
        prefix = f'car-{car_index}'
        assets = RawAssets(entries['3DX'], entries['MLB'], entries['HIC'], output / prefix,
                           single_model=True, env_mlb=env_mlb, env_hic=env_hic, special_colors=special_colors)
        model = assets.model()
        animation = original.get('animation', 0)
        if animation < 0:
            clock = 0x1473a0 if game == 'rally' else 0x154770
            animation = (capture.rd32(capture.link(clock, 4)) & 0x3fff) << 2
        part_names, groups, material_values = [], {}, {}
        for slot in range(model['parts']):
            available = [(level, model['levels'][level][slot]) for level in range(3) if model['levels'][level][slot]]
            if not available:
                continue
            _, offset = available[0]
            part = assets.part(model, offset)
            part_names.append(part['name'])
            # The original hierarchy is retained; the pose is read from this
            # immutable capture, never from a running guest or raw host pointer.
            at = original['parts_b'] + slot * 0x20
            matrix = rotation([capture.i32(at + 8 + axis * 4) for axis in range(3)])
            position = [capture.i32(at + 0x14 + axis * 4) for axis in range(3)]
            transformed = [transform(matrix, position, vertex) for vertex in part['vertices']]
            for polygon in part['polygons']:
                material = assets.material(polygon['material'])
                mode = material['mode']
                texture = None if mode == 2 else assets.texture(material, animation, root.get('reflection_phase', 0))
                require(mode == 2 or texture is not None, 'Original Night car material has no texture')
                reflection_frames = []
                if mode == 5:
                    require(len(part['normals']) == len(part['vertices']), 'Original Night reflective car lacks authored normals')
                    environment = assets.environment.material(0)
                    require(environment['frames'], 'Original Night reflection texture is absent')
                    for phase in range(len(environment['frames'])):
                        reflection_frames.append(assets.texture(material, 0, (phase * 65536 + len(environment['frames']) - 1) // len(environment['frames'])))
                key = (polygon['material'], texture, material['blend_mode'])
                groups.setdefault(key, array('I'))
                material_values[key] = (material, reflection_frames)
                first = len(vertices) // 9
                require(first + len(polygon['indices']) <= MAX_VERTICES, 'Original Night car vertex budget exceeded')
                color = [value / 255 for value in rgb565(polygon['color'])] + [1.] if mode == 2 else [1.] * 4
                for index in polygon['indices']:
                    point = transformed[index]
                    require(all(math.isfinite(value) and abs(value) < 10000000 for value in point), 'Invalid original Night car vertex')
                    vertices.extend(point + [value / 256 for value in part['uv'][index]] + color)
                    normal = transform(matrix, (0, 0, 0), part['normals'][index]) if mode == 5 else [0., 0., 0.]
                    require(all(math.isfinite(value) and abs(value) <= 8 for value in normal), 'Invalid original Night car normal')
                    normals.extend(normal)
                    for axis in range(3):
                        low[axis], high[axis] = min(low[axis], point[axis]), max(high[axis], point[axis])
                for corner in range(1, len(polygon['indices']) - 1):
                    groups[key].extend((first, first + corner, first + corner + 1))
                counts[f'material_{material["type"]:#x}_polygons'] += 1
        require(part_names == original.get('part_names'),
                'Original Night car part hierarchy differs from captured part poses')
        texture_offset = len(textures)
        textures.extend({**texture, 'path': prefix + '/' + texture['path'],
                         **({'rgba_file': prefix + '/' + texture['rgba_file']} if texture.get('rgba_file') else {})}
                        for texture in assets.textures)
        batch_indices = []
        for key, values in groups.items():
            material, reflection_frames = material_values[key]
            mode = material['mode']
            batch = {'first_index': len(indices), 'index_count': len(values),
                     'texture': texture_offset + key[1] if key[1] is not None else None,
                     'instance_id': root['id'], 'mode': mode, 'alpha_test': mode in (1, 3),
                     'blend': mode in (3, 6, 7), 'blend_mode': key[2],
                     'source_material_type': material['type'], 'source_material_offset': material['offset']}
            if mode == 5:
                batch.update(texgen='original-reflection', reflection_textures=[texture_offset + frame for frame in reflection_frames])
            batch_indices.append(len(batches))
            batches.append(batch)
            indices.extend(values)
        instances.append({**root, 'model': root['model'], 'part_names': part_names, 'batch_indices': batch_indices,
                          'geometry_space': 'car-root local; captured per-part placement baked in'})
    require(indices and len(indices) % 3 == 0 and max(indices) < len(vertices) // 9, 'Invalid original Night car indices')
    for name, values in (('vertices.bin', vertices), ('indices.bin', indices), ('normals.bin', normals)):
        write_array(output / name, values)
    scene = {**base, 'title': ('Screamer Rally' if game == 'rally' else 'Screamer 2') + (': original Night cars and light geometry' if night_bit else ': original Day cars'),
             'provenance': {**base['provenance'], 'condition': condition, 'original_entries': provenance,
                            'source': 'Owned original CARS/ENV condition banks decoded offline; captured live root identities preserved'},
             'vertices': {**base['vertices'], 'count': len(vertices) // 9},
             'indices': {**base['indices'], 'count': len(indices)},
             'normals': {'file': 'normals.bin', 'count': len(normals) // 3, 'stride': 12, 'format': 'float32-le', 'space': 'vertex-local'},
             'batches': batches, 'textures': textures, 'dynamic_instances': instances, 'instances': instances,
             'bounds': {'min': low, 'max': high},
             'statistics': {**counts, 'vertices': len(vertices) // 9, 'triangles': len(indices) // 3, 'car_instances': len(instances)},
             'limitations': ['Captured per-part/wheel poses remain frozen; condition assets never change simulation.'],
             'files_sha256': {name: sha((output / name).read_bytes()) for name in ('vertices.bin', 'indices.bin', 'normals.bin')}}
    # Base materials reference transient guest addresses; Night batches refer
    # directly to original source offsets and the explicit texture/blend data.
    scene.pop('materials', None)
    (output / 'scene.json').write_text(json.dumps(scene, indent=2) + '\n')
    return str((output / 'scene.json').resolve())


def export_backdrop(root, track_id, night_bit, path):
    source, provenance = archive_entry(root / f'GFX/MAP{track_id + 1}2.DAT', f'MAP{track_id + 1}{night_bit}.BCK')
    require(len(source) == 256 * 256 * 4, 'Original Rally backdrop extent differs')
    rgba = bytes(value for at in range(0, len(source), 4) for value in (*rgb565(unpack(source, '<H', at)[0]), 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png(256, 256, rgba))
    path.with_suffix('.json').write_text(json.dumps(provenance, indent=2) + '\n')
    return str(path.resolve())


def export_day_and_fog(root, track_id, base_world_path, base_cars_path, output, *, capture, original):
    from original_glide_fog import original_glide_fog
    output.mkdir(parents=True)
    # Fog's original condition2 selects Day banks (condition & 1 == 0).
    # Reuse a captured Day/Fog bank exactly; only a captured Night cohort needs
    # its Day geometry and environment rebuilt with the same live identities.
    cars = str(Path(base_cars_path).resolve())
    if original == 'night':
        cars = export_night_cars(root, base_cars_path, output / 'cars', track_id=track_id,
                                capture=capture, condition=0)
    sky = export_backdrop(root, track_id, 0, output / 'sky.png')
    world = str(Path(base_world_path).resolve())
    # Original builder CBB39..CBB5E shifts BDF7 fields directly into
    # grConstantColorValue; it does not replicate the low RGB565 bits.
    fog = {'available': True, 'world_scene': world, 'cars_scene': cars, 'sky_texture': sky,
           'sky': {'kind': 'rally', 'enabled': False, 'ground_rgb': [184, 188, 184], 'flat_rgb': [184, 188, 184]},
           'glide_fog': original_glide_fog(),
           'source': 'Original STRT3FX condition2: Day banks, no sky, BDF7 fill, B8B8B8 Glide table fog (5527A)'}
    day = None
    if original != 'day':
        colors = [capture.rd32(capture.link(0x136524 + 4 * axis, 4)) for axis in range(3)]
        r, g, b = colors
        ground = ((r << 8) & 0xf800) | ((g << 3) & 0x7e0) | (b >> 3)
        # Match the original sky/constant-color bitshift expansion already used
        # by the baseline Rally sky_state reader, including Day fill value1.
        day = {'available': True, 'world_scene': world, 'cars_scene': cars, 'sky_texture': sky,
               'sky': {'kind': 'rally', 'enabled': True,
                       'ground_rgb': [((ground >> 11) & 31) << 3, ((ground >> 5) & 63) << 2, (ground & 31) << 3],
                       'flat_rgb': [0, 0, 8]}}
    return day, fog


def export_night(game_root, track_id, base_world_path, base_cars_path, output, *, capture):
    """Export original optional visual variants; availability is independent."""
    condition = capture.rd32(capture.link(0x1435c4, 4))
    require(condition in (0, 1, 2), 'Unknown original Rally condition')
    result = {'schema': SCHEMA, 'original': ('day', 'night', 'fog')[condition]}
    require(type(track_id) is int and 0 <= track_id <= 6, 'Unknown Rally track index')
    unavailable = {'available': False, 'reason': 'The original Stadium track has no authored Night sky.'}
    result['night'] = unavailable if track_id == 6 else {'available': False, 'reason': 'Original Night assets unavailable.'}
    result['fog'] = {'available': False, 'reason': 'Original Fog assets unavailable.'}
    root, output = Path(game_root), Path(output)
    try:
        require(sha((root / 'STRT3FX.EXE').read_bytes()) == EXE_SHA256, 'Original Rally executable profile differs')
        require(not output.exists(), 'Refusing to overwrite an original condition cache')
        output.mkdir(parents=True)
    except (ValueError, OSError) as error:
        result['fog']['reason'] = str(error)[:500]
        if track_id != 6:
            result['night']['reason'] = str(error)[:500]
        return result
    try:
        day, result['fog'] = export_day_and_fog(root, track_id, base_world_path, base_cars_path,
                                              output / 'fog', capture=capture, original=result['original'])
        if day is not None:
            result['day'] = day
    except (ValueError, OSError) as error:
        result['fog'] = {'available': False, 'reason': str(error)[:500]}
    if track_id == 6:
        return result
    try:
        sky = export_backdrop(root, track_id, 1, output / 'sky.png')
        cars = export_night_cars(root, base_cars_path, output / 'cars', track_id=track_id, capture=capture)
        result['night'] = {'available': True, 'world_scene': str(Path(base_world_path).resolve()),
                           'cars_scene': cars, 'sky_texture': sky,
                           'sky': {'kind': 'rally', 'enabled': True, 'ground_rgb': [0, 0, 0], 'flat_rgb': [0, 0, 0]},
                           'night_fog': {'near': 6000, 'far': 35000, 'color': [0, 0, 0]}}
    except (ValueError, OSError) as error:
        result['night'] = {'available': False, 'reason': str(error)[:500]}
    return result
