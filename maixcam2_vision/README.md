# MaixCAM2 智能搬运视觉

这是基于创源启明开源视觉项目整理的 MaixCAM2 版本，按智能搬运比赛顺序组织，附中文注释。默认独立运行，串口关闭，没有 STM32/F407 固件、电机控制、机械臂动作、底盘纠偏矩阵或原工程二进制通信依赖。

运行入口是 `main.py`，先看 `workflow.py` 的比赛步骤，再按下表阅读 `steps/`。底层检测算法在 `detectors/`，参数在 `config/`。原参考仓库保留在工程外，没有修改。

## 1. 比赛步骤与代码

| 步骤 | 场上阶段 | 视觉代码 | 主要结果 |
| --- | --- | --- | --- |
| 01 | 扫码、持续显示任务 | `steps/step01_qrcode.py` | 连续确认后的四组任务、两批计划 |
| 02 | 第一批原料转盘对齐 | `steps/step02_turntable.py` | 外圆中心、半径、相对参考圆心的像素误差 |
| 03 | 第一批原料抓取 | `steps/step03_material.py` | 左/右/下的颜色、空位、转动后停稳状态 |
| 04 | 第一批粗加工区放置 | `steps/step04_station.py` | 三环位置、工位角度、实际环号映射 |
| 05 | 第一批粗加工区取回 | `steps/step05_stacking.py` | 遮挡时用中环和基准线定位 |
| 06 | 第一批暂存区放置 | `steps/step04_station.py` | 暂存区独立的三环参考 |
| 07 | 第二批原料转盘对齐 | `steps/step02_turntable.py` | 重新积累定位证据 |
| 08 | 第二批原料抓取 | `steps/step03_material.py` | 重新观察本批转动与停稳 |
| 09 | 第二批粗加工区放置 | `steps/step04_station.py` | 使用第四组给出的粗加工位置 |
| 10 | 第二批粗加工区取回 | `steps/step05_stacking.py` | 遮挡工位定位 |
| 11 | 第二批暂存区同色码垛 | `steps/step05_stacking.py` | 工位定位、同色下层所在环号 |
| 12 | 返场 | `workflow.py` | 保留任务显示，无运动指令 |

步骤 05、10 默认用遮挡模式；如果三个环仍完整可见，可以切成 `rings`。两个区域分别标定，相机各观察姿态也要可重复。

**视觉稳定不会自动进入下一步。** 调试时手动切换；以后由你们自己的控制系统，在确认导航、抓放等动作完成后切换。一次原料抓取步骤可以处理三件物料；机械臂遮挡之后可执行 `retry` 重新建立观测，随后仍需看到转动再停稳。

任务例子：`452+321+254+312`。第一批绿、黑、黄放到 3、2、1；第二批黄、黑、绿在粗加工区放到 3、1、2，在暂存区要叠到第一批同色物料上，即 1、2、3。第四组不能直接用作第二批暂存位置。

## 2. 先独立运行

在 MaixVision 打开整个 `maixcam2_vision` 文件夹，运行整个项目，入口为 `main.py`，让 `steps/`、`detectors/`、`config/` 一起传入设备。使用支持 MaixCAM2 的 MaixPy 系统及系统自带的 OpenCV、NumPy；无需在设备上安装桌面 OpenCV。

也可在设备项目目录运行：

```bash
python main.py
```

默认从步骤 01 开始，使用设备相机、屏幕、触摸。未标定前允许看检测效果，但相应步骤不会输出 `ready=true`。首次扫码需要同一合法任务连续确认三帧；只识别到其他普通二维码不会锁定任务。

电脑查看步骤或调试普通摄像头：

```bash
python -m pip install -r requirements.txt
python main.py --list-steps
python main.py --backend desktop --device 0 --step 4 --task "452+321+254+312"
```

预览按钮依次为：上一阶段、重试、保存截图、下一阶段、三环/遮挡切换、清任务重新开始、退出。电脑快捷键依次是 `p / r / s / n / m / c / q`。触摸仅供赛前调试，正式比赛由你们的一键启动与自动控制逻辑驱动。

任务始终显示在顶部。屏幕上的任务字高能否达到讲义的 **12mm** 要在实物测量；仅有像素字号不能证明合规。当前界面显示步骤与视觉状态，尚未记录真实抓取、放置成功情况。

## 3. 按顺序标定

先固定相机安装、各观察姿态、焦距、照明以及曝光/白平衡条件，再做下面的标定。默认 1280×720；修改分辨率后须重新标定，各检测器的像素搜索范围也需要调整。

预览中的 `Save` 保存不含叠字的 PNG 及同名 JSON。把两者一起传回电脑，在相同配置下使用 `calibrate.py`；标定后的 `config/` 再同步到设备，并重新运行程序。ROI 坐标来自保存的 **原尺寸图片**，顺序是 `x y 宽 高`。

下面坐标和尺寸仅演示命令格式，必须替换为现场采样值；95、150、75 也要按正式靶纸和实物测量确认。

### 3.1 六色阈值

颜色编号：红 1、黄 2、蓝 3、绿 4、黑 5、浅蓝 6。在实际物料内部选一块纯色 ROI，逐色运行：

```bash
python calibrate.py colors --image captures/material.png --color 4 --roi 420 120 30 30
```

这个命令替换对应颜色的 HSV 范围，并记录已采样颜色。建议六色全部采样；当前任务的三种颜色未全部标定时，物料步骤不会 `ready`。黑色必须检查与背景的分离，蓝色与浅蓝色必须互相验证。多个阈值同时命中的像素会被剔除，以免一件物料被算成两件。

### 3.2 物料活动区和三个抓取区

在原料抓取姿态采图，框出活动区及三个互不重叠、完全包含于活动区的抓取区：

