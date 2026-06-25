"""
VT CLI 包初始化

本包包含 Vibe Tracing 的所有 CLI 命令实现。
调度逻辑（argparse + 命令路由）位于 cli/main.py。

子命令分布：
  - cli/main.py     → main()         CLI 入口与调度
  - cli/init.py     → run_init()     项目初始化
  - cli/finalize.py → run_finalize() 锁定设计基线
  - cli/accept.py   → run_accept()   人类接受手动规则
  - cli/doctor.py   → run_doctor()   治理数据健康扫描
  - cli/analyze/    → run_analyze()  核心分析流水线
"""

import subprocess  # re-exported so test mocks on vibe_tracing.cli.subprocess work

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
from vibe_tracing.cli.main import main
from vibe_tracing.cli.init import run_init
from vibe_tracing.cli.finalize import run_finalize
from vibe_tracing.cli.analyze import run_analyze
from vibe_tracing.cli.doctor import run_doctor
from vibe_tracing.cli.accept import run_accept
from vibe_tracing.cli.analyze.exceptions import _GateBlocked
