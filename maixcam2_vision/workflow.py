"""按真实比赛顺序划分步骤；只管理视觉状态，不控制电机或机械臂。"""

from dataclasses import dataclass
from .task import Task


@dataclass(frozen=True)
class Stage:
    number: int
    name: str
    label: str
    detector: str
    batch: int
    area: str = ""


# 粗加工放下后还需要取回，因此把放置与取回分成独立步骤。
STAGES = (
    Stage(1, "接收外部任务并显示", "TASK INPUT", "task", 0),
    Stage(2, "第一批：转盘对齐", "B1 TURNTABLE", "turntable", 1),
    Stage(3, "第一批：原料颜色与停稳识别", "B1 MATERIAL", "material", 1),
    Stage(4, "第一批：粗加工区放置对齐", "B1 ROUGH PLACE", "rings", 1, "rough"),
    Stage(5, "第一批：粗加工区取回对齐", "B1 ROUGH PICK", "stacking", 1, "rough"),
    Stage(6, "第一批：暂存区放置对齐", "B1 STORAGE", "rings", 1, "storage"),
    Stage(7, "第二批：转盘对齐", "B2 TURNTABLE", "turntable", 2),
    Stage(8, "第二批：原料颜色与停稳识别", "B2 MATERIAL", "material", 2),
    Stage(9, "第二批：粗加工区放置对齐", "B2 ROUGH PLACE", "rings", 2, "rough"),
    Stage(10, "第二批：粗加工区取回对齐", "B2 ROUGH PICK", "stacking", 2, "rough"),
    Stage(11, "第二批：暂存区同色码垛对齐", "B2 STACKING", "stacking", 2, "storage"),
    Stage(12, "返场阶段：保留任务显示", "RETURN", "idle", 0),
)


class Workflow:
    def __init__(self, step=1, task=None):
        self.task = Task.parse(task) if task else None
        self.step = 1
        self.generation = 0
        self.mode_override = None
        self.select(step)

    @property
    def stage(self):
        return STAGES[self.step - 1]

    @property
    def mode(self):
        return self.mode_override or self.stage.detector

    def select(self, step):
        # 步骤切换必须清除检测器历史；generation 由视觉引擎检测。
        if type(step) is not int or not 1 <= step <= len(STAGES):
            raise ValueError("步骤编号应为 1~12")
        if step != 1 and self.task is None:
            raise ValueError("请先接收外部任务，或用 --task 载入调试任务")
        self.step = step
        self.mode_override = None
        self.generation += 1

    def set_task(self, text):
        task = Task.parse(text)
        if self.task is not None and task != self.task:
            raise ValueError("更换任务前请 restart，避免混用两场任务")
        if task != self.task:
            self.task = task
            self.generation += 1

    def retry(self):
        # 重试只清本步骤的观测与超时状态，不推进比赛步骤。
        self.generation += 1

    def restart(self):
        self.task = None
        self.select(1)

    def set_mode(self, mode):
        if self.stage.detector not in ("rings", "stacking") or mode not in ("rings", "stacking"):
            raise ValueError("只有工位步骤可切换 rings / stacking")
        self.mode_override = mode
        self.generation += 1

    def describe(self):
        plan = self.task.plan(self.stage.batch) if self.task and self.stage.batch else []
        return {
            "step": self.step, "stage": self.stage.name, "mode": self.mode,
            "batch": self.stage.batch, "area": self.stage.area,
            "task": self.task.text if self.task else None, "plan": plan,
        }
