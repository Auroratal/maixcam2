"""第五、十、十一步：遮挡工位定位；不把几何重建当作物料检测。"""

from ..detectors.stacked_ring_detector import StackedRingDetector, load_stacked_ring_config
from ..detectors.ring_station_detector import load_ring_station_config
from .step04_station import station_data


def build_detector(config_dir, area, camera_signature):
    detector = StackedRingDetector(
        load_stacked_ring_config(config_dir / f"{area}_stacking.json"),
        load_ring_station_config(config_dir / f"{area}_rings.json"),
    )
    detector.set_camera_geometry(camera_signature)
    return detector


def process(detector, frame, ring_order, reference_calibrated):
    result = detector.detect(frame)
    data = station_data(result, ring_order, reference_calibrated, detector.ring_config)
    if result.detected:
        data.update({
            "side_centers_reconstructed": True,
            "material_alignment_verified": False,
            "reference_line_count": len(result.line_segments_px),
        })
    return result, data
