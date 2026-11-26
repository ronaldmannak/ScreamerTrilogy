# SPDX-License-Identifier: GPL-3.0-only
"""Explicit game-specific addresses for the shared, bounded scene decoder."""
import copy
import json
from pathlib import Path
import re


DEFAULT_PATH = Path(__file__).resolve().parent.parent / 'profiles/screamer2.json'
REQUIRED_LINKS = {'rows', 'models', 'scene', 'camera', 'clock', 'dispatch',
                  'textures', 'libraries', 'environment'}


def load_profile(path):
    path = Path(path)
    if not 0 < path.stat().st_size <= 65536:
        raise ValueError('Extractor profile must contain at most 64 KiB')
    profile = json.loads(path.read_text())
    if not isinstance(profile, dict) or profile.get('schema') != 'screamer-extractor-profile/v1':
        raise ValueError('Unrecognized extractor profile schema')
    if not isinstance(profile.get('id'), str) or not isinstance(profile.get('title'), str):
        raise ValueError('Extractor profile requires an id and title')
    if not re.fullmatch('[0-9a-f]{64}', str(profile.get('executable_sha256'))):
        raise ValueError('Extractor profile requires an executable SHA-256')
    links = profile.get('links')
    if not isinstance(links, dict) or set(links) != REQUIRED_LINKS:
        raise ValueError('Extractor profile links are incomplete or ambiguous')
    if any(type(value) is not int or not 0 < value < 2**32 for value in links.values()):
        raise ValueError('Extractor profile links must be positive 32-bit integers')
    modes = profile.get('setup_modes')
    if not isinstance(modes, dict) or len(modes) != 8:
        raise ValueError('Extractor profile requires all eight material modes')
    try:
        modes = {int(address, 0): mode for address, mode in modes.items()}
    except (TypeError, ValueError) as error:
        raise ValueError('Invalid material routine address') from error
    if any(not 0 < address < 2**32 for address in modes) or set(modes.values()) != set(range(8)):
        raise ValueError('Extractor material routines must uniquely map modes 0..7')
    count = profile.get('texture_record_count')
    if type(count) is not int or not 0 < count <= 8192:
        raise ValueError('Extractor texture count is outside bounds')
    prefixes = profile.get('car_name_prefixes')
    if (not isinstance(prefixes, list) or not prefixes or len(prefixes) > 8
            or any(not isinstance(p, str) or not 1 <= len(p) <= 8 for p in prefixes)):
        raise ValueError('Invalid car-name prefixes')
    lower, upper = profile.get('car_count_min'), profile.get('car_count_max')
    if type(lower) is not int or type(upper) is not int or not 1 <= lower <= upper <= 64:
        raise ValueError('Invalid car-count bounds')
    profile = copy.deepcopy(profile)
    profile['setup_modes'] = modes
    return profile


DEFAULT_PROFILE = load_profile(DEFAULT_PATH)
