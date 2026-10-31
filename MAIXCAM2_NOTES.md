# MaixCAM2 开发学习笔记

查阅日期：2026-10-11。来源为 Sipeed 官方文档；文末列出对应入口。
本次完成文档学习，尚未连接用户设备或进行上板验证。

## 用户设备信息

| 项目 | 当前信息 |
| --- | --- |
| 设备 | 用户已购买 MaixCAM2 |
| 内存版本 | 待确认，不能默认是 4GB |
| eMMC 配置 | 待确认 |
| 摄像头型号 | 待确认 |
| 系统、运行库、MaixPy 版本 | 待读取设备信息 |
| 连接方式、设备 IP | 待确认 |
| 项目目标 | 工创赛智能搬运赛项；已阅读用户提供的 2027 年赛题解析 |

已学习的视觉参考工程：`references/cyqm_vision_gongxun`。源码解析、串口协议、合成图验证及 MaixCAM2 适配事项见 `CYQM_VISION_STUDY.md`。

2026-10-31：已新增 `maixcam2_vision/`，入口 `main.py`。默认独立运行，使用 Maix 相机与扫码接口，按比赛顺序分为 12 步；没有原 F407 主控通信依赖，另提供可选 JSON 行协议。使用与标定顺序见 `maixcam2_vision/README.md`。电脑测试已覆盖流程和合成图算法，尚未上板验证。

## 1. 平台与硬件

MaixCAM2 使用 AX630C，主核是双核 Cortex-A53，运行 Linux；开发以 MaixPy v4 的 Python API 为主，也有 MaixCDK C/C++ SDK。[S1][S2]

| 项目 | 官方参数 |
| --- | --- |
| NPU | 3.2 TOPS INT8 / 12.8 TOPS INT4 |
| 内存 | 1GB / 4GB LPDDR4 配置 |
| 屏幕 | 常见整机配 640×480 电容触摸屏 |
| 摄像头 | 支持的模组包括 OS04D10、OS04A10、SC850SL |
| 通信与外设 | WiFi、USB 网络、UART、I2C、SPI、PWM、GPIO 等 |

产品页的 YOLO11n 113 FPS 指 640×640 下单独运行模型的指标；不能据此保证摄像头采集、后处理、显示、通信整个程序达到相同帧率。[S2]

## 2. 开机与连接

带 eMMC 的配置通常从 eMMC 启动；无 eMMC 配置需要有系统的 TF 卡。[S3]

初次操作顺序：

1. Type-C 供电，进入应用菜单。
2. 在设置中连接 WiFi，确认取得 IP 且能访问互联网。
3. 安装或更新运行库。
4. 电脑与设备建立 WiFi 同网段连接，或使用 USB 虚拟网卡。
5. MaixVision 搜索并连接设备；搜索不到时手动输入设备 IP。[S3]

USB 开发连接使用网络接口，不能把它当作普通 USB 转串口。Windows 需正确识别 RNDIS 或 NCM；设备实际地址以设备信息为准。[S3][S12]

MaixCAM2 专属快速开始给出的默认终端账号为 `root`，密码为 `sipeed`。[S3]

## 3. 编辑、调试与文件路径

MaixVision 可编辑代码、运行例程、显示日志和图像、传输文件、安装及打包应用。多文件工程入口为 `main.py`，需要运行整个项目来传输其他模块及资源。[S4]

电脑编辑的代码最终在设备上运行。程序引用的 `/root/models/...` 属于设备文件系统，Windows 的 `E:\...` 路径不能直接在设备程序中使用。[S4]

电脑安装 MaixPy 可以用于编辑器补全；这不代表电脑具备设备摄像头、屏幕和 NPU 的运行环境。[S4]

## 4. 摄像头与显示

常用调用关系：

- `camera.Camera(width, height, ...)` 配置取图尺寸和格式。
- `cam.read()` 得到图像。
- `display.Display()` 创建显示对象，`disp.show(img)` 显示图像。
- 主循环检查 `app.need_exit()`，支持正常退出。[S5][S6]

AI 场景优先按模型需求设置摄像头尺寸和像素格式。分辨率与帧率上限取决于摄像头型号，不能把一代的配置直接用于二代。[S5]

改变宽高比可能改变裁剪范围和视野。大分辨率会增加内存和处理开销，在线预览也有传输成本；初始化后可跳过若干帧等待图像稳定。[S5]

手动设置曝光或增益会影响自动曝光模式。做颜色判断时要考虑自动白平衡引起的颜色变化。[S5]

## 5. YOLO 检测

