"""
VT CLI 调度模块（Dispatch Module）

本模块是 Vibe Tracing 的唯一入口，负责：
1. 定义命令行参数（argparse）
2. 将用户命令路由到对应的子命令处理函数
3. 初始化运维日志记录器（唯一的 init 调用点）
4. 全局异常捕获，将未处理异常记录到运维日志

入口函数：main() — 由 pyproject.toml 的 [project.scripts] 绑定到 vibe-tracing 命令。
子命令处理函数分布在以下模块中：
  - cli/init.py      → run_init()      项目初始化
  - cli/finalize.py  → run_finalize()  锁定设计基线
  - cli/accept.py    → run_accept()    人类接受手动规则
  - cli/doctor.py    → run_doctor()    治理数据健康扫描
  - cli/analyze/     → run_analyze()   核心分析流水线

日志架构：
  本模块是 OperationalLogger 的唯一初始化点。子命令通过 OperationalLogger.get()
  获取已初始化的单例实例，不再自行调用 init()，避免日志文件碎片化。
  每次 CLI 调用产生一个日志文件（.vibetracing/logs/vt-{timestamp}.jsonl），
  所有子命令的日志条目通过 run_id 关联到同一次运行。

  如果 main 的 init() 失败（如目录不可写），子命令的 get() 会返回空日志器，
  静默丢弃所有日志，但不阻断命令执行（LOG-VT-011 约束）。
"""

import argparse
import sys
import uuid
from pathlib import Path

from vibe_tracing import __version__
from vibe_tracing.infra.operational_logger import OperationalLogger

# 导入各子命令的处理函数
from vibe_tracing.cli.init import run_init
from vibe_tracing.cli.finalize import run_finalize
from vibe_tracing.cli.analyze import run_analyze
from vibe_tracing.cli.doctor import run_doctor
from vibe_tracing.cli.accept import run_accept

# 子命令 → 所属模块的映射，用于日志中标识异常来源
_COMMAND_MODULE_MAP = {
    "analyze": "cli.analyze.pipeline",
    "init": "cli.init",
    "finalize": "cli.finalize",
    "accept": "cli.accept",
    "doctor": "cli.doctor",
}


def _build_parser() -> argparse.ArgumentParser:
    """
    构建 argparse 解析器，注册所有子命令和参数。

    将解析器构建逻辑独立为函数，便于 main() 保持清晰的三段式结构。

    返回：
        argparse.ArgumentParser: 配置好的解析器
    """
    parser = argparse.ArgumentParser(
        description="Vibe Tracing (VT) - 一致性校验框架，用于 AI Coding Agent 的开发过程治理"
    )
    # --version 参数：打印版本号后退出
    parser.add_argument(
        "--version", action="version", version=f"vibe-tracing {__version__}"
    )

    # 创建子命令分组，dest="command" 表示解析后用户选择的子命令名存入 args.command
    subparsers = parser.add_subparsers(dest="command", help="子命令帮助")

    # ---------- 子命令 1：analyze（核心分析流水线）----------
    # 用途：运行完整的一致性分析，包括门禁检查、工具执行、分析器、报告生成
    analyze_parser = subparsers.add_parser(
        "analyze", help="分析项目一致性与合规性"
    )
    analyze_parser.add_argument(
        "--project-root",
        default=".",
        help="项目工作区根目录路径（默认：当前工作目录）",
    )
    analyze_parser.add_argument(
        "--out", help="输出目录路径（默认：<project-root>/output）"
    )
    # --pre-commit 模式：仅检查暂存区中的文件，用于 Git pre-commit hook
    analyze_parser.add_argument(
        "--pre-commit", action="store_true", help="以 Git pre-commit hook 模式运行（启用幽灵代码检测）"
    )
    # --gates-only 模式：仅运行门禁（快速模式），跳过工具执行和分析
    analyze_parser.add_argument(
        "--gates-only", action="store_true",
        help="仅运行完整性门禁（1, 2, 2.5），跳过工具执行和分析（pre-commit 快速模式）"
    )

    # ---------- 子命令 2：init（项目初始化）----------
    # 用途：在新项目中创建 VT 所需的模板文件（PRD、constraints、task_list 等）
    init_parser = subparsers.add_parser(
        "init", help="初始化新的 Vibe Tracing 项目，创建模板文件"
    )
    init_parser.add_argument(
        "--project-root",
        default=".",
        help="项目工作区根目录路径（默认：当前工作目录）",
    )
    init_parser.add_argument(
        "--name",
        help="项目的人类可读名称",
    )
    init_parser.add_argument(
        "--prefix",
        help="项目前缀缩写（例如 CapL, VT）",
    )

    # ---------- 子命令 3：finalize（锁定设计基线）----------
    # 用途：校验 PRD↔Architecture 映射关系，计算哈希基线并锁定
    finalize_parser = subparsers.add_parser(
        "finalize", help="从架构约束锁定项目配置基线"
    )
    finalize_parser.add_argument(
        "--project-root",
        default=".",
        help="项目工作区根目录路径（默认：当前工作目录）",
    )

    # ---------- 子命令 4：accept（人类接受手动规则）----------
    # 用途：将手动验证的架构约束标记为"已接受"，写入 human_decisions.json
    accept_parser = subparsers.add_parser(
        "accept", help="接受一条手动架构约束规则"
    )
    accept_parser.add_argument(
        "rule_id",
        help="要接受的规则 ID（例如 PRINCIPLE-VT-001）",
    )
    accept_parser.add_argument(
        "--project-root",
        default=".",
        help="项目工作区根目录路径（默认：当前工作目录）",
    )
    accept_parser.add_argument(
        "--by",
        default="human",
        help="接受者标识（默认：'human'）",
    )

    # ---------- 子命令 5：doctor（治理数据健康扫描）----------
    # 用途：检查所有治理数据文件的完整性和一致性
    doctor_parser = subparsers.add_parser(
        "doctor", help="扫描治理数据健康状态并报告问题"
    )
    doctor_parser.add_argument(
        "--project-root",
        default=".",
        help="项目工作区根目录路径（默认：当前工作目录）",
    )

    return parser


