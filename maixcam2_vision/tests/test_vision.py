"""用合成图像与模拟时钟验证流程；测试不修改实际标定文件。"""

from contextlib import redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from maixcam2_vision.calibrate import calibrate, parse_args
from maixcam2_vision.camera_io import Frame, ImagePipeline, MaixSource, load_frame
from maixcam2_vision.detectors.colors import load_color_config, make_all_color_masks, estimate_ranges
from maixcam2_vision.detectors.material_pickup_detector import MaterialPickupDetector
from maixcam2_vision.engine import VisionEngine
from maixcam2_vision.main import main, save_snapshot
from maixcam2_vision.settings import DEFAULT_CONFIG_DIR, load_settings, read_json, save_json
from maixcam2_vision.steps import step01_task
from maixcam2_vision.steps.step02_turntable import build_detector as turntable_detector
from maixcam2_vision.steps.step04_station import build_detector as ring_detector
from maixcam2_vision.task import Task
from maixcam2_vision.transport import LineParser, apply_command, encode_message, UARTTransport
from maixcam2_vision.workflow import STAGES, Workflow


TASK = "452+321+254+312"


def station_image():
    frame = np.full((720, 1280, 3), 240, np.uint8)
    for x in (380, 640, 900):
        for radius in (82, 68, 54, 40, 26, 12):
            cv2.circle(frame, (x, 360), radius, (20, 20, 20), 3, cv2.LINE_AA)
    for y in (230, 490):
        cv2.line(frame, (110, y), (1170, y), (20, 20, 20), 3)
    return frame


def material_image(offset=0):
    frame = np.full((720, 1280, 3), 240, np.uint8)
    # 使用阈值内部的 HSV 值，避免把合成颜色误当成实际物料标定。
    for center, hsv in (
        ((450+offset, 160), (70, 200, 170)),
        ((820+offset, 160), (0, 0, 30)),
        ((640+offset, 450), (25, 180, 200)),
    ):
        color = cv2.cvtColor(np.uint8([[hsv]]), cv2.COLOR_HSV2BGR)[0, 0]
        cv2.circle(frame, center, 35, tuple(int(v) for v in color), -1)
    return frame


def material_config():
    document = read_json(DEFAULT_CONFIG_DIR / "material_pickup_detector.json")
    document["calibrated"] = True
    document["regions"] = {
        "workspace": {"x": 250, "y": 40, "width": 750, "height": 560},
        "left": {"x": 350, "y": 80, "width": 220, "height": 180},
        "right": {"x": 730, "y": 80, "width": 220, "height": 180},
        "down": {"x": 540, "y": 350, "width": 220, "height": 180},
    }
    return document