| API | 文档注明的最低 MaixPy 版本 |
| --- | --- |
| `nn.YOLOv8` | 4.3.0 |
| `nn.YOLO11` | 4.7.0 |
| `nn.YOLO26` | 4.12.5 |

这些是功能的版本要求，不是对当前最新发行版本的声明。[S7]

通过 `.mud` 路径创建对应检测器；使用检测器的 `input_width()`、`input_height()`、`input_format()` 配置摄像头。`detect()` 提供置信度与 IoU 阈值，检测结果包含类别、置信度和矩形坐标。[S7]

输入图尺寸不一致时，文档说明检测器会保持比例缩放、填边，并把坐标映射回原图；实际项目仍需验证坐标与显示、控制坐标系的关系。[S7]

`dual_buff=True` 可提高吞吐量，但结果对应上一次输入，且额外占用内存。需要图像与结果严格对应、测量延迟或控制执行器时，应明确选择是否关闭双缓冲。[S8]

## 6. 模型包与上传

| 文件 | 含义 |
| --- | --- |
| `*.mud` | 文本描述文件，记录实际模型路径、模型类型、标签等 |
| `*_npu.axmodel` | 完整 NPU 配置的实际模型 |
| `*_vnpu.axmodel` | 为 AI-ISP 预留算力的实际模型变体 |

模型包可能只有一个 `.axmodel`，也可能有两个；按实际包和 `.mud` 内容处理。全部配套文件一起上传，通常放到设备 `/root/models`，代码加载 `.mud`。[S9][S11]

一代的 `.cvimodel` 与二代的 `.axmodel` 属于不同平台格式。重命名配套模型文件时，要同步修改 `.mud` 中的引用。[S9][S11]

## 7. 自定义模型转换

普通 YOLO 目标检测优先参考官方网页转换流程。当前该页列出 YOLO26、YOLO11、YOLOv8、YOLOv5u；旧 YOLOv5、分类、姿态、分割和旋转框不属于该网页流程支持范围。[S10]

网页接收 ONNX。该页指定导出工具 `ultralytics==8.4.104`，使用固定输入尺寸、`opset=17`、`dynamic=False`。尺寸参数顺序是高、宽；这是该流程的兼容配置，后续实际转换时需再核对文档。[S10]

网页量化校准使用 20–100 张实际场景图片，ZIP 上限 100MB；标签顺序必须和训练一致。[S10]

手动转换使用 Pulsar2，MaixCAM2 对应的目标参数是 `AX620E`。流程为固定尺寸 ONNX → 核对并裁剪输出节点 → 场景图片校准 → 生成 `.axmodel` → 编写 `.mud`。[S11]

`NPU2` 对应完整 NPU 配置；`NPU1` 对应为 AI-ISP 预留算力的配置。节点名称、输出布局、标签与预处理参数必须针对真实模型核对。[S11]

## 8. UART 与引脚

先核对 MaixCAM2 引脚图，再用 `pinmap.set_pin_function()` 配置复用功能。[S12][S13]

| 官方例程中的选择 | 对应关系 |
| --- | --- |
| UART4 | A21 → TX，A22 → RX，设备 `/dev/ttyS4` |
| UART2 | B0 → TX，B1 → RX，设备 `/dev/ttyS2` |

UART0 用于系统终端和日志。与控制器连接时 TX/RX 交叉、GND 共地；常用初始参数为 115200、8N1。USB 连接电脑的网络功能与这些硬件 UART 是不同通道。[S12]

MaixCAM2 IO 为 3.3V，不能直接接 5V 信号。B25 连照明 LED，A6 连系统状态 LED；选引脚时要检查现有用途。[S13]

## 9. 独立应用与开机启动

在线运行用于开发调试；要让设备独立启动项目，需要通过 MaixVision 安装成应用。手工打包工程使用 `main.py`、`app.yaml` 等资源，官方提供 `maixtool release` 流程。[S3][S14]

应用安装后，在设备设置的开机自启选项中选择该应用。后续项目交付应验证启动、退出、资源路径及断开电脑后的运行表现。[S15]

## 10. 内存与本地大模型

Linux 可用内存与摄像头/NPU 使用的 CMM 内存分开。`free` 显示的数值较小，不等于物理内存少装。可用 `maix.sys.memory_info()` 查看硬件、用户空间和 CMM 信息。[S16]

内存页默认值表列出：4GiB 配置为约 1GiB Linux + 3GiB CMM，1GiB 配置为各 512MiB；同页其他段落含不同示例，实际分配需读取设备。[S16]