def main(argv=None):
    """
    CLI 主入口函数。

    执行流程：
    1. 构建 argparse 解析器，注册 5 个子命令（analyze/init/finalize/accept/doctor）
    2. 解析用户输入的命令行参数
    3. 初始化运维日志记录器（唯一的 init 调用点）
    4. 根据 args.command 路由到对应的 run_* 处理函数
    5. 全局异常捕获：未处理异常记录到运维日志 + stderr 提示，以退出码 1 终止

    异常捕获策略（单点记录 + 用户可见）：
      - 所有未处理异常由本函数的 except Exception 统一捕获
      - 异常详情通过 logger.exception() 记录到运维日志（供 VT 开发者排查）
      - 简短错误提示通过 print(stderr) 输出（供用户了解发生了什么）
      - 两者信息不重复：logger 记录完整 traceback，print 只输出一句话提示
      - KeyboardInterrupt 单独捕获，记录 cli_interrupted 事件后返回 130

    日志字段说明：
      - event:     事件类型（cli_command_start / cli_command_end / cli_error / cli_interrupted）
      - module:    异常来源模块（如 cli.analyze.pipeline、cli.init）
      - command:   用户执行的子命令名（如 analyze、init）
      - run_id:    本次运行的唯一标识（格式：RUN-{uuid}）

    参数：
        argv: 命令行参数列表，None 表示使用 sys.argv[1:]（真实命令行），
              传入列表可用于单元测试模拟命令行输入。

    返回：
        int: 退出码，0 表示成功，1 表示未处理异常，130 表示用户中断
    """
    # 如果未传入 argv，从系统参数获取（真实 CLI 调用场景）
    if argv is None:
        argv = sys.argv[1:]

    # 初始化为 None，用于异常处理时的安全引用
    logger = None
    run_id = ""
    source_module = ""

    try:
        # ========== 第一步：解析命令行参数 ==========
        # try 覆盖 parse_args，捕获 KeyboardInterrupt（用户在参数解析阶段按 Ctrl+C）
        parser = _build_parser()
        args = parser.parse_args(argv)

        # 未输入子命令时直接打印帮助并退出（无需日志）
        if args.command is None:
            parser.print_help()
            return 0

        # ========== 第二步：解析 project_root ==========
        # 统一解析一次，传递给日志初始化和 _dispatch，避免重复解析
        project_root = Path(args.project_root).resolve()

        # ========== 第三步：初始化运维日志记录器（唯一的 init 调用点）==========
        # 这是 OperationalLogger 的唯一初始化位置。
        # 子命令通过 OperationalLogger.get_or_init() 获取此实例，不再自行 init，
        # 避免日志文件碎片化（同一 run 的日志写入同一个文件）。
        # 防御性设计：即使 init 内部已 try/except，此处再包一层确保
        # init 在任何情况下都不会导致 main() 崩溃。
        run_id = f"RUN-{uuid.uuid4()}"
        try:
            logger = OperationalLogger.init(run_id=run_id, project_root=project_root)
        except Exception:
            # init 失败：日志体系不可用，后续日志调用安全降级（NullLogger 静默丢弃）
            logger = OperationalLogger.get()

        # 确定异常来源模块（用于日志中的 module 字段）
        source_module = _COMMAND_MODULE_MAP.get(args.command, f"cli.{args.command}")

        # ========== 第四步：路由到子命令处理函数 ==========
        logger.info(
            "cli_command_start",
            f"开始执行子命令: {args.command}",
            command=args.command,
            module=source_module,
        )

        exit_code = _dispatch(args, project_root)

        logger.info(
            "cli_command_end",
            f"子命令执行完成: {args.command}",
            command=args.command,
            module=source_module,
            exit_code=exit_code,
        )
        return exit_code

    except KeyboardInterrupt:
        # 用户中断（Ctrl+C）：记录事件后以退出码 130 终止（Unix 惯例）
        # logger 可能为 None（中断发生在 init 之前），安全降级
        if logger:
            logger.warning(
                "cli_interrupted",
                f"子命令 {getattr(args, 'command', '?')} 被用户中断",
                command=getattr(args, "command", "?"),
                module=source_module,
            )
        return 130

    except Exception as exc:
        # 未处理异常：双通道输出
        #   1. logger.exception() → 运维日志（完整 traceback，供 VT 开发者排查）
        #   2. print(stderr) → 终端（简短提示，供用户了解发生了什么）
        if logger:
            logger.exception(
                "cli_error",
                f"子命令 {getattr(args, 'command', '?')} 发生未处理异常: {exc}",
                exc=exc,
                command=getattr(args, "command", "?"),
                module=source_module,
                run_id=run_id,
            )
        print(f"\n错误: {getattr(args, 'command', 'vt')} 命令执行失败: {exc}", file=sys.stderr)
        return 1


