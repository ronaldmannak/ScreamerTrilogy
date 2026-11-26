#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Optional original-car mesh export with captured part poses and replay IDs.

Vertices stay in each car root's local space. Per-part wheel poses are captured,
not animated. A renderer must apply dynamic_instances transforms to batches with
the matching instance_id. This is not a playable-game or complete-car-shader port.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_track import EXPECTED_EXE_SHA256, LINKS, TrackExtractor, file_sha256, rotation, triple
from guest_memory import Snapshot


class CarExtractor(TrackExtractor):
    def __init__(self, memory):
        super().__init__(memory, with_textures=True)
        self.root_poses = {}
        self.current_parts_b = None

    def objects(self):
        r = self.memory
        scene = r.link(LINKS['scene'])
        count = 0
        for entry in range(1024):
            address = scene + 28 * entry
            if r.rd32(address + 0x18) == 0xffffffff:
                break
            name = r.bytes(address, 8).split(b'\0')[0].decode('ascii', errors='replace')
            if not name.startswith('auto'):
                continue
            instance = r.pointer(address + 0xc)
            parts_b = r.pointer(address + 0x10)
            position, angles = triple(r, instance + 8), triple(r, instance + 0x14)
            identifier = f'scene:{entry}'
            self.root_poses[identifier] = {'id': identifier, 'name': name,
                'position': position, 'angles': angles,
                'rotation': [value for row in rotation(angles) for value in row]}
            count += 1
            yield {'id': identifier, 'name': name, 'address': instance, 'parts_b': parts_b,
                   'model': r.rd32(instance), 'flags': r.rd32(instance + 4), 'listing': 1,
                   'position': [0, 0, 0], 'angles': [0, 0, 0],
                   'animation': r.i32(instance + 0x20)}
        self.counts['car_instances'] = count
        if count != 6:
            raise ValueError(f'Expected six race cars in the captured scene, found {count}')

    def placement(self, model, slot):
        if self.current_parts_b is None:
            raise ValueError('Car part placement requested without instance B')
        address = self.current_parts_b + 0x20 * slot
        angles = triple(self.memory, address + 8)
        position = triple(self.memory, address + 0x14)
        return rotation(angles), position

    def add_object(self, obj):
        self.current_parts_b = obj['parts_b']
        self.current_instance_id = obj['id']
        super().add_object(obj)
        self.instances[-1].update(self.root_poses[obj['id']])
        self.instances[-1]['geometry_space'] = 'car-root local; captured per-part placement baked in'

    def extract(self, output, provenance):
        scene = super().extract(output, provenance)
        scene['title'] = 'Screamer Rally: six captured original car meshes'
        scene['prototype'] = 'Optional local car meshes for root-pose replay; requires instance transforms and material pipelines.'
        scene['dynamic_instances'] = []
        for instance in self.instances:
            scene['dynamic_instances'].append({**self.root_poses[instance['id']],
                'model': instance['model'],
                'batch_indices': [index for index, batch in enumerate(scene['batches'])
                                  if batch.get('instance_id') == instance['id']],
                'part_names': instance['part_names']})
        scene['coordinates']['vertices'] = 'each batch instance_id selects a car-root local coordinate system'
        scene['limitations'] = [
            'Root transforms must be applied by instance_id; these are not world-baked vertices.',
            'Wheel and part placement is frozen at the captured pose; no hierarchy animation.',
            'Mode 6 requires an alpha-blended pipeline and appropriate transparent ordering.',
            'Mode 5 requires view-dependent reflection texgen; exported ordinary UVs do not reproduce it.',
            'No shadows, smoke, HUD, sounds, controls, physics execution or playable game.',
        ]
        (output / 'scene.json').write_text(json.dumps(scene, indent=2) + '\n')
        return scene


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ram', type=Path, required=True)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError(f'Refusing to overwrite existing artifact: {args.output}')
    memory = Snapshot.load(args.ram, args.metadata)
    provenance = {'ram_file': str(args.ram), 'ram_sha256': file_sha256(args.ram),
        'snapshot': json.loads(args.metadata.read_text()),
        'expected_original_executable_sha256': EXPECTED_EXE_SHA256,
        'source_project': 'https://github.com/Rick-Barber/ScreamerRally-Recomp',
        'source_license': 'GPL-3.0-only',
        'data_layout_sources': ['docs/re/native/world.md', 'docs/re/native/dynamics.md']}
    staging = args.output.with_name('.' + args.output.name + '.extracting-' + uuid.uuid4().hex)
    try:
        scene = CarExtractor(memory).extract(staging, provenance)
        staging.rename(args.output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    print(json.dumps({'scene': str(args.output / 'scene.json'), 'statistics': scene['statistics'],
                      'cars': [{'id': x['id'], 'batches': len(x['batch_indices'])} for x in scene['dynamic_instances']]}, indent=2))


if __name__ == '__main__':
    main()
