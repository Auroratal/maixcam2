"""可选的通用 JSON 行接口；默认关闭，不依赖任何单片机 SDK。

任何能收发 UART 字节流的平台都可以自行实现相同协议。
每行一个 UTF-8 JSON 对象，以 LF 结束；不再使用原 F407 二进制协议。
"""

import json
import time


MAX_LINE_BYTES = 2048


def encode_message(message):
    return (json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


class LineParser:
    def __init__(self):
        self.buffer = bytearray()
        self.discarding = False

    def feed(self, data):
        commands = []
        # 超长行丢弃至下一行，避免把截断尾部误认为一条新命令。
        for value in data:
            if value == 10:
                if not self.discarding and self.buffer:
                    try:
                        command = json.loads(self.buffer.decode("utf-8"))
                        if isinstance(command, dict):
                            commands.append(command)
                    except (UnicodeError, ValueError):
                        pass
                self.buffer.clear()
                self.discarding = False
            elif not self.discarding:
                self.buffer.append(value)
                if len(self.buffer) > MAX_LINE_BYTES:
                    self.buffer.clear()
                    self.discarding = True
        return commands


def apply_command(workflow, message):
    """仅允许改变视觉状态；没有电机、抓取或车辆控制命令。"""
    command = message.get("command")
    if command == "set_step":
        workflow.select(message.get("step"))
    elif command == "next":
        workflow.select(workflow.step + 1)
    elif command == "previous":
        workflow.select(workflow.step - 1)
    elif command == "retry":
        workflow.retry()
    elif command == "restart":
        workflow.restart()
    elif command == "set_task":
        workflow.set_task(message.get("task"))
    elif command == "set_mode":
        workflow.set_mode(message.get("mode"))
    elif command != "status":
        raise ValueError("未知视觉命令")
    return {"version": 1, "type": "ack", "id": message.get("id"), "ok": True,
            "generation": workflow.generation, **workflow.describe()}


class NullTransport:
    """未启用串口时，独立预览和单步调试不需要连接任何主控。"""

    def poll(self):
        return []

    def send(self, message):
        return True

    def close(self):
        pass


class UARTTransport:
    def __init__(self, config):
        self.config = config
        self.port = None
        self.parser = LineParser()
        self.retry_at = 0.0

    def _open(self):
        if self.port is not None:
            return True
        if time.monotonic() < self.retry_at:
            return False
        try:
            from maix import uart, pinmap
            for pin, function in self.config["pins"].items():
                pinmap.set_pin_function(pin, function)
            self.port = uart.UART(self.config["device"], self.config["baudrate"])
            return True
        except Exception:
            self.close()
            return False

    def poll(self):
        if not self._open():
            return []
        try:
            # read 默认非阻塞。接收数量设上限，避免持续输入占住图像主循环。
            data = self.port.read(4096)
            return self.parser.feed(data or b"")
        except Exception:
            self.close()
            return []

    def send(self, message):
        if not self._open():
            return False
        try:
            frame = encode_message(message)
            if self.port.write(frame) != len(frame):
                self.close()
                return False
            return True
        except Exception:
            self.close()
            return False

    def close(self):
        if self.port is not None:
            try:
                self.port.close()
            except Exception:
                pass
        self.port = None
        self.parser = LineParser()
        self.retry_at = time.monotonic() + 1.0