```bash
python calibrate.py regions --image captures/material.png --workspace 250 40 750 560 --left 350 80 220 180 --right 730 80 220 180 --down 540 350 220 180
```

初始静止不算本次停稳。算法必须先看见本周期运动，再观察连续低速、颜色位置稳定；抓取区内为空时颜色编号为 `0`。

### 3.3 转盘参考圆心

把机器人与相机放到实际需要的转盘对齐位置，再采图：

```bash
python calibrate.py turntable --image captures/turntable.png
```

保存后，观测圆心减去参考圆心得到 `error_px`。找不到外圆时，先修改 `turntable_detector.json` 的最小/最大搜索半径；原作者的像素半径只是初值。三物料辅助定位默认关闭，不使用作者的参考圆心作为本机标定。

### 3.4 两个工位分别标定

在你们希望作为放置零点的位置采集三个无遮挡靶环。输入实测中心距、外圈直径，以及图片中从左到右的真实环号：

```bash
python calibrate.py station --area rough --image captures/rough.png --spacing-mm 150 --outer-mm 95 --ring-order 1 2 3
python calibrate.py station --area storage --image captures/storage.png --spacing-mm 150 --outer-mm 95 --ring-order 1 2 3
```

`rough` 是粗加工区，`storage` 是暂存区。程序不识别环内印刷数字，环号通过这里确认。几何上的中环不一定就是数字 2；如果观察方向改变，请按实际画面修改排列。

工具用已知尺寸建立局部像素→毫米尺度，供视觉误差验收使用；没有到电机或车体坐标的转换。明显透视、相机高度或姿态变化时，局部模型可能失效，需要重新标定。

### 3.5 遮挡模式的外圈与基准线

先完成对应区域的 `station` 标定。保存中环外圈、上下两条基准线清楚可见的图片，输入线到中环中心的垂直物理距离：

```bash
python calibrate.py stacking --area rough --image captures/rough.png --outer-mm 95 --line-offset-mm 75
python calibrate.py stacking --area storage --image captures/storage.png --outer-mm 95 --line-offset-mm 75
```

不能自动选出唯一中环时，可加 `--middle 640 360` 指定原图中环附近的点。标定必须看到上下两条有效线；运行时允许其中一条短时被遮挡。中环外圈被完全挡住时不能保证定位，程序会返回未找到。

移动相机支架、改变观察姿态或现场布置后，主动清除旧标定并重做：

```bash
python calibrate.py invalidate
```

分辨率、是否畸变矫正或内参指纹改变时，下一次标定会自动撤销其他步骤的旧标定。系统无法仅凭分辨率发现相机支架移动，因此仍需主动失效处理。

默认 `camera.undistort=false`，不加载原作者的相机内参。若以后启用，需自行准备当前镜头、分辨率的 OpenCV `camera.yaml`，包含 `image_width`、`image_height`、`camera_matrix`、`distortion_coefficients`、`new_camera_matrix`，然后重标全部 ROI 与工位参考。

## 4. 离线检查与测试

```bash
python main.py --backend image --image captures/rough.png --step 4 --task "452+321+254+312" --frames 3 --no-display
```

输出为逐行 JSON。带截图元数据时先检查图像几何，避免重复畸变校正；没有元数据的外部图片按原始相机图处理。离线结果带 `offline=true`，只能验证算法，不能证明真实运动或车辆动作已经完成。

在 **本文件夹的上一级目录** 运行测试：

```bash
python -m unittest discover -s maixcam2_vision/tests -v
```

测试覆盖任务推导、扫码一致性、状态切换、协议拆包、运动停稳、三环和遮挡检测、标定失效及断线超时。电脑若安装 `opencv-python-headless`，可以运行离线模式与测试，无法打开电脑预览窗口。

## 5. 接入你们自己的主控

目前不用接任何主控即可运行。需要联动时，在 `config/vision.json` 中把 `uart.enabled` 改为 `true`，依据实际接线设置设备节点和引脚。默认配置对应 MaixCAM2 的 UART4：A21 TX、A22 RX、115200；TX/RX 交叉、共地，电平以双方硬件规格为准。

无论使用哪种单片机，只要实现 [PROTOCOL.md](PROTOCOL.md) 的 UTF-8 JSON 行协议，就能选择步骤、读任务和坐标。没有提供某个芯片 SDK 的固件。

`detected` 表示找到目标，`stable` 表示连续观测满足检测器条件，`ready` 表示当前视觉数据满足本步骤的标定与新鲜度要求；`within_tolerance` 才是相对标定零点的视觉误差验收。以上状态都不代表机械臂已经抓住、放稳或车辆已经完成动作。

一直得不到可用观测时默认 10 秒进入超时，清空坐标，需 `retry` 或换步骤；相机断开也会清除历史。它只处理视觉观测，不能代替赛规中“15 秒未移动”的整车判定。

## 6. 当前边界

步骤 11 实现的是遮挡工位定位及同色目标环号推导。`side_centers_reconstructed=true` 表示两侧圆心来自几何重建，`material_alignment_verified=false` 表示尚未核验第一批物料的实际偏移、顶部接触面和高度。因此不能把工位对齐当作真实码垛成功；这部分要根据你们实物和机械臂视角继续补充。

工程尚未在你们的 MaixCAM2 上运行。相机曝光、板端耗时、实际分辨率、机械臂遮挡、串口收发和放置精度仍需上板验证；电脑合成图通过不等于实物精度达标。默认参数未宣称可直接用于比赛。

来源和改动见 [ATTRIBUTION.md](ATTRIBUTION.md)。比赛步骤依据用户提供的 `工创.pdf` 学习笔记，最终比赛要求以你们当届正式规则为准。
