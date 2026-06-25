"""CLI 层共享异常定义。

独立模块以避免 pipeline.py ↔ reports.py/tools.py 的循环导入。
"""


class _GateBlocked(Exception):
    """Raised when an integrity gate blocks the analysis pipeline."""
    def __init__(self, exit_code: int = 1):
        self.exit_code = exit_code
