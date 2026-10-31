"""相机与图像坐标统一入口；MaixCAM2 不依赖桌面 OpenCV 窗口。"""

from dataclasses import dataclass
import json
from pathlib import Path
import time

import cv2
import numpy as np

from .detectors.stacked_ring_detector import camera_geometry_signature


@dataclass
class Frame:
    bgr: object
    captured_s: float
    qr_payloads: object = None
    processed: bool = False


def load_frame(path, pipeline):
    """截图附带几何元数据时避免二次矫正；其他图片按相机原图处理。"""
    path = Path(path)
    frame = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f"无法读取图片 {path}")
    metadata_path = path.with_suffix(".json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    if metadata.get("processed"):
        if metadata.get("geometry") != pipeline.signature:
            raise ValueError("截图的图像几何与当前设置不同，请重新采集")
        if (frame.shape[1], frame.shape[0]) != pipeline.size:
            raise ValueError("截图分辨率与元数据不一致")
        return frame
    return pipeline.process(frame)


class ImagePipeline:
    def __init__(self, config_dir, camera_config):
        self.camera_config = camera_config
        self.size = (camera_config["width"], camera_config["height"])
        calibration_path = Path(config_dir) / camera_config["calibration_file"]
        self.signature = camera_geometry_signature(
            *self.size, camera_config["undistort"], calibration_path,
        )
        self.maps = None
        if camera_config["undistort"]:
            storage = cv2.FileStorage(str(calibration_path), cv2.FILE_STORAGE_READ)
            try:
                matrices = [storage.getNode(name).mat() for name in (
                    "camera_matrix", "distortion_coefficients", "new_camera_matrix",
                )]
                stored_size = tuple(int(storage.getNode(name).real()) for name in (
                    "image_width", "image_height",
                ))
            finally:
                storage.release()
            if stored_size != self.size or any(matrix is None for matrix in matrices):
                raise ValueError("相机标定文件不完整或与当前分辨率不一致")
            self.maps = cv2.initUndistortRectifyMap(
                matrices[0], matrices[1], None, matrices[2], self.size, cv2.CV_16SC2,
            )

    def process(self, frame):
        if frame is None or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("相机必须返回 BGR 三通道图像")
        if (frame.shape[1], frame.shape[0]) != self.size:
            raise ValueError(f"图像分辨率应为 {self.size}，不得静默缩放后套用旧标定")
        return cv2.remap(frame, *self.maps, cv2.INTER_LINEAR) if self.maps else frame.copy()


class MaixSource:
    """只在真机运行时导入 maix，电脑上的任务与算法测试不需要该模块。"""

    def __init__(self, camera_config):
        from maix import camera, image
        self.image = image
        self.camera = camera.Camera(
            camera_config["width"], camera_config["height"],
            image.Format.FMT_RGB888, fps=camera_config["fps"],
        )

    def read(self, want_qr=False):
        img = self.camera.read()
        captured_s = time.monotonic()
        payloads = [code.payload() for code in img.find_qrcodes()] if want_qr else None
        bgr = self.image.image2cv(img, ensure_bgr=True, copy=True)
        return Frame(bgr, captured_s, payloads)

    def close(self):
        close = getattr(self.camera, "close", None)
        if close:
            close()


class DesktopSource:
    def __init__(self, device, camera_config):
        device = int(device) if str(device).isdigit() else device
        self.camera = cv2.VideoCapture(device)
        for key, value in (
            (cv2.CAP_PROP_FRAME_WIDTH, camera_config["width"]),
            (cv2.CAP_PROP_FRAME_HEIGHT, camera_config["height"]),
            (cv2.CAP_PROP_FPS, camera_config["fps"]),
        ):
            self.camera.set(key, value)
        if not self.camera.isOpened():
            self.close()
            raise OSError(f"无法打开电脑相机 {device}")

    def read(self, want_qr=False):
        ok, frame = self.camera.read()
        if not ok:
            raise OSError("摄像头未返回新画面")
        return Frame(frame, time.monotonic())

    def close(self):
        self.camera.release()


class StillSource:
    """离线图片只验证算法，不把它解释为真实转盘运动。"""

    def __init__(self, path, pipeline):
        self.frame = load_frame(path, pipeline)

    def read(self, want_qr=False):
        return Frame(self.frame.copy(), time.monotonic(), processed=True)

    def close(self):
        pass


class DesktopQR:
    def __init__(self):
        self.detector = cv2.QRCodeDetector()

    def decode(self, frame):
        # 优先多码解码，避免画面里出现两个任务码时任意选取。
        ok, payloads, _, _ = self.detector.detectAndDecodeMulti(frame)
        if ok:
            return [text for text in payloads if text]
        payload, _, _ = self.detector.detectAndDecode(frame)
        return [payload] if payload else []
