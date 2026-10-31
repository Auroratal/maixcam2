"""统一读取本工程配置，粗加工区与暂存区分别保存标定。"""

import json
import math
from pathlib import Path


DEFAULT_CONFIG_DIR = Path(__file__).resolve().parent / "config"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_settings(config_dir=DEFAULT_CONFIG_DIR):
    config_dir = Path(config_dir).resolve()
    config = read_json(config_dir / "vision.json")
    camera = config["camera"]
    for key in ("width", "height", "fps"):
        if type(camera[key]) is not int or camera[key] <= 0:
            raise ValueError(f"camera.{key} 必须是正整数")
    if type(camera["undistort"]) is not bool:
        raise ValueError("camera.undistort 必须为 true 或 false")
    for key in ("result_hz", "observation_timeout_s", "freshness_ms"):
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key} 必须是有限正数")
    for area in ("rough", "storage"):
        order = config["areas"][area]["ring_order"]
        if order is not None and (
            not isinstance(order, list) or len(order) != 3
            or any(type(n) is not int for n in order) or set(order) != {1, 2, 3}
        ):
            raise ValueError(f"{area}.ring_order 应为左到右的三个实际环号")
    return config_dir, config


def save_json(path, data):
    """同目录替换，避免标定保存中断留下半个 JSON。"""
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
