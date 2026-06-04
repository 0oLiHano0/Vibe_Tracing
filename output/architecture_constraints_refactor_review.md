# Vibe Tracing 架构约束基线校验重构代码审查报告

对 [architecture_constraints_baseline_refactor.md](file:///Users/lihan/Project/Vibe_Tracing/output/architecture_constraints_baseline_refactor.md) 中定义的 **Phase 8: 架构约束基线校验重构（Git 单一基线方案）** 的实际代码实现进行了全面审查。

---

## 一、 整体结论

**基线重构设计方案已正确实现并运转**：
- 彻底移除了 `.vibetracing/architecture_constraints.base.json`，实现了以 Git 作为单一事实来源。
- 职责分离清晰：`vt analyze` 保持只读检测，`vt finalize` 负责验证与锁定指纹。
- `git_utils.py` 提供了健壮的低层 Git 命令包装。
- 自动化测试 `test_finalize.py` 和 `test_e2e_finalize_analyze.py` 覆盖了基线变更、同一 commit 提交、未提交阻断等各种核心流程并全部通过。

然而，在与旧测试套件的兼容性以及个别新实现模块中，存在以下几个 **Runtime Bug 和测试不兼容问题** 需要修复。

---

## 二、 关键代码实现审查对照

### 2.1 Git 封装层 `git_utils.py`
实现位置：[git_utils.py](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/git_utils.py)
- **`git_show(commit, path, cwd)`**：使用 `git show <commit>:<path>` 还原历史版本，实现正确。
- **`git_last_commit_touching(path, cwd)`**：使用 `git log -1 --format=%H -- <path>` 定位最近提交，实现正确。
- **`git_file_modified_after(path, after_commit, cwd)`**：使用 `git log <after_commit>..HEAD` 检测后续修改，实现正确。
- **`git_has_uncommitted_changes(path, cwd)`**：组合 `git diff` 与 `git diff --cached` 检查暂存和未暂存变更，实现正确。

### 2.2 CLI 锁定层 `cli.py`
实现位置：[cli.py](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/cli.py)
- **`run_finalize()` 中的时间线比对**：
  - 首次定稿允许直接通过（写入当前 HEAD commit 和 hash）。
  - 非首次定稿通过 `_validate_constraints_change` 执行变更日志校验。
  - 支持“格式变化但规则没变”时直接更新 hash。
  - 阻断机制：存在未提交变更时直接 exit 1。
  - 校验 change_log 时间线：若在同一个 commit 被修改，或 change_log 的最后 commit 晚于 constraints.json，则视为通过。
  - 验证失败时报错并输出变更的规则 diff 清单。
  - 幂等性：当语言、工具和 hash 均匹配时直接返回 0。

### 2.3 只读检测层 `architecture_change_proposal.py`
实现位置：[architecture_change_proposal.py](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/architecture_change_proposal.py)
- **`check_governance()`**：
  - 只读检测，绝不判定通过/不通过（始终返回 `is_valid=True`）。
  - 若 stored_hash 与当前 hash 不匹配，则还原旧版本并生成 diff 清单，附加修复指南并放入 `warnings`/`risks`/`gaps`。

### 2.4 门禁判定层 `architecture_compliance_checker.py`
实现位置：[architecture_compliance_checker.py](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/architecture_compliance_checker.py)
- 对 `GATE-VT-014` 的处理：
  - 当 `check_governance` 返回 `warnings` 但无 `errors` 时，将 `GATE-VT-014` 标记为 `"unclear"`。
  - 从而触发保守门禁：`gate decision` 判定为失败（FAIL），但由于 severity 为 `"should"` 或 `"unclear"` 门禁，不会被判定为 `"blocked"`（符合“暴露但不阻断”的语义）。

---

## 三、 发现的问题与 Runtime Bug

### 🔴 Bug 1: `assess_claim_credibility` 错误地将 `"task"` 视为工具证据
- **问题文件**：[claim_credibility.py:62](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/traceability/claim_credibility.py#L62)
- **问题描述**：
  ```python
  if source_type in ("test", "tool", "task"):
      has_tool_evidence = True
  ```
  在校验 Claim 的可信度（Credibility）时，只有 `"test"` 和 `"tool"`（即由 VT 运行的工具/测试证据）才能提供 `"high"` 可信度。而 `"task"` 只是任务列表记录本身，并非工具执行证据。如果允许 `"task"`，会导致原本只有任务关联而无测试支撑的 Claim 被评估为 `"high"`，从而违反设计并导致 `test_low_credibility_only_task_evidence` 测试失败。
- **修复方案**：将 `"task"` 从元组中移除，改为 `if source_type in ("test", "tool"):`。

### 🔴 Bug 2: `test_tool_execution.py` 对 shell 引用（`shlex.quote`）的单引号断言错误
- **问题文件**：[test_tool_execution.py](file:///Users/lihan/Project/Vibe_Tracing/tests/test_tool_execution.py#L154) (L154, L163, L173, L224)
- **问题描述**：
  测试中存在类似 `assert "'tests/test_foo.py'" in cmd` 的断言。它期望 `shlex.quote()` 始终将路径用单引号包围。
  然而在 Python 中，`shlex.quote` 仅在字符串中包含非安全字符或空格时才会添加单引号。对于普通的英文路径（如 `tests/test_foo.py`），它不添加单引号。导致该测试在新环境中 4 处断言失败。
- **修复方案**：去掉断言中多余的内层单引号，改为 `assert "tests/test_foo.py" in cmd`。

### 🔴 Bug 3: 旧测试套件未适配“analyze 运行前必须先 finalize”的规则
- **问题描述**：
  重构后，`run_analyze` 强制要求 config.json 中存在定稿的 `language`，否则会打印 `Error: Project not finalized` 并 exit 1。这导致 `test_cli_analyze.py`、`test_dynamic_prefix.py`、`test_prd_draft_guidance.py`、`test_prd_frozen_audit.py` 和 `test_e2e_samples.py` 中直接调用 `run_analyze` 或 `main(["analyze", ...])` 的测试全部报错。
- **修复方案**：
  1. 在 `test_cli_analyze.py` 的 `setup_mock_project` 辅助函数中，增加 `.vibetracing` 文件夹创建，并在 config.json 中预先写入 `language: "python"` 和 `validation_tools`。
  2. 在 `test_dynamic_prefix.py` 运行 `run_analyze` 之前先调用 `run_finalize` 写入定稿元数据，或在 config 中模拟写入。
  3. 在 `test_prd_draft_guidance.py` 中：
     - PRD 中当前状态的读取依赖 YAML Front Matter。原测试缺少 Front Matter 导致 PRD 被判定为 `active` 进而报错缺失 `task_list.json`。需要在 PRD 内容顶部补充 YAML Front Matter。
  4. 在 `test_prd_frozen_audit.py` 中，为测试 mock 的 `config.json` 预先写入 finalized 数据。
  5. 在 `test_e2e_samples.py` 中，在运行 `main(["analyze", ...])` 前，先对 fixture 目录运行 `main(["finalize", ...])`（由于这些 fixture 有 git 提交历史，可以通过 finalize 流程）。
