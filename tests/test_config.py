import ast
import copy
import json
from pathlib import Path
import tempfile
import unittest

from studio_config import ANCHORS, INPUT_PATHS, ROOT, load_config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.example = json.loads((ROOT / 'configs/forest.example.json').read_text())

    def write(self, data=None):
        filename = self.base / 'config.json'
        filename.write_text(json.dumps(self.example if data is None else data))
        return filename

    def test_relative_paths_are_config_relative(self):
        config = load_config(self.write())
        self.assertEqual(config['output_dir'], self.base / 'outputs/forest-capsules')
        self.assertEqual(set(config['anchors_xz']), ANCHORS)
        self.assertIsNone(config['history_root'])

    def test_missing_source_file_is_reported_before_execution(self):
        with self.assertRaisesRegex(ValueError, 'camera_harness'):
            load_config(self.write(), check_paths=True)

    def test_present_paths_validate_without_blender_or_model(self):
        config = load_config(self.write())
        for key in INPUT_PATHS:
            path = config[key]
            if key in {'camera_harness', 'worldos'}:
                path.mkdir(parents=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
        load_config(self.write(), check_paths=True)

    def test_bad_scene_hash_rejected(self):
        self.example['source_sha256'] = 'not-a-scene-hash'
        with self.assertRaisesRegex(ValueError, 'scene hash'):
            load_config(self.write())

    def test_missing_and_nonfinite_anchor_rejected(self):
        for point in ([0, float('nan')], [True, 0], [0]):
            with self.subTest(point=point):
                data = copy.deepcopy(self.example)
                data['anchors_xz']['observer'] = point
                with self.assertRaises(ValueError):
                    load_config(self.write(data))
        self.example['anchors_xz'].pop('observer')
        with self.assertRaisesRegex(ValueError, 'ten named'):
            load_config(self.write())

    def test_anchors_outside_region_rejected(self):
        self.example['anchors_xz']['observer'] = [900, 0]
        with self.assertRaisesRegex(ValueError, 'outside local region'):
            load_config(self.write())

    def test_source_in_output_directory_rejected(self):
        self.example['source_blend'] = 'outputs/forest-capsules/source.blend'
        with self.assertRaisesRegex(ValueError, 'contains source input'):
            load_config(self.write())

    def test_all_sources_parse_without_machine_specific_paths(self):
        runtime_paths = list((ROOT / 'experiments').rglob('*.py')) + [ROOT / 'studio_config.py']
        for path in runtime_paths:
            with self.subTest(path=path.relative_to(ROOT)):
                source = path.read_text()
                ast.parse(source, filename=str(path))
                for node in ast.walk(ast.parse(source)):
                    if isinstance(node, ast.Constant) and isinstance(node.value, str):
                        self.assertFalse(node.value.startswith(('/Users/', '/System/Library/', '/Applications/', '/opt/homebrew/')))


if __name__ == '__main__':
    unittest.main()
