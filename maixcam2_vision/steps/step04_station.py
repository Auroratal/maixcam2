"""第四、六、九步：空工位三环定位；粗加工取回时也可切到此模式。"""

from ..detectors.ring_station_detector import RingStationDetector, load_ring_station_config


def build_detector(config_dir, area):
    return RingStationDetector(load_ring_station_config(config_dir / f"{area}_rings.json"))


def process(detector, frame, ring_order, reference_calibrated):
    result = detector.detect(frame)
    return result, station_data(result, ring_order, reference_calibrated, detector.config)


def station_data(result, ring_order, reference_calibrated, reference):
    if not result.detected:
        return {}
    # 数字编号与左中右几何位置分开，避免把“中环”误当成数字 2。
    data = {
        "centers_px": result.centers_px,
        "station_yaw_deg": result.station_yaw_deg,
        "numbering_confirmed": ring_order is not None,
        "rings_by_id": {} if ring_order is None else {
            str(number): list(center) for number, center in zip(ring_order, result.centers_px)
        },
        "reference_calibrated": reference_calibrated,
    }
    # 只输出像素、角度与观测质量。原项目的底盘纠偏矩阵不作为控制指令输出。
    if reference_calibrated:
        data.update({
            "within_tolerance": result.within_tolerance,
            "center_errors_px": [
                [center[0]-target[0], center[1]-target[1]]
                for center, target in zip(result.centers_px, reference.reference_centers_px)
            ],
            "angle_error_deg": result.angle_error_deg,
        })
    return data
