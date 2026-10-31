"""MaixCAM2 智能搬运视觉入口：默认独立运行，不连接任何主控板。"""

from pathlib import Path
import sys

# MaixVision 安装后的目录名称可能改变，用固定包名加载本工程。
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
import json
import time

import cv2
from .camera_io import ImagePipeline, MaixSource, DesktopSource, StillSource, DesktopQR
from .engine import VisionEngine
from .settings import DEFAULT_CONFIG_DIR, load_settings, save_json
from .transport import NullTransport, UARTTransport, apply_command, encode_message
from .ui import Preview
from .workflow import Workflow, STAGES


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("maix", "desktop", "image"), default="maix")
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--step", type=int, default=1, help="按比赛顺序选择 1~12")
    parser.add_argument("--task", help="调试时预设任务，例如 452+321+254+312")
    parser.add_argument("--device", default="0", help="电脑端相机编号")
    parser.add_argument("--image", type=Path, help="backend=image 时的原始输入图片")
    parser.add_argument("--frames", type=int, help="处理帧数上限；图片模式默认 1 帧")
    parser.add_argument("--no-display", action="store_true", help="关闭预览，仍输出 JSON")
    parser.add_argument("--output-jsonl", type=Path, help="额外记录观测与命令结果")
    parser.add_argument("--snapshot-dir", type=Path, default=Path(__file__).with_name("captures"))
    parser.add_argument("--list-steps", action="store_true")
    args = parser.parse_args(argv)
    if args.backend == "image" and not args.image and not args.list_steps:
        parser.error("--backend image 需要 --image")
    if args.frames is not None and args.frames <= 0:
        parser.error("--frames 必须大于 0")
    if args.backend == "image" and args.frames is None:
        args.frames = 1
    return args


def save_snapshot(folder, frame, pipeline, event):
    if frame is None:
        raise ValueError("没有新鲜图像，不能保存标定图")
    folder.mkdir(parents=True, exist_ok=True)
    name = f"step{event['step']:02d}_{time.time_ns()}"
    image_path = folder / (name + ".png")
    ok, encoded = cv2.imencode(".png", frame)
    if not ok:
        raise OSError("PNG 编码失败")
    encoded.tofile(str(image_path))
    # 保存的是进入算法前的处理图，标定工具检查旁边的几何签名避免二次矫正。
    save_json(image_path.with_suffix(".json"), {
        "processed": True, "geometry": pipeline.signature, "step": event["step"],
    })
    return image_path


def run(args):
    if args.list_steps:
        for stage in STAGES:
            print(f"{stage.number:02d} {stage.name} ({stage.detector})")
        return 0
    config_dir, config = load_settings(args.config_dir)
    workflow = Workflow(args.step, args.task)
    pipeline = ImagePipeline(config_dir, config["camera"])
    engine = VisionEngine(config_dir, config, workflow, pipeline.signature)
    preview_backend = "none" if args.no_display or args.backend == "image" else args.backend
    preview = Preview(preview_backend)
    if config["uart"]["enabled"] and args.backend != "maix":
        raise ValueError("UART 接口只在 MaixCAM2 上启用；电脑验证时请关闭 uart.enabled")
    transport = UARTTransport(config["uart"]) if config["uart"]["enabled"] else NullTransport()
    log = None
    if args.output_jsonl:
        args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
        log = args.output_jsonl.open("w", encoding="utf-8")
    source, qr_decoder = None, None
    source_retry_s = 0.0
    last_emit_s = 0.0
    previous_state = None
    notice, notice_until = "", 0.0
    frame_count = 0
    frame = None

    def emit(event):
        line = encode_message(event).decode("utf-8")
        print(line, end="", flush=True)
        if log:
            log.write(line)
            log.flush()
        transport.send(event)

    try:
        while True:
            for command in transport.poll():
                try:
                    emit(apply_command(workflow, command))
                except (TypeError, ValueError) as error:
                    emit({"version": 1, "type": "ack", "id": command.get("id"),
                          "ok": False, "detail": str(error)})
            # 触摸按钮只用于现场运行前的视觉调试，不替代比赛启动按钮。
            for action in preview.poll():
                if action == "quit":
                    return 0
                try:
                    if action == "snapshot":
                        if frame is None or time.monotonic() - last_capture_s > config["freshness_ms"]/1000:
                            raise ValueError("当前图像已失效，请等待相机恢复")
                        path = save_snapshot(args.snapshot_dir, frame, pipeline, event)
                        emit({"version": 1, "type": "snapshot", "path": str(path)})
                    else:
                        command = {"command": action}
                        if action == "toggle":
                            command = {"command": "set_mode",
                                       "mode": "rings" if workflow.mode == "stacking" else "stacking"}
                        emit(apply_command(workflow, command))
                    notice, notice_until = "", 0
                except (OSError, TypeError, ValueError) as error:
                    emit({"version": 1, "type": "error", "detail": str(error)})
                    notice, notice_until = "Action rejected - see log", time.monotonic()+2

            now = time.monotonic()
            if source is None and now >= source_retry_s:
                try:
                    if args.backend == "maix":
                        source = MaixSource(config["camera"])
                    elif args.backend == "desktop":
                        source = DesktopSource(args.device, config["camera"])
                    else:
                        source = StillSource(args.image, pipeline)
                    engine.reset()
                except Exception as error:
                    if args.backend == "image":
                        raise
                    source_retry_s = now + 1
                    camera_error = str(error)

            if source is None:
                frame = None
                event = engine.unavailable(camera_error)
            else:
                try:
                    packet = source.read(want_qr=workflow.mode == "qr")
                    frame = packet.bgr if packet.processed else pipeline.process(packet.bgr)
                    last_capture_s = packet.captured_s
                    payloads = packet.qr_payloads
                    if workflow.mode == "qr" and payloads is None:
                        if qr_decoder is None:
                            qr_decoder = DesktopQR()
                        payloads = qr_decoder.decode(frame)
                    event = engine.process(frame, packet.captured_s, payloads)
                    frame_count += 1
                except (ValueError, cv2.error) as error:
                    # 配置/算法失败时不报告旧坐标；重试可重新加载检测器。
                    engine.reset()
                    frame = None
                    event = engine._event("error", str(error))
                except Exception as error:
                    source.close()
                    source = None
                    source_retry_s = time.monotonic() + 1
                    frame = None
                    event = engine.unavailable(str(error))

            if args.backend == "image":
                event["offline"] = True
            state = (workflow.generation, event["state"])
            now = time.monotonic()
            if state != previous_state or now-last_emit_s >= 1/config["result_hz"] or (
                args.frames and frame_count >= args.frames
            ):
                emit(event)
                previous_state, last_emit_s = state, now
            preview.show(frame, event, workflow.stage.label, notice if now < notice_until else "")
            if args.frames and frame_count >= args.frames:
                return 0
            if args.backend == "image" and event["state"] == "error":
                return 1
            if source is None:
                time.sleep(0.05)
    finally:
        if source:
            source.close()
        transport.close()
        preview.close()
        if log:
            log.close()


def main(argv=None):
    try:
        return run(parse_args(argv))
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        print(json.dumps({"version": 1, "type": "error", "detail": str(error)},
                         ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