class TaskWorkflowTests(unittest.TestCase):
    def test_second_storage_is_same_color_mapping(self):
        plan = Task.parse(TASK).plan(2)
        self.assertEqual([item["rough_ring"] for item in plan], [3, 1, 2])
        self.assertEqual([item["storage_ring"] for item in plan], [1, 2, 3])
        self.assertEqual([item["layer"] for item in plan], [2, 2, 2])

    def test_reject_invalid_task(self):
        for text in (None, "", TASK+" ", "４52+321+254+312",
                     "452+321+253+312", "442+321+244+312",
                     "452+331+254+312", "452+321+254+301"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                Task.parse(text)

    def test_order_and_no_automatic_progression(self):
        workflow = Workflow()
        with self.assertRaises(ValueError):
            workflow.select(2)
        workflow.set_task(TASK)
        for stage in STAGES:
            workflow.select(stage.number)
            self.assertEqual(workflow.stage, stage)
        self.assertEqual(workflow.mode, "idle")
        workflow.restart()
        self.assertEqual(workflow.step, 1)
        self.assertIsNone(workflow.task)

    def test_lock_task_and_clear_histories(self):
        workflow = Workflow(4, TASK)
        generation = workflow.generation
        workflow.retry()
        self.assertGreater(workflow.generation, generation)
        workflow.set_mode("stacking")
        self.assertEqual(workflow.mode, "stacking")
        workflow.select(6)
        self.assertEqual(workflow.mode, "rings")
        with self.assertRaises(ValueError):
            workflow.set_task("123+123+321+321")
        with self.assertRaises(ValueError):
            workflow.select(True)
        workflow.select(2)
        with self.assertRaises(ValueError):
            workflow.set_mode("rings")

    def test_external_input_is_optional_and_keeps_existing_task_interface(self):
        workflow = Workflow()
        self.assertIsNone(step01_task.read_external_task())
        self.assertFalse(step01_task.process(workflow)[0])
        self.assertIsNone(workflow.task)
        with patch.object(step01_task, "read_external_task", return_value=TASK):
            self.assertTrue(step01_task.process(workflow)[0])
        self.assertEqual(workflow.task, Task.parse(TASK))
        # 接收入口返回 None 表示本轮没有新报文，已经锁定的任务仍保留。
        self.assertTrue(step01_task.process(workflow)[0])
        self.assertEqual(workflow.step, 1)

    def test_received_task_is_locked_even_before_leaving_step_one(self):
        workflow = Workflow(1, TASK)
        original_generation = workflow.generation
        with patch.object(step01_task, "read_external_task", return_value=TASK):
            step01_task.process(workflow)
        self.assertEqual(workflow.generation, original_generation)
        with patch.object(step01_task, "read_external_task", return_value="123+123+321+321"):
            with self.assertRaises(ValueError):
                step01_task.process(workflow)
        self.assertEqual(workflow.task.text, TASK)
        workflow.restart()
        with patch.object(step01_task, "read_external_task", return_value="123+123+321+321"):
            step01_task.process(workflow)
        self.assertEqual(workflow.task.text, "123+123+321+321")


class ProtocolTests(unittest.TestCase):
    def test_optional_set_task_still_uses_same_validation_and_lock(self):
        workflow = Workflow()
        ack = apply_command(workflow, {"command": "set_task", "task": TASK, "id": 1})
        self.assertTrue(ack["ok"])
        self.assertEqual(ack["task"], TASK)
        self.assertEqual(workflow.step, 1)
        generation = workflow.generation
        apply_command(workflow, {"command": "set_task", "task": TASK})
        self.assertEqual(workflow.generation, generation)
        with self.assertRaises(ValueError):
            apply_command(workflow, {"command": "set_task", "task": "123+123+321+321"})
        apply_command(workflow, {"command": "next"})
        self.assertEqual(workflow.step, 2)

    def test_fragmented_utf8_and_multiple_commands(self):
        wire = encode_message({"command": "status", "id": "中文"}) + b'{"command":"retry"}\r\n'
        parser = LineParser()
        messages = []
        for value in wire:
            messages.extend(parser.feed(bytes([value])))
        self.assertEqual(messages, [{"command": "status", "id": "中文"}, {"command": "retry"}])

    def test_noise_and_oversize_resynchronize(self):
        parser = LineParser()
        self.assertEqual(parser.feed(b'[]\nnot-json\n\xff\n' + b'x'*3000), [])
        self.assertEqual(parser.feed(b'{"command":"next"}\n'), [])
        self.assertEqual(parser.feed(b'{"command":"status"}\n'), [{"command": "status"}])

    def test_commands_validate_and_ack_generation(self):
        workflow = Workflow(1, TASK)
        ack = apply_command(workflow, {"command": "set_step", "step": 11, "id": 7})
        self.assertTrue(ack["ok"])
        self.assertEqual(ack["generation"], workflow.generation)
        self.assertEqual(ack["id"], 7)
        for message in ({"command": "motor"}, {"command": "set_step", "step": 13},
                        {"command": "set_step", "step": "4"}):
            with self.assertRaises(ValueError):
                apply_command(workflow, message)

    def test_uart_nonblocking_and_partial_write_disconnect(self):
        port = types.SimpleNamespace(read=lambda size: b'{"command":"status"}\n',
                                     write=lambda data: len(data)-1, close=lambda: None)
        fake = types.SimpleNamespace(
            uart=types.SimpleNamespace(UART=lambda *args: port),
            pinmap=types.SimpleNamespace(set_pin_function=lambda *args: None),
        )
        with patch.dict(sys.modules, {"maix": fake}):
            transport = UARTTransport({"device": "test", "baudrate": 115200, "pins": {}})
            self.assertEqual(transport.poll(), [{"command": "status"}])
            self.assertFalse(transport.send({"type": "result"}))
            self.assertIsNone(transport.port)


class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.colors = load_color_config(DEFAULT_CONFIG_DIR / "material_color_thresholds.json")

    def test_overlapping_colors_do_not_duplicate(self):
        config = copy.deepcopy(self.colors)
        config["colors"][5]["ranges"] = copy.deepcopy(config["colors"][2]["ranges"])
        frame = cv2.cvtColor(np.full((20, 20, 3), (110, 180, 150), np.uint8), cv2.COLOR_HSV2BGR)
        masks = make_all_color_masks(frame, config)
        self.assertEqual(np.count_nonzero(masks[3]), 0)
        self.assertEqual(np.count_nonzero(masks[6]), 0)

    def test_red_wrap_and_small_sample_rejection(self):
        hsv = np.full((20, 20, 3), (179, 180, 180), np.uint8)
        hsv[:10, :, 0] = 1
        bands = estimate_ranges(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR), 1)
        self.assertEqual(len(bands), 2)
        with self.assertRaises(ValueError):
            estimate_ranges(np.zeros((2, 2, 3), np.uint8), 1)

    def test_static_material_is_not_new_stop(self):
        detector = MaterialPickupDetector(material_config(), self.colors)
        for i in range(8):
            result = detector.detect(material_image(), timestamp=i*0.05)
            self.assertFalse(result.ready)
        self.assertEqual(result.state, "WAITING_FOR_MOTION")

    def test_material_requires_movement_then_stop(self):
        detector = MaterialPickupDetector(material_config(), self.colors)
        outputs = [detector.detect(material_image(offset), timestamp=i*0.05)
                   for i, offset in enumerate((0, 4, 8, 8, 8, 8))]
        self.assertTrue(outputs[-1].ready)
        self.assertEqual(outputs[-1].slot_colors, (4, 5, 2))
        detector.reset()
        self.assertFalse(detector.detect(material_image(8), timestamp=1).ready)

    def test_triple_rings_need_consecutive_quality_frames(self):
        detector = ring_detector(DEFAULT_CONFIG_DIR, "rough")
        self.assertFalse(detector.detect(station_image()).stable)
        detector.detect(station_image())
        result = detector.detect(station_image())
        self.assertTrue(result.stable)
        self.assertLess(abs(result.centers_px[1][0]-640), 1)
        result = detector.detect(np.full((720, 1280, 3), 240, np.uint8))
        self.assertFalse(result.detected)
        self.assertFalse(detector.detect(station_image()).stable)

    def test_turntable_outer_circle(self):
        detector = turntable_detector(DEFAULT_CONFIG_DIR, self.colors)
        frame = np.full((720, 1280, 3), 220, np.uint8)
        cv2.circle(frame, (640, 360), 300, (60, 60, 60), -1, cv2.LINE_AA)
        for _ in range(6):
            result = detector.detect(frame)
        self.assertTrue(result.stable)
        self.assertLess(abs(result.radius_px-300), 3)


class ConfigFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.folder = Path(self.temporary.name)
        self.config_dir = self.folder / "config"
        shutil.copytree(DEFAULT_CONFIG_DIR, self.config_dir)
        _, self.config = load_settings(self.config_dir)
        self.pipeline = ImagePipeline(self.config_dir, self.config["camera"])
        self.image = self.folder / "station.png"
        cv2.imencode(".png", station_image())[1].tofile(str(self.image))

    def tearDown(self):
        self.temporary.cleanup()

    def calibration(self, *args):
        return calibrate(parse_args(["--config-dir", str(self.config_dir), *map(str, args)]))


class CalibrationTests(ConfigFixture):
    def test_station_and_stacking_calibrate_separately(self):
        self.calibration("station", "--image", self.image, "--area", "rough",
                         "--outer-mm", 95, "--spacing-mm", 150, "--ring-order", 3, 2, 1)
        settings = read_json(self.config_dir / "vision.json")
        self.assertTrue(settings["areas"]["rough"]["reference_calibrated"])
        self.assertFalse(settings["areas"]["storage"]["reference_calibrated"])
        self.assertEqual(settings["areas"]["rough"]["ring_order"], [3, 2, 1])
        self.calibration("stacking", "--image", self.image, "--area", "rough",
                         "--outer-mm", 95, "--line-offset-mm", 75)
        settings = read_json(self.config_dir / "vision.json")
        self.assertTrue(settings["areas"]["rough"]["stacking_calibrated"])
        workflow = Workflow(5, TASK)
        engine = VisionEngine(self.config_dir, settings, workflow, self.pipeline.signature)
        for _ in range(3):
            event = engine.process(station_image(), engine.clock())
        self.assertTrue(event["ready"], event["detail"])
        self.assertTrue(event["data"]["side_centers_reconstructed"])
        self.assertFalse(event["data"]["material_alignment_verified"])
        self.assertEqual(event["data"]["numbering_confirmed"], True)

    def test_regions_validate_before_writing(self):
        before = (self.config_dir / "material_pickup_detector.json").read_bytes()
        with self.assertRaises(ValueError):
            self.calibration("regions", "--image", self.image,
                             "--workspace", 0, 0, 1280, 720, "--left", 100, 100, 200, 200,
                             "--right", 150, 150, 200, 200, "--down", 500, 500, 100, 100)
        self.assertEqual((self.config_dir / "material_pickup_detector.json").read_bytes(), before)
        self.calibration("regions", "--image", self.image,
                         "--workspace", 0, 0, 1280, 720, "--left", 100, 100, 200, 200,
                         "--right", 800, 100, 200, 200, "--down", 500, 500, 100, 100)
        self.assertTrue(read_json(self.config_dir / "material_pickup_detector.json")["calibrated"])

    def test_geometry_change_invalidates_other_calibrations(self):
        self.config["calibration_geometry"] = {"old": True}
        self.config["areas"]["rough"]["reference_calibrated"] = True
        self.config["areas"]["rough"]["ring_order"] = [1, 2, 3]
        self.config["color_calibrated_ids"] = [1, 2, 3]
        save_json(self.config_dir / "vision.json", self.config)
        self.calibration("colors", "--image", self.image, "--color", 5,
                         "--roi", 100, 100, 20, 20)
        settings = read_json(self.config_dir / "vision.json")
        self.assertEqual(settings["color_calibrated_ids"], [5])
        self.assertFalse(settings["areas"]["rough"]["reference_calibrated"])
        self.assertIsNone(settings["areas"]["rough"]["ring_order"])
        self.assertFalse(read_json(self.config_dir / "material_pickup_detector.json")["calibrated"])

    def test_processed_capture_mismatch_rejected(self):
        save_json(self.image.with_suffix(".json"), {"processed": True, "geometry": {}})
        with self.assertRaises(ValueError):
            self.calibration("colors", "--image", self.image, "--color", 1,
                             "--roi", 100, 100, 20, 20)

    def test_interrupted_station_save_leaves_reference_untrusted(self):
        arguments = ("station", "--image", self.image, "--area", "rough",
                     "--outer-mm", 95, "--spacing-mm", 150, "--ring-order", 1, 2, 3)
        self.calibration(*arguments)
        original_save = save_json

        def failing_save(path, document):
            if Path(path).name == "rough_rings.json":
                raise OSError("模拟磁盘写入失败")
            original_save(path, document)

        with patch("maixcam2_vision.calibrate.save_json", side_effect=failing_save):
            with self.assertRaises(OSError):
                self.calibration(*arguments)
        settings = read_json(self.config_dir / "vision.json")
        self.assertFalse(settings["areas"]["rough"]["reference_calibrated"])

    def test_stacking_requires_real_reference_lines(self):
        self.calibration("station", "--image", self.image, "--area", "rough",
                         "--outer-mm", 95, "--spacing-mm", 150, "--ring-order", 1, 2, 3)
        frame = station_image()
        frame[220:240] = 240
        frame[480:500] = 240
        cv2.imencode(".png", frame)[1].tofile(str(self.image))
        with self.assertRaises(ValueError):
            self.calibration("stacking", "--image", self.image, "--area", "rough",
                             "--outer-mm", 95, "--line-offset-mm", 75)
        self.assertFalse(read_json(self.config_dir / "vision.json")["areas"]["rough"]["stacking_calibrated"])


