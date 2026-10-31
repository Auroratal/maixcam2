"""离线标定工具：使用预览保存的无叠字图片，所有坐标均为原图像素。"""

from pathlib import Path
import sys

if __package__ in (None, ""):
    import importlib.util
    _spec = importlib.util.spec_from_file_location(
        "maixcam2_vision", Path(__file__).with_name("__init__.py"),
        submodule_search_locations=[str(Path(__file__).resolve().parent)],
    )
    _package = importlib.util.module_from_spec(_spec)
    sys.modules["maixcam2_vision"] = _package
    _spec.loader.exec_module(_package)
    __package__ = "maixcam2_vision"

import argparse
import copy
from dataclasses import replace
import json
import math

import cv2
import numpy as np

from .camera_io import ImagePipeline, load_frame
from .detectors.colors import estimate_ranges
from .detectors.material_pickup_detector import validate_material_pickup_config
from .detectors.ring_station_detector import load_ring_station_config, _raw_detection
from .detectors.stacked_ring_detector import (
    ellipse_shape_matrix, find_calibration_outer_ring, detect_scaled_reference_lines,
    load_stacked_ring_config, make_search_calibration,
)
from .steps.step02_turntable import build_detector
from .detectors.colors import load_color_config
from .settings import DEFAULT_CONFIG_DIR, load_settings, read_json, save_json


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("必须输入有限正数")
    return number


def rectangle(values, frame):
    x, y, width, height = values
    if min(x, y) < 0 or min(width, height) <= 0 or (
        x + width > frame.shape[1] or y + height > frame.shape[0]
    ):
        raise ValueError("ROI 越界；顺序应为 x y 宽 高，坐标来自原图")
    return {"x": x, "y": y, "width": width, "height": height}


def invalidate(config, config_dir, signature):
    """清除可信标记，同时丢弃依赖画面位置的 ROI 和搜索尺度。"""
    config["calibration_geometry"] = signature
    config["color_calibrated_ids"] = []
    config["turntable_target_px"] = None
    documents = {}
    material = read_json(config_dir / "material_pickup_detector.json")
    material.update({
        "calibrated": False, "image_width": signature["image_size"][0],
        "image_height": signature["image_size"][1],
        "regions": dict.fromkeys(("workspace", "left", "right", "down")),
    })
    documents["material_pickup_detector.json"] = material
    for area in ("rough", "storage"):
        config["areas"][area].update({
            "reference_calibrated": False, "stacking_calibrated": False, "ring_order": None,
        })
        document = read_json(config_dir / f"{area}_stacking.json")
        document["search_calibration"] = None
        documents[f"{area}_stacking.json"] = document
    return documents


def commit(config_dir, config, signature, changed, documents):
    """先撤销受影响的可信标记，再更新文件；中断后也不会信任半份标定。"""
    current = copy.deepcopy(config)
    pending = {}
    if current["calibration_geometry"] != signature:
        pending.update(invalidate(current, config_dir, signature))
    final = copy.deepcopy(current)
    changed(final)
    pending.update(documents)
    # 同一套几何下重标某项，也先撤销该项；其他工位的标定仍有效。
    for key in ("turntable_target_px", "color_calibrated_ids", "areas"):
        if final[key] != current[key]:
            if key == "areas":
                for area in ("rough", "storage"):
                    if final[key][area] != current[key][area]:
                        current[key][area]["reference_calibrated"] = False
                        current[key][area]["stacking_calibrated"] = False
            elif key == "color_calibrated_ids":
                current[key] = []
            else:
                current[key] = None
    # 更新已有颜色/ROI 时，标记数值可能相同，仍必须先失效。
    if "material_color_thresholds.json" in documents:
        current["color_calibrated_ids"] = []
    for area in ("rough", "storage"):
        if f"{area}_rings.json" in documents:
            current["areas"][area]["reference_calibrated"] = False
            current["areas"][area]["stacking_calibrated"] = False
        elif f"{area}_stacking.json" in documents:
            current["areas"][area]["stacking_calibrated"] = False
    if "material_pickup_detector.json" in documents:
        temporary_material = copy.deepcopy(pending["material_pickup_detector.json"])
        temporary_material["calibrated"] = False
        temporary_material["regions"] = dict.fromkeys(("workspace", "left", "right", "down"))
        save_json(config_dir / "material_pickup_detector.json", temporary_material)
    save_json(config_dir / "vision.json", current)
    for filename, document in pending.items():
        save_json(config_dir / filename, document)
    save_json(config_dir / "vision.json", final)
    return final


