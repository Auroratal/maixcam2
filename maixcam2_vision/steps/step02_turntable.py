"""第二、七步：对齐原料转盘，只输出外圆测量值。"""

from ..detectors.turntable_detector import TurntableDetector, load_turntable_detector_config
from ..detectors.turntable_material_seed import (
    ThreeMaterialTurntableSeeder, load_three_material_seed_config,
)


def build_detector(config_dir, colors):
    seeder = ThreeMaterialTurntableSeeder(
        load_three_material_seed_config(config_dir / "turntable_material_seed.json"), colors,
    )
    return TurntableDetector(
        load_turntable_detector_config(config_dir / "turntable_detector.json"), seeder,
    )


def process(detector, frame, target=None):
    result = detector.detect(frame)
    data = {}
    if result.detected:
        data = {
            "center_px": [result.center_x_px, result.center_y_px],
            "radius_px": result.radius_px, "confidence": result.confidence,
            "error_px": None if target is None else [
                result.center_x_px - target[0], result.center_y_px - target[1],
            ],
        }
    return result, data