class EngineTests(ConfigFixture):
    def engine(self, step, clock=None):
        self.workflow = Workflow(step, TASK)
        kwargs = {"clock": clock} if clock else {}
        return VisionEngine(self.config_dir, self.config, self.workflow,
                            self.pipeline.signature, **kwargs)

    def test_uncalibrated_stable_does_not_become_ready(self):
        engine = self.engine(4)
        for _ in range(3):
            event = engine.process(station_image(), engine.clock())
        self.assertTrue(event["stable"])
        self.assertFalse(event["ready"])
        self.assertNotIn("within_tolerance", event["data"])

    def test_retry_and_step_change_clear_samples(self):
        engine = self.engine(4)
        for _ in range(3):
            event = engine.process(station_image(), engine.clock())
        self.assertTrue(event["stable"])
        old_generation = event["generation"]
        self.workflow.retry()
        event = engine.process(station_image(), engine.clock())
        self.assertFalse(event["stable"])
        self.assertGreater(event["generation"], old_generation)
        self.workflow.select(6)
        self.assertFalse(engine.process(station_image(), engine.clock())["stable"])

    def test_unavailable_has_no_old_coordinates(self):
        engine = self.engine(4)
        engine.process(station_image(), engine.clock())
        event = engine.unavailable("断线")
        self.assertFalse(event["ready"])
        self.assertEqual(event["data"], {})
        self.assertFalse(engine.process(station_image(), engine.clock())["stable"])

    def test_timeout_latches_until_retry(self):
        now = [0.0]
        engine = self.engine(4, lambda: now[0])
        blank = np.full((720, 1280, 3), 240, np.uint8)
        engine.process(blank, 0.0)
        now[0] = 11.0
        event = engine.process(blank, 11.0)
        self.assertEqual(event["state"], "timeout")
        self.assertEqual(engine.process(station_image(), 11.0)["data"], {})
        self.workflow.retry()
        self.assertNotEqual(engine.process(station_image(), 11.0)["state"], "timeout")

    def test_stale_input_clears_history(self):
        now = [10.0]
        engine = self.engine(4, lambda: now[0])
        for _ in range(3):
            engine.process(station_image(), 10.0)
        stale = engine.process(station_image(), 9.0)
        self.assertEqual(stale["state"], "stale")
        self.assertEqual(stale["data"], {})
        self.assertFalse(engine.process(station_image(), 10.0)["stable"])

    def test_processing_too_slow_never_returns_ready(self):
        now = [10.0]
        engine = self.engine(4, lambda: now[0])
        engine.reset()
        detector = types.SimpleNamespace(reset=lambda: None)
        engine.detector = detector

        def slow_detection(*args):
            now[0] += 0.6
            result = types.SimpleNamespace(detected=True, stable=True, detail="ok")
            return result, {"centers_px": [[100, 100]]}

        with patch("maixcam2_vision.engine.step04_station.process", side_effect=slow_detection):
            event = engine.process(station_image(), 10.0)
        self.assertEqual(event["state"], "stale")
        self.assertFalse(event["ready"])
        self.assertEqual(event["data"], {})
        self.assertGreaterEqual(event["age_ms"], 500)

    def test_waiting_for_external_task_needs_no_camera_or_observation_timeout(self):
        now = [0.0]
        workflow = Workflow()
        engine = VisionEngine(self.config_dir, self.config, workflow,
                              self.pipeline.signature, clock=lambda: now[0])
        for moment in (0.0, 11.0, 100.0):
            now[0] = moment
            event = engine.process(None, None)
            self.assertEqual(event["state"], "waiting_task")
            self.assertFalse(event["ready"])
            self.assertIsNone(event["task"])
            self.assertIsNone(event["captured_ms"])
            self.assertIsNone(event["age_ms"])

    def test_external_task_is_ready_without_camera_and_never_advances_step(self):
        workflow = Workflow()
        engine = VisionEngine(self.config_dir, self.config, workflow, self.pipeline.signature)
        with patch.object(step01_task, "read_external_task", return_value=TASK):
            event = engine.process(None, None)
        self.assertTrue(event["ready"])
        self.assertEqual(event["mode"], "task")
        self.assertEqual(event["task"], TASK)
        self.assertEqual(event["step"], 1)
        self.assertTrue(engine.process(None, None)["ready"])
        # 进入原有第二批暂存步骤时，颜色→第一批同色位置的计划保持一致。
        workflow.select(11)
        self.assertEqual([p["storage_ring"] for p in workflow.describe()["plan"]], [1, 2, 3])

    def test_bad_or_failed_receiver_does_not_replace_locked_task(self):
        engine = self.engine(1)
        generation = self.workflow.generation
        for malformed in ("bad", b"452+321+254+312", {"task": TASK}, "123+123+321+321"):
            with self.subTest(value=malformed):
                with patch.object(step01_task, "read_external_task", return_value=malformed):
                    event = engine.process(None, None)
                self.assertEqual(event["state"], "task_error")
                self.assertFalse(event["ready"])
                self.assertEqual(event["task"], TASK)
                self.assertEqual(self.workflow.generation, generation)
        with patch.object(step01_task, "read_external_task", side_effect=OSError("链路断开")):
            event = engine.process(None, None)
        self.assertEqual(event["state"], "task_error")
        self.assertTrue(engine.process(None, None)["ready"])

    def test_task_retry_keeps_task_restart_clears_it(self):
        engine = self.engine(1)
        self.workflow.retry()
        self.assertTrue(engine.process(None, None)["ready"])
        self.workflow.restart()
        event = engine.process(None, None)
        self.assertEqual(event["state"], "waiting_task")
        self.assertIsNone(event["task"])

    def test_entry_waits_for_task_without_opening_camera(self):
        output = io.StringIO()
        with patch("maixcam2_vision.main.MaixSource", side_effect=AssertionError("任务阶段不应打开相机")):
            with redirect_stdout(output):
                result = main(["--config-dir", str(self.config_dir), "--frames", "1", "--no-display"])
        self.assertEqual(result, 0)
        event = json.loads(output.getvalue().splitlines()[-1])
        self.assertEqual(event["state"], "waiting_task")
        self.assertEqual(event["step"], 1)

    def test_received_task_continues_into_original_vision_steps(self):
        class Commands:
            def __init__(self):
                self.count = 0

            def poll(self):
                self.count += 1
                return [{"command": "set_step", "step": 4}] if self.count == 2 else []

            def send(self, message):
                return True

            def close(self):
                pass

        source = types.SimpleNamespace(
            read=lambda: Frame(station_image(), time.monotonic()),
            close=lambda: None,
        )
        output = io.StringIO()
        with patch.object(step01_task, "read_external_task", return_value=TASK):
            with patch("maixcam2_vision.main.NullTransport", return_value=Commands()):
                with patch("maixcam2_vision.main.MaixSource", return_value=source) as camera:
                    with redirect_stdout(output):
                        result = main(["--config-dir", str(self.config_dir),
                                       "--frames", "4", "--no-display"])
        self.assertEqual(result, 0)
        camera.assert_called_once()
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(events[0]["step"], 1)
        self.assertEqual(events[0]["task"], TASK)
        self.assertTrue(events[0]["ready"])
        self.assertEqual(events[-1]["step"], 4)
        self.assertTrue(events[-1]["stable"])
        self.assertEqual(events[-1]["task"], TASK)

    def test_input_size_must_match_configuration(self):
        with self.assertRaises(ValueError):
            self.pipeline.process(np.zeros((480, 640, 3), np.uint8))

    def test_snapshot_metadata_and_offline_entry(self):
        event = {"step": 4}
        path = save_snapshot(self.folder / "截图", station_image(), self.pipeline, event)
        self.assertEqual(read_json(path.with_suffix(".json"))["geometry"], self.pipeline.signature)
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["--backend", "image", "--image", str(self.image),
                           "--config-dir", str(self.config_dir), "--step", "4",
                           "--task", TASK, "--frames", "3", "--no-display"])
        self.assertEqual(result, 0)
        messages = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertTrue(messages[-1]["stable"])
        self.assertTrue(messages[-1]["offline"])
        self.assertFalse(messages[-1]["ready"])
        self.assertLess(len(encode_message(messages[-1])), 2048)

    def test_saved_processed_image_skips_second_remap(self):
        path = save_snapshot(self.folder, station_image(), self.pipeline, {"step": 4})
        with patch.object(self.pipeline, "process", side_effect=AssertionError("不应二次处理")):
            image = load_frame(path, self.pipeline)
        self.assertTrue(np.array_equal(image, station_image()))
        # 外部原始图片则必须走当前图像管线。
        with patch.object(self.pipeline, "process", wraps=self.pipeline.process) as process:
            load_frame(self.image, self.pipeline)
        process.assert_called_once()

    def test_direct_main_entry_from_another_directory(self):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join(sys.path)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run([sys.executable, str(DEFAULT_CONFIG_DIR.parent / "main.py"), "--list-steps"],
                                cwd=self.folder, env=environment, capture_output=True, text=True,
                                encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 12)


class MaixAPITests(unittest.TestCase):
    def test_camera_converts_rgb_to_bgr_without_scanning(self):
        calls = []
        # 只提供取图对象；不提供任何二维码 API，保证后续视觉不再调用扫码。
        picture = object()
        fake = types.SimpleNamespace(
            camera=types.SimpleNamespace(Camera=lambda *args, **kwargs: types.SimpleNamespace(
                read=lambda: picture, close=lambda: None)),
            image=types.SimpleNamespace(Format=types.SimpleNamespace(FMT_RGB888=1),
                image2cv=lambda img, **kwargs: calls.append(kwargs) or np.zeros((720, 1280, 3), np.uint8)),
        )
        with patch.dict(sys.modules, {"maix": fake}):
            source = MaixSource({"width": 1280, "height": 720, "fps": 30})
            packet = source.read()
            source.close()
        self.assertEqual(packet.bgr.shape, (720, 1280, 3))
        self.assertEqual(calls, [{"ensure_bgr": True, "copy": True}])


if __name__ == "__main__":
    unittest.main()
