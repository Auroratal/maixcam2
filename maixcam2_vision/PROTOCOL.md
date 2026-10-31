# 通用视觉通信协议 v1

本协议是保留的可选联动方案，尚未决定你们的实际任务传输方式。自定义接收入口是 `steps/step01_task.py` 的 `read_external_task()`，在那里把实际报文转换为完整任务字符串即可，不必采用本文 JSON 协议。

若选择本方案，任何单片机都可自行实现。默认 UART 关闭；相同回复也打印到程序标准输出。每条消息是一个 UTF-8 JSON 对象，末尾一个换行字节 `0x0A`。按字节收包，遇到换行才解析，不能假设一次读取就是完整消息。

## 控制系统发给视觉

```json
{"id":1,"command":"set_task","task":"452+321+254+312"}
{"id":2,"command":"set_step","step":4}
{"id":3,"command":"retry"}
{"id":4,"command":"set_mode","mode":"stacking"}
{"id":5,"command":"status"}
```

| command | 参数 | 含义 |
| --- | --- | --- |
| `set_task` | `task` 字符串 | 若采用本协议，由外部设备提供完整任务 |
| `set_step` | `step` 整数 1～12 | 选择比赛视觉步骤 |
| `next` | 无 | 下一步骤 |
| `previous` | 无 | 上一步骤 |
| `retry` | 无 | 清除当前观测历史和超时，保持任务、步骤 |
| `set_mode` | `mode` 为 `rings` 或 `stacking` | 仅工位步骤允许切换检测方法 |
| `restart` | 无 | 清任务、回到外部任务接收步骤，换场时使用 |
| `status` | 无 | 返回当前步骤和计划，不改变状态 |

超过 2048 字节、非对象、非法 UTF-8 或损坏的 JSON 行被丢弃，接着处理下一行。合法对象中的未知命令或无效参数会收到 `ok=false`。没有任务时无法切到步骤 02～12；任务一经接收就锁定，更换任务须先 `restart`。

`set_task` 和自定义接收函数使用同一个校验入口，不依赖图像或连续帧确认。一次完整有效输入即可锁定，同一任务可以重复发送；不会自动进入下一步。任务成功接收时输出 `mode=task`、`ready=true` 和 `data.task_received=true`。该结果只确认任务有效，不提供视觉坐标，`captured_ms/age_ms` 为 null。

## 视觉回复

每条合法命令返回一个 `type=ack` 的对象，包含同一个 `id`。成功时还包含步骤、任务和 `generation`；失败包含 `ok=false` 和 `detail`。命令 ACK 只表示视觉接受命令，不能作为坐标。

```json
{"version":1,"type":"ack","id":3,"ok":true,"generation":4,"step":4,"stage":"第一批：粗加工区放置对齐","mode":"rings","batch":1,"area":"rough","task":"452+321+254+312","plan":[]}
```

上例省略了计划内容。实际 `plan` 有三项，每项包括搬运顺序 `order`、颜色 `color`、粗加工环号 `rough_ring`、暂存环号 `storage_ring`、层数 `layer`。

观测消息 `type=result` 默认最多 5Hz，状态变化时立即输出。公共字段：

| 字段 | 含义 |
| --- | --- |
| `version / seq / generation` | 协议版本、当前进程递增消息序号、任务/步骤/重试的观测代数 |
| `step / mode / batch / area / task / plan` | 当前比赛上下文 |
| `state / detail` | `waiting_task`、`task_error`、`observing`、`ready`、`timeout`、`stale`、`camera_unavailable`、`error`、`return_stage` 及说明 |
| `detected / stable / ready` | 找到目标、观测稳定、视觉结果可用 |
| `captured_ms` | 设备单调时钟下的取图时间；无有效图像时为 null |
| `age_ms` | 生成消息时距离取图的耗时；不包括之后的排队和传输延迟 |
| `ttl_ms` | 默认 500ms，该结果从取图时起的最大有效期 |
| `data` | 当前步骤数据；断线、过期、超时、算法错误时不提供旧坐标 |
| `offline` | 仅离线模式出现且为 true，禁止作为现场反馈 |

设备与主控的单调时钟不一定同步，不能直接相减。主控侧的本地有效时间应小于 `ttl_ms - age_ms - 估计通信延迟`；重连或视觉重启后清除缓存，重新请求步骤，不能沿用此前 `seq`、`generation` 或坐标。

坐标均为进入算法的图像坐标：左上为原点，x 向右、y 向下，单位 px。角度单位为度，正方向随图像 y 向下的约定。像素误差是 **当前测量减去参考位置**，不直接等于电机行进方向或距离。

| mode | `data` 的主要字段 |
| --- | --- |
| `task` | `task_received`，确认任务位于公共 `task`；接收失败时该标记仅表示旧任务仍被保留，须同时检查 `state/ready` |
| `turntable` | `center_px`、`radius_px`、`confidence`、`error_px` |
| `material` | `motion_state`、`speed_px_s`、`slots`、`color_to_slot`、`task_colors_match` |
| `rings` | `centers_px`、`station_yaw_deg`、`numbering_confirmed`、`rings_by_id` |
| `stacking` | 同工位字段，另有 `side_centers_reconstructed`、`material_alignment_verified`、`reference_line_count` |

`slots` 的键为 `left/right/down`，值为颜色编号，0 为空。物料不在已标定抓取区内时，不可用的槽位映射不会变成可执行结果。工位标定确认后另输出 `center_errors_px`、`angle_error_deg`、`within_tolerance`；未标定时不能使用作者的示例零点。

控制系统至少检查消息类型、当前任务与步骤、`generation`、`seq`、`ready`、本地接收超时及离线标记，再使用坐标。`ready=true` 的观测会重复输出，不能每收到一帧就重复抓放；机械动作与执行去重由你们的控制系统负责。
