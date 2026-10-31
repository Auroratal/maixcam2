# 来源与改动

参考项目：创源启明工训赛视觉开源项目。

- 上游：https://gitee.com/linsen06/cyqm_vision_gongxun
- 参考提交：`ccb55c4939b75e0f658300c9201f09ef86e4e00d`
- 本工作区原始副本：`E:\codex\1\references\cyqm_vision_gongxun`

`detectors/turntable_detector.py`、`turntable_material_seed.py`、`material_pickup_detector.py`、`ring_station_detector.py`、`stacked_ring_detector.py` 来自该提交 `code/` 中的对应算法，并作了本工程适配：包内导入、统一颜色处理、移除主控纠偏输出、调整输入限制与提示等。配置中的搜索参数也部分继承自上游，仅作为待重新标定的初值。

新增任务解析、按赛程排列的调度、相机扫码、MaixCAM2 图像入口、独立预览、可选 JSON 行协议、两个工位的独立标定、过期/断线处理、离线运行与测试。

所读上游副本未见独立 LICENSE 文件，不能据此宣称上游采用 MIT、Apache 或其他许可；保留本来源说明，后续分发应确认作者授权与仓库实际许可。

官方 API 参考，核对日期 2026-10-31：

- 相机：https://wiki.sipeed.com/maixpy/doc/zh/vision/camera.html
- OpenCV 转换：https://wiki.sipeed.com/maixpy/doc/zh/vision/opencv.html
- 二维码：https://wiki.sipeed.com/maixpy/doc/zh/vision/qrcode.html
- 触摸：https://wiki.sipeed.com/maixpy/doc/zh/gui/touchscreen.html
- UART：https://wiki.sipeed.com/maixpy/doc/zh/peripheral/uart.html
- UART API：https://wiki.sipeed.com/maixpy/api/maix/peripheral/uart.html
- 应用清单：https://wiki.sipeed.com/maixcdk/doc/zh/convention/app.html
