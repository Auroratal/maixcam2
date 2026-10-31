"""设备预览与单步调试界面。界面使用 ASCII 标签，源码保留中文说明。"""

import cv2
import numpy as np


class Preview:
    def __init__(self, backend):
        self.backend = backend
        self.pending = []
        self.was_pressed = False
        self.width, self.height = 640, 480
        self.buttons = ("previous", "retry", "snapshot", "next", "toggle", "restart", "quit")
        if backend == "maix":
            from maix import app, display, image, touchscreen
            self.app, self.image = app, image
            self.display = display.Display()
            self.width, self.height = self.display.width(), self.display.height()
            self.touch = touchscreen.TouchScreen()
        elif backend == "desktop":
            cv2.namedWindow("Transport Vision", cv2.WINDOW_AUTOSIZE)
            cv2.setMouseCallback("Transport Vision", self._mouse)

    def _mouse(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONUP:
            self._click(x, y)

    def _click(self, x, y):
        if self.height - 44 <= y < self.height and 0 <= x < self.width:
            index = min(len(self.buttons) - 1, x * len(self.buttons) // self.width)
            self.pending.append(self.buttons[index])

    def poll(self):
        if self.backend == "maix":
            if self.app.need_exit():
                self.pending.append("quit")
            x, y, pressed = self.touch.read()
            if self.was_pressed and not pressed:
                self._click(*self.last_touch)
            if pressed:
                self.last_touch = (x, y)
            self.was_pressed = bool(pressed)
        elif self.backend == "desktop":
            key = cv2.waitKey(1) & 0xFF
            action = {
                ord("n"): "next", ord("p"): "previous", ord("r"): "retry",
                ord("s"): "snapshot", ord("m"): "toggle", ord("c"): "restart",
                ord("q"): "quit", 27: "quit",
            }.get(key)
            if action:
                self.pending.append(action)
        commands, self.pending = self.pending, []
        return commands

    def render(self, frame, event, label, notice=""):
        """分离绘制和设备显示，便于在电脑上检查真机界面布局。"""
        width, height = self.width, self.height
        canvas = np.full((height, width, 3), (24, 27, 28), dtype=np.uint8)
        task = event.get("task")
        groups = task.split("+") if task else ["---"] * 4
        # 任务码始终占据顶部固定区域，不被步骤提示或检测画面覆盖。
        for row, text in enumerate(("+".join(groups[:2]), "+".join(groups[2:]))):
            size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.6, 2)[0]
            cv2.putText(canvas, text, ((width-size[0])//2, 40 + row*45),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.6, (100, 240, 170), 2, cv2.LINE_AA)
        cv2.putText(canvas, f'{event["step"]:02d}/12  {label}', (12, 110),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (245, 245, 245), 1, cv2.LINE_AA)
        view_top, view_bottom = 120, height - 86
        if frame is not None and view_bottom > view_top:
            view = frame.copy()
            data = event.get("data", {})
            for center in data.get("centers_px", []):
                cv2.circle(view, tuple(int(v) for v in center), 8, (0, 255, 0), 2)
            center = data.get("center_px")
            if center:
                cv2.drawMarker(view, tuple(int(v) for v in center), (0, 220, 255),
                               cv2.MARKER_CROSS, 28, 2)
            scale = min(width/view.shape[1], (view_bottom-view_top)/view.shape[0])
            resized = cv2.resize(view, (int(view.shape[1]*scale), int(view.shape[0]*scale)))
            x, y = (width-resized.shape[1])//2, view_top+(view_bottom-view_top-resized.shape[0])//2
            canvas[y:y+resized.shape[0], x:x+resized.shape[1]] = resized
        state = notice or event["state"]
        while state and cv2.getTextSize(state, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0][0] > width-24:
            state = state[:-1]
        color = (100, 240, 170) if event.get("ready") else (100, 190, 255)
        cv2.putText(canvas, state[:65], (12, height-61),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
        labels = ("<", "Retry", "Save", ">", "R/S", "Clear", "X")
        for index, text in enumerate(labels):
            x0, x1 = index*width//7, (index+1)*width//7
            cv2.rectangle(canvas, (x0, height-44), (x1-1, height-1), (65, 70, 70), 1)
            text_width = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1)[0][0]
            cv2.putText(canvas, text, (x0+(x1-x0-text_width)//2, height-17),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.48, (240, 240, 240), 1, cv2.LINE_AA)
        return canvas

    def show(self, frame, event, label, notice=""):
        if self.backend == "none":
            return
        canvas = self.render(frame, event, label, notice)
        if self.backend == "maix":
            self.display.show(self.image.cv2image(canvas, bgr=True))
        else:
            cv2.imshow("Transport Vision", canvas)

    def close(self):
        if self.backend == "desktop":
            cv2.destroyAllWindows()
