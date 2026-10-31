"""校验外部输入的任务码，推导两批物料的搬运计划。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    text: str
    first_colors: tuple
    first_rings: tuple
    second_colors: tuple
    second_rings: tuple

    @classmethod
    def parse(cls, text):
        # 只接受比赛规定的 ASCII 数字与加号，不把错误报文当成任务。
        if not isinstance(text, str) or len(text) != 15:
            raise ValueError("任务码应为四组三位数，例如 452+321+254+312")
        groups = text.split("+")
        if len(groups) != 4 or any(len(group) != 3 for group in groups):
            raise ValueError("任务码分组格式错误")
        for group in (groups[0], groups[2]):
            if any(c not in "123456" for c in group) or len(set(group)) != 3:
                raise ValueError("每批应包含三种不同颜色，编号为 1~6")
        if set(groups[0]) != set(groups[2]):
            raise ValueError("两批颜色集合必须一致")
        if any(set(groups[index]) != set("123") for index in (1, 3)):
            raise ValueError("放置位置应为 1、2、3 的不重复排列")
        return cls(text, *(tuple(int(c) for c in group) for group in groups))

    def plan(self, batch):
        """第二批暂存目标按第一批同色位置计算，不能直接使用第四组。"""
        if batch not in (1, 2):
            raise ValueError("批次只能是 1 或 2")
        storage = dict(zip(self.first_colors, self.first_rings))
        colors = self.first_colors if batch == 1 else self.second_colors
        rough = self.first_rings if batch == 1 else self.second_rings
        return [
            {"order": i + 1, "color": color, "rough_ring": rough[i],
             "storage_ring": storage[color], "layer": batch}
            for i, color in enumerate(colors)
        ]