def _dispatch(args, project_root: Path) -> int:
    """
    根据解析后的参数路由到对应的子命令处理函数。

    此函数封装了所有命令的路由逻辑，便于 main() 保持简洁，
    同时让异常捕获能准确标识出错的模块。

    参数：
        args:          argparse 解析后的命名空间对象
        project_root:  已解析的项目根目录（由 main() 统一解析，避免重复）

    返回：
        int: 子命令处理函数的退出码（0=成功）
    """
    if args.command == "analyze":
        # analyze 命令：最复杂的子命令，拥有最多的参数
        # 处理输出目录：如果用户指定了 --out，解析为绝对路径；
        # 否则设为 None，由 run_analyze 内部从 config.json 读取默认值
        if args.out:
            output_dir = Path(args.out)
            if not output_dir.is_absolute():
                output_dir = (project_root / output_dir).resolve()
        else:
            output_dir = None  # 在 run_analyze 内部从 config 解析

        return run_analyze(project_root, output_dir, is_pre_commit=args.pre_commit, gates_only=args.gates_only)

    elif args.command == "init":
        # init 命令：创建模板文件，name 和 prefix 可选
        return run_init(project_root, name=args.name, prefix=args.prefix)

    elif args.command == "finalize":
        # finalize 命令：校验 PRD↔Architecture 映射，锁定哈希基线
        return run_finalize(project_root)

    elif args.command == "accept":
        # accept 命令：将手动规则标记为已接受
        return run_accept(project_root, args.rule_id, accepted_by=args.by)

    elif args.command == "doctor":
        # doctor 命令：扫描治理数据健康状态
        return run_doctor(project_root)

    else:
        # 未知子命令（理论上 argparse 不会允许到这里，防御性处理）
        return 1


if __name__ == "__main__":
    sys.exit(main())
