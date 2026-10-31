"""六色 HSV 分割与离线采样，编号遵循智能搬运赛题。

沿用上游的多区间 HSV 思路。重叠像素暂不归入任何颜色，防止蓝/浅蓝
阈值交叉时把同一物料计成两件；需要通过重新标定消除大面积冲突。
"""

from pathlib import Path
import json
import math

import cv2
import numpy as np


COLOR_NAMES = {
    1: "red", 2: "yellow", 3: "blue", 4: "green",
    5: "black", 6: "light_blue",
}
COLOR_NAMES_ZH = {1: "红", 2: "黄", 3: "蓝", 4: "绿", 5: "黑", 6: "浅蓝"}
DISPLAY_BGR = {
    1: (0, 0, 255), 2: (0, 255, 255), 3: (255, 0, 0),
    4: (0, 200, 0), 5: (70, 70, 70), 6: (255, 220, 0),
}


def load_color_config(path):
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("color_space") != "OpenCV_HSV":
        raise ValueError("颜色配置必须使用 OpenCV HSV，不能填写 LAB 阈值")
    colors = document.get("colors", [])
    if len(colors) != 6 or {c["color_id"] for c in colors} != set(COLOR_NAMES):
        raise ValueError("颜色配置必须包含编号 1~6，各一次")
    for item in colors:
        if item["name"] != COLOR_NAMES[item["color_id"]] or not item["ranges"]:
            raise ValueError("颜色名称或 HSV 范围无效")
        for bounds in item["ranges"]:
            lower, upper = bounds["lower"], bounds["upper"]
            if len(lower) != 3 or len(upper) != 3 or any(
                type(a) is not int or type(b) is not int or not 0 <= a <= b <= limit
                for a, b, limit in zip(lower, upper, (179, 255, 255))
            ):
                raise ValueError("HSV 范围越界")
    return document


def make_all_color_masks(frame, config):
    """同一次转换生成六色蒙版，并剔除所有多色重叠像素。"""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    masks = {}
    for item in config["colors"]:
        mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        for bounds in item["ranges"]:
            mask |= cv2.inRange(
                hsv, np.asarray(bounds["lower"], dtype=np.uint8),
                np.asarray(bounds["upper"], dtype=np.uint8),
            )
        masks[item["color_id"]] = mask
    overlap = np.sum(np.stack([mask != 0 for mask in masks.values()]), axis=0) > 1
    for mask in masks.values():
        mask[overlap] = 0
    return masks


def estimate_ranges(bgr_sample, color_id):
    """用 ROI 像素的百分位估计阈值；红色跨 Hue 零点时拆成两个区间。"""
    hsv = cv2.cvtColor(bgr_sample, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(float)
    if len(hsv) < 100:
        raise ValueError("采样区域至少包含 100 个像素，请框选物料内部")
    saturation, value = hsv[:, 1], hsv[:, 2]
    if color_id == 5:
        return [{"lower": [0, 0, 0], "upper": [
            179, min(255, int(np.percentile(saturation, 98)) + 20),
            min(255, int(np.percentile(value, 98)) + 20),
        ]}]
    hue = hsv[:, 0]
    radians = hue * math.pi / 90.0
    mean = math.atan2(np.sin(radians).mean(), np.cos(radians).mean())
    center = (mean * 90.0 / math.pi) % 180
    delta = (hue - center + 90) % 180 - 90
    low = int(math.floor(np.percentile(delta, 2) + center - 3)) % 180
    high = int(math.ceil(np.percentile(delta, 98) + center + 3)) % 180
    s0 = max(0, int(np.percentile(saturation, 2)) - 15)
    s1 = min(255, int(np.percentile(saturation, 98)) + 15)
    v0 = max(0, int(np.percentile(value, 2)) - 20)
    v1 = min(255, int(np.percentile(value, 98)) + 20)
    bands = [(low, high)] if low <= high else [(0, high), (low, 179)]
    return [{"lower": [a, s0, v0], "upper": [b, s1, v1]} for a, b in bands]
