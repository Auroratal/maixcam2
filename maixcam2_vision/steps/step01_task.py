"""第一步：接收外部设备给出的任务码，具体通信方式留待接入。"""


def read_external_task():
    """以后只需修改这个函数，接入最终选定的传输方式和报文格式。

    返回约定：
    - 已收到完整任务：返回字符串，例如 "452+321+254+312"。
    - 没收到或报文尚未收全：返回 None，等待下一轮读取。

    请在这里完成原始报文的拆包、解码和任务字段提取；不要把原始
    bytes、半包或字典直接返回。校验与任务推导继续由现有代码负责。
    此函数应快速返回，避免阻塞屏幕和其他命令处理。
    """
    # TODO：确定通信方式后，把下面这一行替换为实际接收代码。
    # 目前不初始化任何通信硬件，也不生成默认任务。
    return None


def process(workflow):
    """保留统一的任务入口，后续颜色、环号和同色码垛推导无需修改。"""
    text = read_external_task()
    if text is not None:
        workflow.set_task(text)
    received = workflow.task is not None
    return received, "外部任务已接收并校验" if received else "等待外部设备传入任务码"
