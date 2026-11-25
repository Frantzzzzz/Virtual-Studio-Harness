"""Explicit paths for the pilot; no machine-specific defaults or credentials."""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from studio_config import load_config

CONFIG = load_config()
OUT = CONFIG['output_dir']
HARNESS = CONFIG['camera_harness']
WORLDOS = CONFIG['worldos']
INDEX = CONFIG['scene_index']
OUT.mkdir(parents=True, exist_ok=True)


def font(size):
    from PIL import ImageFont
    return ImageFont.truetype(str(CONFIG['font_path']), size)
