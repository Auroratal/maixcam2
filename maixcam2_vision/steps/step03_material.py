"""第三、八步：找颜色位置，确认转动后减速；不执行抓取动作。"""

from ..detectors.material_pickup_detector import MaterialPickupDetector, load_material_pickup_config


def build_detector(config_dir, colors):
    return MaterialPickupDetector(
        load_material_pickup_config(config_dir / "material_pickup_detector.json"), colors,
    )


def process(detector, frame, timestamp, task, batch):
    result = detector.detect(frame, timestamp=timestamp)
    data = {"motion_state": result.state, "speed_px_s": result.max_speed_px_s}
    if result.detected:
        slots = dict(zip(("left", "right", "down"), result.slot_colors))
        data["slots"] = slots
        # 只按本帧找到的位置建立查表。空位不是颜色，不能作为抓取目标。
        data["color_to_slot"] = {
            str(color): name for name, color in slots.items() if color
        }
        colors = task.first_colors if batch == 1 else task.second_colors
        observed = [region.color_id for region in result.regions]
        data["task_colors_match"] = (
            len(observed) == len(set(observed)) and set(observed).issubset(colors)
        )
    return result, data