MaixCAM2 可通过 `/boot/configs` 的 `maix_memory_cmm` 调整预留 MiB，`-1` 使用默认分配，修改后需重启。先查内存需求，再考虑修改。[S16][S19]

官方列有离线语言、视觉语言、语音识别和语音合成模型。支持表将部分 SenseVoice、Whisper、MeloTTS、SmolVLM 配置标为 1G，将 Qwen、InternVL 等配置标为 4G；不能假设所有模型适用于用户的内存版本。[S17]

## 11. 排查顺序与文档差异

- 搜索不到设备：确认启动状态、IP、同网段连接和 USB 网络驱动；再尝试手动 IP。[S18]
- 预览卡顿：比较设备屏幕与电脑预览，检查网络和 USB 传输，并测量各处理阶段耗时。[S18]
- 模型加载失败：检查板型、全部配套文件、设备路径和 `.mud` 引用；怀疑传输损坏时比较文件哈希。[S9][S18]
- 系统镜像、运行库、MaixPy 是不同层次，需核对版本兼容；重新烧录系统前备份设备内的数据。[S18]

通用 MaixVision 页面仍有账号密码均为 `root` 的说明；MaixCAM2 专属快速开始写的是 `root / sipeed`。本设备优先依据专属页面，再根据实际镜像核实。[S3][S4]

硬件参数页概述板载 eMMC，专属快速开始另外区分无 eMMC 配置。用户设备的启动介质应以订单与实机为准。[S2][S3]

本次重点学习上手、取图显示、YOLO、模型转换、串口、部署和内存。OCR、人脸识别、触摸界面、网络串流等已找到官方入口，具体实现时再读对应 API、例程和兼容说明。[S1]

## 12. 后续实践起点

建议首先完成三个可观察的结果：摄像头画面正常显示；现成 YOLO 模型正确框出目标；安装成应用后可从设备菜单独立运行。[S3][S7][S14]

再根据项目目标增加自定义训练、串口控制、触摸交互或本地语音功能。实测记录需包含设备配置、版本、模型输入尺寸、各阶段耗时及整段循环帧率。

## 官方资料索引

| 编号 | 页面 | 地址 |
| --- | --- | --- |
| S1 | MaixPy 总入口 | `https://wiki.sipeed.com/maixpy/doc/zh/index.html` |
| S2 | MaixCAM2 硬件 | `https://wiki.sipeed.com/hardware/zh/maixcam/maixcam2.html` |
| S3 | MaixCAM2 快速开始 | `https://wiki.sipeed.com/maixpy/doc/zh/README_MaixCAM2.html` |
| S4 | MaixVision | `https://wiki.sipeed.com/maixpy/doc/zh/basic/maixvision.html` |
| S5 | 摄像头 | `https://wiki.sipeed.com/maixpy/doc/zh/vision/camera.html` |
| S6 | 屏幕 | `https://wiki.sipeed.com/maixpy/doc/zh/vision/display.html` |
| S7 | YOLO | `https://wiki.sipeed.com/maixpy/doc/zh/vision/yolov5.html` |
| S8 | 双缓冲 | `https://wiki.sipeed.com/maixpy/doc/zh/vision/dual_buff.html` |
| S9 | 模型部署 | `https://wiki.sipeed.com/maixpy/doc/zh/ai_model_converter/ai_model_deploy.html` |
| S10 | 网页转换 | `https://wiki.sipeed.com/maixpy/doc/zh/ai_model_converter/online_converter.html` |
| S11 | MaixCAM2 手动转换 | `https://wiki.sipeed.com/maixpy/doc/zh/ai_model_converter/maixcam2.html` |
| S12 | UART | `https://wiki.sipeed.com/maixpy/doc/zh/peripheral/uart.html` |
| S13 | 引脚映射 | `https://wiki.sipeed.com/maixpy/doc/zh/peripheral/pinmap.html` |
| S14 | 应用开发 | `https://wiki.sipeed.com/maixpy/doc/zh/basic/app.html` |
| S15 | 开机自启 | `https://wiki.sipeed.com/maixpy/doc/zh/basic/auto_start.html` |
| S16 | 内存 | `https://wiki.sipeed.com/maixpy/doc/zh/pro/memory.html` |
| S17 | 大模型 | `https://wiki.sipeed.com/maixpy/doc/zh/mllm/basic.html` |
| S18 | MaixPy FAQ | `https://wiki.sipeed.com/maixpy/doc/zh/faq.html` |
| S19 | MaixCAM2 FAQ | `https://wiki.sipeed.com/hardware/zh/maixcam/maixcam2_faq.html` |
