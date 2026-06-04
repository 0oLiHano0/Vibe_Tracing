# Phase 8: 架构约束基线校验优化 (Git/Hash 替代 Base.json)

## 背景

当前 Vibe Tracing 通过比对两个物理文件：
1. `docs/architecture_constraints.json` (当前配置)
2. `.vibetracing/architecture_constraints.base.json` (基线配置)

来检测架构漂移并审计规则变更。这种方式在 Git 管理的项目中存在冗余（违反“剃刀原则”和 DRY 原则），增加了维护和同步成本。

## 改造目标

通过引入 **“Hash 门哨”** 与 **“Git 动态溯源”**，彻底移除 `.vibetracing/architecture_constraints.base.json`。
* `vt finalize` 时，将当前架构约束文件的 SHA256 哈希值以及当前的 Git HEAD Commit Hash 写入 `.vibetracing/config.json`。
* `vt analyze` 时，先比对当前架构约束的哈希值。若不匹配，则通过 `git show <commit>:<path>` 动态读出定稿时刻的内容进行语义 Diff。
* 提供“优雅降级”机制，兼容非 Git 环境或历史重写等边缘场景。

---

## 变更说明

### 1. 结构与配置变更

#### [DELETE] `.vibetracing/architecture_constraints.base.json`
彻底从代码库和模板中移除该文件。

#### [MODIFY] `src/vibe_tracing/cli.py` (run_finalize)
* 计算 `docs/architecture_constraints.json` 的 SHA256 哈希。
* 尝试通过 `git rev-parse HEAD` 获取当前的 HEAD commit hash。
* 将 `architecture_constraints_hash` 和 `finalize_git_commit` 写入 `.vibetracing/config.json`。
* 即使已经 finalize，如果 `architecture_constraints.json` 的内容发生变化（哈希不匹配），允许通过重新运行 `vt finalize` 锁定新哈希与新 Commit，实现“合理演进的定稿印封”。

---

### 2. 漂移检测引擎变更

#### [MODIFY] [architecture_change_proposal.py](file:///Users/lihan/Project/Vibe_Tracing/src/vibe_tracing/architecture_change_proposal.py) (check_governance)
* **比对逻辑升级**：
  1. 计算 `docs/architecture_constraints.json` 的当前哈希。
  2. 读取 `config.json` 中的 `architecture_constraints_hash`。
  3. 如果 `config.json` 中不存在哈希（未 finalize），跳过漂移检查。
  4. 如果哈希一致，判定为 `is_valid=True`，无漂移，直接返回（性能 O(1)）。
  5. 如果哈希不一致，获取定稿时刻的基线内容：
     * **第一优先级**：如果 `finalize_git_commit` 存在，且处于 Git 仓库中，执行 `git show <commit_sha>:<relative_path>` 读取基线内容。
     * **第二优先级（优雅降级）**：如果非 Git 环境，或者 `git show` 失败，检查是否存在 `.vibetracing/architecture_constraints.base.json`（兼容存量测试）。
     * **兜底失败**：如果上述均无法获取基线内容，报告 `must` 级别风险（提示无法执行漂移审计）。
  6. 进行语义 Diff（复用现有的 `_find_differences` 逻辑），产出具体的变更项进行审计日志比对。

---

### 3. 测试适配变更

#### [MODIFY] [test_finalize.py](file:///Users/lihan/Project/Vibe_Tracing/tests/test_finalize.py)
* 校验 `finalize` 后 `config.json` 中是否包含正确的 `architecture_constraints_hash`。
* 校验重新 finalize 时，哈希是否会被更新。

#### [MODIFY] [test_architecture_change_proposal.py](file:///Users/lihan/Project/Vibe_Tracing/tests/test_architecture_change_proposal.py) & [test_quality_gates.py](file:///Users/lihan/Project/Vibe_Tracing/tests/test_quality_gates.py) & [test_raw_input_loader.py](file:///Users/lihan/Project/Vibe_Tracing/tests/test_raw_input_loader.py)
* 由于引入了优雅降级机制（如果存在物理 base.json，仍作为 fallback 使用），现有的非 Git 测试用例（通过写入物理 base.json 模拟基线）将直接兼容通过。
* 新增针对真实 Git 溯源环境的单元测试，模拟 `git init`、修改文件、`git show` 校验漂移的完整流程。

---

## 验证计划

### 自动化测试
运行所有现有测试，确保在兼容层作用下无 Regression：
```bash
pytest tests/test_finalize.py
pytest tests/test_architecture_change_proposal.py
pytest tests/test_quality_gates.py
pytest tests/test_raw_input_loader.py
```

### 手动验证
1. 初始化项目 `vibe-tracing init`。
2. 定稿 `vibe-tracing finalize`，确认 `config.json` 写入了哈希和 commit_sha。
3. 修改 `docs/architecture_constraints.json`，运行 `vibe-tracing analyze`，确认在无 change_log 时抛出阻断错误，在有 change_log 时仅提示警告。
4. 再次运行 `vibe-tracing finalize`，确认哈希被更新，之后 `analyze` 恢复 PASS。
