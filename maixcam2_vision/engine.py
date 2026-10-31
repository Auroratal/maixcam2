"""按比赛步骤调度视觉算法，产生统一结果，不推进机械动作。"""

import time

from .detectors.colors import load_color_config
from .steps.step01_qrcode import QRStep
from .steps import step02_turntable, step03_material, step04_station, step05_stacking


class VisionEngine:
    def __init__(self, config_dir, config, workflow, camera_signature, clock=time.monotonic):
        self.config_dir = config_dir
        self.config = config
        self.workflow = workflow
        self.signature = camera_signature
        self.clock = clock
        self.colors = load_color_config(config_dir / "material_color_thresholds.json")
        self.qr = QRStep(config["qr_confirmations"])
        self.detector = None
        self.generation = None
        self.started_s = clock()
        self.timed_out = False
        self.sequence = 0

    def reset(self):
        self.detector = None
        self.qr.reset()
        self.generation = self.workflow.generation
        self.started_s = self.clock()
        self.timed_out = False

    def _detector(self):
        if self.detector is None:
            mode, area = self.workflow.mode, self.workflow.stage.area
            if mode == "turntable":
                self.detector = step02_turntable.build_detector(self.config_dir, self.colors)
            elif mode == "material":
                self.detector = step03_material.build_detector(self.config_dir, self.colors)
            elif mode == "rings":
                self.detector = step04_station.build_detector(self.config_dir, area)
            elif mode == "stacking":
                self.detector = step05_stacking.build_detector(self.config_dir, area, self.signature)
        return self.detector

    def _event(self, state, detail, captured_s=None, detected=False, stable=False,
               ready=False, data=None):
        self.sequence += 1
        return {
            "version": 1, "type": "result", "seq": self.sequence,
            "generation": self.workflow.generation,
            **self.workflow.describe(),
            "state": state, "detail": detail, "detected": detected,
            "stable": stable, "ready": ready, "data": data or {},
            "captured_ms": None if captured_s is None else int(captured_s * 1000),
            "age_ms": None if captured_s is None else max(0, int((self.clock()-captured_s)*1000)),
            "ttl_ms": self.config["freshness_ms"],
        }

    def unavailable(self, detail):
        # 相机断开就丢弃连续帧证据和坐标，禁止继续报告旧结果。
        self.reset()
        return self._event("camera_unavailable", detail)

    def process(self, frame, captured_s, qr_payloads=None):
        if self.generation != self.workflow.generation:
            self.reset()
        mode = self.workflow.mode
        if mode == "idle":
            return self._event("return_stage", "返场由车辆系统执行", captured_s)
        if self.timed_out:
            return self._event("timeout", "本步骤观测超时，请重试或切换步骤", captured_s)
        if self.clock() - captured_s > self.config["freshness_ms"] / 1000:
            # 捕获到处理之前已经太旧，不能积累稳定历史。
            if self.detector:
                self.detector.reset()
            self.qr.reset()
            return self._event("stale", "输入图像已过期", captured_s)

        result = None
        if mode == "qr":
            task, detail = self.qr.process(qr_payloads or [], self.workflow.task)
            if task:
                self.workflow.set_task(task.text)
                # 任务变化更新了 generation，当前锁定任务本身仍是有效证据。
                self.generation = self.workflow.generation
            detected = bool(qr_payloads)
            stable = ready = task is not None
            data = {"candidate": self.qr.candidate, "confirmations": self.qr.count}
        else:
            detector = self._detector()
            if mode == "turntable":
                result, data = step02_turntable.process(
                    detector, frame, self.config["turntable_target_px"],
                )
            elif mode == "material":
                result, data = step03_material.process(
                    detector, frame, captured_s, self.workflow.task, self.workflow.stage.batch,
                )
            else:
                area = self.config["areas"][self.workflow.stage.area]
                module = step04_station if mode == "rings" else step05_stacking
                result, data = module.process(
                    detector, frame, area["ring_order"], area["reference_calibrated"],
                )
            detected, stable = result.detected, result.stable
            ready = bool(stable)
            detail = result.detail
            # 作者的阈值和参考零点只是搜索初值，不视为本机已完成标定。
            if mode == "turntable" and self.config["turntable_target_px"] is None:
                ready = False
                detail = "转盘参考圆心尚未标定；" + detail
            elif mode == "material":
                sampled = set(self.config["color_calibrated_ids"])
                needed = set(self.workflow.task.first_colors)
                ready = ready and needed.issubset(sampled) and data.get("task_colors_match", False)
                if not needed.issubset(sampled):
                    detail = "本轮颜色尚未全部采样标定；" + detail
            elif mode in ("rings", "stacking"):
                ready = ready and area["reference_calibrated"] and area["ring_order"] is not None
                if mode == "stacking":
                    ready = ready and area["stacking_calibrated"]
                if not ready and stable:
                    detail = "图像稳定，工位标定或环号映射尚未确认"

        geometry = self.config["calibration_geometry"]
        if mode != "qr" and geometry != self.signature:
            ready = False
            detail = "本机图像几何未标定或已变化；" + detail
        if self.clock() - captured_s > self.config["freshness_ms"] / 1000:
            stable = ready = False
            state = "stale"
            detail = "本帧处理耗时超过有效期，结果不可用于动作"
            data = {}
            if self.detector:
                self.detector.reset()
            self.qr.reset()
        else:
            state = "ready" if ready else "observing"
        # 稳定的有效观测可持续用于对齐；只对一直得不到可用观测的情况计超时。
        if ready:
            self.started_s = self.clock()
        elif self.clock() - self.started_s >= self.config["observation_timeout_s"]:
            self.timed_out = True
            state, ready, stable, data = "timeout", False, False, {}
            detail = "本步骤观测超时，已停止提供可用结果"
        return self._event(state, detail, captured_s, detected, stable, ready, data)