def calibrate(args):
    config_dir, config = load_settings(args.config_dir)
    pipeline = ImagePipeline(config_dir, config["camera"])
    if args.action == "invalidate":
        updated = copy.deepcopy(config)
        documents = invalidate(updated, config_dir, pipeline.signature)
        # 首先写入失效状态，随后重置其余搜索配置。
        save_json(config_dir / "vision.json", updated)
        for name, document in documents.items():
            save_json(config_dir / name, document)
        return {"ok": True, "detail": "已清除全部标定可信标记，请重新采集"}
    frame = load_frame(args.image, pipeline)
    documents = {}
    report = {}
    if args.action == "colors":
        roi = rectangle(args.roi, frame)
        sample = frame[roi["y"]:roi["y"]+roi["height"], roi["x"]:roi["x"]+roi["width"]]
        ranges = estimate_ranges(sample, args.color)
        colors = load_color_config(config_dir / "material_color_thresholds.json")
        next(item for item in colors["colors"] if item["color_id"] == args.color)["ranges"] = ranges
        documents["material_color_thresholds.json"] = colors

        def changed(setting):
            setting["color_calibrated_ids"] = sorted(set(setting["color_calibrated_ids"]) | {args.color})
        report = {"color": args.color, "ranges": ranges}
    elif args.action == "regions":
        material = read_json(config_dir / "material_pickup_detector.json")
        material.update({
            "image_width": frame.shape[1], "image_height": frame.shape[0], "calibrated": True,
            "regions": {name: rectangle(getattr(args, name), frame)
                        for name in ("workspace", "left", "right", "down")},
        })
        validate_material_pickup_config(material)
        documents["material_pickup_detector.json"] = material

        def changed(setting):
            pass
        report = {"regions": material["regions"]}
    elif args.action == "station":
        document = read_json(config_dir / f"{args.area}_rings.json")
        ring_config = replace(
            load_ring_station_config(config_dir / f"{args.area}_rings.json"),
            center_spacing_mm=args.spacing_mm, outer_diameter_mm=args.outer_mm,
            ring1_side="left",
        )
        raw = _raw_detection(frame, ring_config)
        if raw is None or raw["confidence"] < ring_config.minimum_confidence:
            raise ValueError("三环不完整或置信度不足，请露出三个靶环后重新采集")
        if raw["residual"] > ring_config.maximum_affine_residual or not (
            ring_config.perspective_ratio_range[0] <= raw["perspective"]
            <= ring_config.perspective_ratio_range[1]
        ):
            raise ValueError("工位透视超出局部仿射适用范围，请调整视角")
        # 已知中心距给出平面横轴；已知外圈直径补全纵轴，求像素→毫米。
        ellipse, _ = find_calibration_outer_ring(frame, ring_config)
        centers = np.asarray(raw["centers"])
        axis_x = (centers[2] - centers[0]) / (2 * args.spacing_mm)
        remaining = ellipse_shape_matrix(ellipse) / (args.outer_mm / 2)**2 - np.outer(axis_x, axis_x)
        values, vectors = np.linalg.eigh(remaining)
        if values[-1] <= 0 or abs(values[0])/values[-1] > ring_config.maximum_affine_residual:
            raise ValueError("外圈尺寸与中心距不一致，无法建立局部毫米坐标")
        axis_y = math.sqrt(values[-1]) * vectors[:, -1]
        image_axes = np.column_stack((axis_x, axis_y))
        if np.linalg.det(image_axes) < 0:
            image_axes[:, 1] *= -1
        affine = np.linalg.inv(image_axes)
        document["geometry"].update({
            "center_spacing_mm": args.spacing_mm, "outer_diameter_mm": args.outer_mm,
            "ring1_side": "left",
        })
        document["reference"].update({
            "station_yaw_deg": raw["yaw"], "ring_centers_px": centers.tolist(),
            "image_to_station_affine": affine.tolist(),
        })
        document["profile_name"] = f"{args.area}_own_camera"
        documents[f"{args.area}_rings.json"] = document
        stacking = read_json(config_dir / f"{args.area}_stacking.json")
        stacking["search_calibration"] = None
        documents[f"{args.area}_stacking.json"] = stacking

        def changed(setting):
            setting["areas"][args.area].update({
                "reference_calibrated": True, "ring_order": args.ring_order,
                "stacking_calibrated": False,
            })
        report = {"area": args.area, "centers_px": centers.tolist(),
                  "image_to_station_affine": affine.tolist()}
    elif args.action == "stacking":
        if config["calibration_geometry"] != pipeline.signature or not (
            config["areas"][args.area]["reference_calibrated"]
        ):
            raise ValueError("请先完成同一图像几何下的 station 工位零点标定")
        ring = load_ring_station_config(config_dir / f"{args.area}_rings.json")
        stacking = load_stacked_ring_config(config_dir / f"{args.area}_stacking.json")
        if not math.isclose(args.outer_mm, ring.outer_diameter_mm, rel_tol=0.001):
            raise ValueError("外圈直径与 station 标定不一致")
        ellipse, _ = find_calibration_outer_ring(frame, ring, selection=args.middle)
        observation = detect_scaled_reference_lines(
            frame, ellipse, stacking, args.outer_mm, args.line_offset_mm,
            yaw_hint=ring.reference_yaw_deg, require_both=True,
        )
        search = make_search_calibration(
            observation, pipeline.signature, args.outer_mm, args.line_offset_mm,
        )
        document = read_json(config_dir / f"{args.area}_stacking.json")
        document["search_calibration"] = search
        documents[f"{args.area}_stacking.json"] = document

        def changed(setting):
            setting["areas"][args.area]["stacking_calibrated"] = True
        report = {"area": args.area, "search_calibration": search}
    else:
        detector = build_detector(config_dir, load_color_config(config_dir / "material_color_thresholds.json"))
        result = detector.detect(frame)
        if not result.detected:
            raise ValueError("转盘外圆未找到，请调整 turntable_detector.json 的半径搜索范围")
        center = [result.center_x_px, result.center_y_px]

        def changed(setting):
            setting["turntable_target_px"] = center
        report = {"target_px": center, "radius_px": result.radius_px}
    commit(config_dir, config, pipeline.signature, changed, documents)
    return {"ok": True, "action": args.action, **report}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("colors", "regions", "station", "stacking", "turntable", "invalidate"):
        command = sub.add_parser(action)
        if action != "invalidate":
            command.add_argument("--image", required=True, type=Path)
        if action in ("station", "stacking"):
            command.add_argument("--area", choices=("rough", "storage"), required=True)
            command.add_argument("--outer-mm", type=positive, required=True)
        if action == "colors":
            command.add_argument("--color", type=int, choices=range(1, 7), required=True)
            command.add_argument("--roi", type=int, nargs=4, required=True, metavar=("X", "Y", "W", "H"))
        elif action == "regions":
            for name in ("workspace", "left", "right", "down"):
                command.add_argument("--" + name, type=int, nargs=4, required=True)
        elif action == "station":
            command.add_argument("--spacing-mm", type=positive, required=True)
            command.add_argument("--ring-order", type=int, nargs=3, required=True)
        elif action == "stacking":
            command.add_argument("--line-offset-mm", type=positive, required=True)
            command.add_argument("--middle", type=float, nargs=2, help="中环原图 x y；不填则须自动找到唯一三环")
    args = parser.parse_args(argv)
    if args.action == "station" and set(args.ring_order) != {1, 2, 3}:
        parser.error("--ring-order 必须是从左到右的 1、2、3 排列")
    if args.action == "stacking" and (
        args.line_offset_mm <= args.outer_mm/2
        or args.middle is not None and not all(math.isfinite(v) for v in args.middle)
    ):
        parser.error("线到中环中心的距离必须大于外圈半径，选点必须是有限数")
    return args


def main(argv=None):
    try:
        print(json.dumps(calibrate(parse_args(argv)), ensure_ascii=False, allow_nan=False))
        return 0
    except (OSError, ValueError, cv2.error) as error:
        print(json.dumps({"ok": False, "detail": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
