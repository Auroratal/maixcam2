"""第一步：相机扫码；同一码连续出现才锁定，不自动跳到下一步骤。"""

from ..task import Task


class QRStep:
    def __init__(self, confirmations=3):
        self.confirmations = confirmations
        self.reset()

    def reset(self):
        self.candidate = None
        self.count = 0

    def process(self, payloads, locked_task=None):
        valid = {}
        for text in payloads:
            try:
                task = Task.parse(text)
                valid[task.text] = task
            except ValueError:
                continue
        # 同时看到两个不同的合法任务，不能任意选择其中一个。
        if len(valid) != 1:
            self.reset()
            return None, "二维码未找到" if not valid else "画面中存在多个不同任务码"
        task = next(iter(valid.values()))
        if locked_task and task != locked_task:
            self.reset()
            return None, "任务已锁定，换场前请重置"
        self.count = self.count + 1 if task.text == self.candidate else 1
        self.candidate = task.text
        if self.count >= self.confirmations:
            return task, "任务码已连续确认"
        return None, f"扫码确认 {self.count}/{self.confirmations}"
