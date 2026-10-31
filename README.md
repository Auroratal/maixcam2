# maixcam2

MaixCAM2 工创赛智能搬运视觉工程，按比赛顺序组织，附中文注释。

视觉工程位于 [`maixcam2_vision/`](maixcam2_vision/)，默认独立运行，不依赖 STM32/F407 主控。需要整车联动时，可由任意单片机实现可选的 JSON 行通信协议。

扫码由外部设备完成。任务传输方式尚未确定，接收适配入口保留在 [`steps/step01_task.py`](maixcam2_vision/steps/step01_task.py) 的 `read_external_task()`，以后修改这里即可；后续任务推导和视觉步骤继续沿用。

## 使用入口

- [运行、步骤顺序与标定说明](maixcam2_vision/README.md)
- [程序入口](maixcam2_vision/main.py)
- [按比赛顺序排列的 12 个步骤](maixcam2_vision/workflow.py)
- [标定工具](maixcam2_vision/calibrate.py)
- [通用通信协议](maixcam2_vision/PROTOCOL.md)
- [上游来源与改动](maixcam2_vision/ATTRIBUTION.md)

在 MaixVision 中打开整个 `maixcam2_vision` 文件夹，以 `main.py` 为入口运行项目；首次使用需按说明重新标定。

电脑端安装依赖、查看步骤及运行测试：

```bash
python -m pip install -r maixcam2_vision/requirements.txt
python maixcam2_vision/main.py --list-steps
python -m unittest discover -s maixcam2_vision/tests -v
```

40 项电脑测试已通过，尚未在用户的 MaixCAM2 上验证。码垛目前提供工位定位及同色目标推导，尚未核验下层物料的实际偏移与接触面。

## 学习笔记

- [MaixCAM2 开发笔记](MAIXCAM2_NOTES.md)
- [智能搬运规则解读](SMART_TRANSPORT_RULES.md)
- [比赛流程与视觉模块对应](SMART_TRANSPORT_VISION_FLOW.md)
- [创源启明开源工程分析](CYQM_VISION_STUDY.md)

比赛资料笔记与工程建议不替代当届正式规则。原始参考仓库、临时依赖和调试截图保留在本机，不纳入版本记录。
