"""Validated configuration shared by the extracted pilot; no Blender/model calls."""
import argparse
import json
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INPUT_PATHS = ('camera_harness', 'worldos', 'scene_index', 'source_blend',
               'calibration_blend', 'baseline_episode', 'font_path')
DIRECTORY_INPUTS = {'camera_harness', 'worldos', 'history_root'}
ANCHORS = {'west_entry', 'pickup_stand', 'handover_A', 'handover_B', 'east_wait',
           'drop_stand', 'drop_retreat', 'observer', 'west_bypass', 'east_bypass'}


def _numbers(value, count, label):
    if not isinstance(value, list) or len(value) != count or any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
        for v in value
    ):
        raise ValueError(f'{label} must contain {count} finite numbers')


def load_config(filename=None, *, check_paths=False):
    filename = Path(filename or os.environ.get('STUDIO_CONFIG', ROOT / 'config.local.json')).resolve()
    if not filename.is_file():
        raise ValueError('Missing config: copy configs/forest.example.json to config.local.json and edit it')
    config = json.loads(filename.read_text())
    if not isinstance(config, dict) or config.get('schema') != 'virtual_studio.forest_pilot.v1':
        raise ValueError('Unsupported studio configuration schema')
    for key in INPUT_PATHS + ('output_dir', 'blender_lock'):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f'Missing path: {key}')
        path = Path(config[key]).expanduser()
        config[key] = (filename.parent / path).resolve()
    if config.get('history_root') is not None:
        if not isinstance(config['history_root'], str) or not config['history_root'].strip():
            raise ValueError('history_root must be a directory path or null')
        config['history_root'] = (filename.parent / Path(config['history_root']).expanduser()).resolve()
    else:
        config['history_root'] = None
    # Keep outputs separate from inputs: opening/saving a pilot must not overwrite sources.
    for key in INPUT_PATHS + ('history_root',):
        path = config.get(key)
        if path and (path == config['output_dir'] or config['output_dir'] in path.parents):
            raise ValueError(f'output_dir contains source input: {key}')
    sha = config.get('source_sha256', '')
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
        raise ValueError('source_sha256 must be the actual 64-character lowercase scene hash')
    _numbers(config.get('origin_blender'), 3, 'origin_blender')
    _numbers(config.get('roi_half_extent'), 3, 'roi_half_extent')
    if min(config['roi_half_extent']) <= 0:
        raise ValueError('roi_half_extent must be positive')
    anchors = config.get('anchors_xz')
    if not isinstance(anchors, dict) or set(anchors) != ANCHORS:
        raise ValueError('This pilot requires the ten named Forest anchors; see the example config')
    for name, point in anchors.items():
        _numbers(point, 2, f'anchors_xz.{name}')
        if abs(point[0]) > config['roi_half_extent'][0] or abs(point[1]) > config['roi_half_extent'][1]:
            raise ValueError(f'Anchor outside local region: {name}')
    for key in ('blender_bin', 'codex_bin', 'model', 'reasoning_effort'):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f'Missing setting: {key}')
    if check_paths:
        for key in INPUT_PATHS + ('history_root',):
            path = config.get(key)
            if path is None:
                continue
            if not (path.is_dir() if key in DIRECTORY_INPUTS else path.is_file()):
                raise ValueError(f'Missing or wrong-type input: {key} = {path}')
    return config


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--check-paths', action='store_true')
    args = parser.parse_args()
    try:
        load_config(args.config, check_paths=args.check_paths)
    except (ValueError, OSError) as exc:
        parser.exit(2, f'{exc}\n')
    print('Studio config valid; no Blender process or model job started.')
