#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Compile and run synthetic CPU/GPU and menu checks without original game files."""
import argparse
import hashlib
import json
import struct
from pathlib import Path
import subprocess


def compile_probe(source, production, output):
    subprocess.run(['xcrun', 'clang++', '-std=c++17', '-arch', 'arm64',
                    '-mmacosx-version-min=12.0', '-fobjc-arc', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-framework', 'AppKit', '-framework', 'Metal', '-framework', 'MetalKit',
                    '-framework', 'QuartzCore', '-DPREVIEW_SOURCE_FILE="' + str(production) + '"',
                    str(source), '-o', str(output)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='Fresh isolated output directory')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    tests = Path(__file__).resolve().parent
    production = tests.parent / 'Sources/NativePreview.mm'
    gpu = args.output / 'ConditionsRegression'
    menu = args.output / 'PresetMenuRegression'
    frontend = args.output / 'ConditionsFrontend'
    compile_probe(tests / 'ConditionsRegression.mm', production, gpu)
    compile_probe(tests / 'PresetMenuRegression.mm', production, menu)
    compile_probe(production, production, frontend)
    subprocess.run([str(gpu), str(production.parent / 'World.metal'),
                    str(args.output / 'conditions-gpu.json')], check=True, timeout=30)
    subprocess.run([str(menu)], check=True, timeout=15)
    # Exercise actual CLI parsing and renderer wiring with authored geometry.
    scene = args.output / 'synthetic-scene'
    scene.mkdir()
    points = [(-1000, -1000, 0), (1000, -1000, 0), (-1000, 1000, 0),
              (-1000, 1000, 0), (1000, -1000, 0), (1000, 1000, 0)]
    (scene / 'vertices.bin').write_bytes(b''.join(struct.pack('<9f', *point, 0, 0, 64/255, 96/255, 160/255, 1) for point in points))
    (scene / 'indices.bin').write_bytes(struct.pack('<6I', *range(6)))
    (scene / 'scene.json').write_text(json.dumps({
        'title': 'Authored conditions CLI fixture',
        'vertices': {'file': 'vertices.bin'}, 'indices': {'file': 'indices.bin'},
        'bounds': {'min': [-1000, -1000, 0], 'max': [1000, 1000, 0]},
        'textures': [], 'batches': [{'first_index': 0, 'index_count': 6, 'texture': -1}]}))
    invalid = subprocess.run([str(frontend), '--conditions', 'rain'], capture_output=True, text=True, timeout=10)
    assert invalid.returncode != 0 and 'conditions' in invalid.stderr.lower(), invalid
    variants = {}
    for name, option in [('default', []), ('day', ['--conditions', 'day']),
                         ('night', ['--conditions', 'night']), ('fog', ['--conditions', 'fog'])]:
        png, metrics = args.output / (name + '.png'), args.output / (name + '.json')
        subprocess.run([str(frontend), '--scene', str(scene / 'scene.json'),
                        '--shader', str(production.parent / 'World.metal'), '--time', '0',
                        '--width', '64', '--height', '64', '--frames', '2',
                        '--offscreen', str(png), '--report', str(metrics), *option],
                       check=True, capture_output=True, text=True, timeout=20)
        values = json.loads(metrics.read_text())
        expected = 'day' if name == 'default' else name
        assert values['conditions_preset'] == expected, values
        assert abs(values['conditions_night_weight'] - (expected == 'night')) < 1e-6, values
        assert abs(values['conditions_fog_weight'] - (expected == 'fog')) < 1e-6, values
        variants[name] = hashlib.sha256(png.read_bytes()).hexdigest()
    assert variants['default'] == variants['day'], 'Default rendering must equal explicit Day'
    assert variants['night'] == variants['day'], 'Near-field Night must preserve authored art without a global tint'
    assert variants['fog'] != variants['day'], variants
    report = {'passed': True, 'gpu_report': 'conditions-gpu.json',
              'actual_frontend_cli': {'invalid_rejected': True, 'default_equals_day': True,
                                      'night_and_fog_rendered': True, 'image_hashes': variants},
              'menu_shortcuts_and_live_switching': True,
              'scope': 'Synthetic shader/CPU probes and menu dispatch only; no original game content or engine'}
    (args.output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
