# Vibe Tracing 项目自管理规范

## 项目概述

Vibe Tracing (VT) 是一个 AI Coding Agent 的一致性校验框架。VT 自身也由 AI Agent 开发，因此**项目自身也受 VT 治理体系约束**——这是 VT 的核心设计验证：如果 VT 无法治理自身的开发过程，它也无法治理其他项目。

## 核心用户

VT项目的核心用户是AI Coding Agent，也就是你自己。它并不是为了限制你而存在，而是为了给你提供一个工具，帮你检查偏差，并提供指引。

DashBoard是让用户能够快速通过从PRD开始的完整生命周期链条，进行业务判断，以便能快速确认任务的完成情况。

你需要站在你就是用户的角度，通过VT提示的8项反思来思考VT项目。

dashboard的全链条呈现是必须的，因为你的任务最终需要人类（业务人员，没有开发经验，只能凭业务逻辑是否合理来验收），如果没有人类验收，你会一直陷在任务里，所以为了便于人类验收，需要直观的dashboard。

不要尝试设计过度的跳过检查，正确的方向是如何让vt的完整流程足够快而无需跳过，因为跳过会带来人类决策成本上升，一旦人类不作出“任务完成”的决策，你讲永远陷在任务里。

## 自管理机制

### Pre-commit Hook

`vt init` 安装 `.git/hooks/pre-commit`，在每次 `git commit` 时自动执行：

```sh
#!/bin/sh
set -e
# Vibe Tracing Git Guard
"<python_path>" -m vibe_tracing analyze --pre-commit
```

Hook 执行 Gate 1（防篡改）、Gate 2（幽灵代码检测）、Gate 2.5（AC 新鲜度）。任一门禁失败则阻断提交。

### Agent Claims

所有代码变更必须在 `.vibetracing/claims/current.json` 中声明对应的 Claim。Claim 关联 Task，Task 关联 PRD 的 REQ/AC。未声明 Claim 的业务代码称为"幽灵代码"，会被 Gate 2 阻断。

### 契约文件

- `docs/prd.md` — 需求文档，定义 REQ/AC
- `docs/architecture_constraints.json` — 架构约束，受 SHA256 哈希保护（设计基线，不可被 accept 命令修改）
- `docs/task_list.json` — 开发任务，关联 REQ/AC
- `.vibetracing/config.json` — 项目配置，存储双哈希基线
- `.vibetracing/human_decisions.json` — 人类决策记录（accept/risk/gap 决策），由 `vt accept` 和 Dashboard 写入

> [!CAUTION]
> VT项目自身的prd.md、architecture_constraints.json等与init阶段的src/vibe_tracing/templates，还有src/vibe_tracing/schemas，存在关联性关系，需要考虑是否关联更新。

### 门禁链路

```
git commit
  → pre-commit hook
    → Gate 1: constraints 哈希 + PRD 漂移 + PRD↔Arch 映射
    → Gate 2: 幽灵代码检测（staged 代码 vs staged claims）
    → Gate 2.5: AC 新鲜度（WARNING）
```

## 开发工作流

### 正常流程（必须遵守）

1. **更新 PRD**：在 `docs/prd.md` 中添加/修改 REQ 或 AC
2. **更新架构约束**（如需）：在 `docs/architecture_constraints.json` 中添加模块或规则
3. **执行 `vt finalize`**：锁定设计基线（PRD↔Arch 映射校验 + 双哈希）
4. **创建 Task**：在 `docs/task_list.json` 中添加 task，关联 REQ 和 AC
5. **编写代码和测试**
6. **创建 Claim**：在 `.vibetracing/claims/current.json` 中声明 claim，关联 task，引用 code_refs 和 test_refs
7. **`git add` + `git commit`**：hook 自动执行门禁校验

### 如何跳过自管理（仅限紧急情况）

> [!CAUTION]
> 跳过自管理是**例外而非常态**。每次跳过都应在后续补全 Claim 和门禁校验。

**场景 1：Hook 阻断了合法提交**

如果 Gate 2 错误地阻断了合法代码（如白名单遗漏），可以临时跳过 hook：

```sh
git commit --no-verify -m "描述原因"
```

**后续必须**：
- 分析 hook 误报原因
- 修复 hook 逻辑或更新白名单
- 补充 claims/current.json
- 运行 `vt analyze` 确认门禁通过

**场景 2：批量重构，逐文件创建 Claim 不现实**

如果改动涉及大量文件（如全局重命名），可以先提交再补 Claim：

```sh
# 1. 跳过 hook 提交代码
git commit --no-verify -m "refactor: 批量重命名 [待补 claim]"

# 2. 补充 claims
# 编辑 .vibetracing/claims/current.json

# 3. 单独提交 claims
git add .vibetracing/claims/current.json
git commit -m "chore: 补充重构 claims"

# 4. 运行完整 analyze 验证
vt analyze
```

**场景 3：修改设计文件（PRD/Constraints）**

设计文件的修改应通过 `vt finalize`，而非直接 commit。如果 finalize 的映射校验阻断了你：

1. 先修复 PRD↔Architecture 映射关系
2. 重新执行 `vt finalize`
3. 正常提交

**场景 4：测试/CI 环境不需要 hook**

CI 环境中 hook 通常不生效（git clone 不复制 hooks）。CI 应独立运行：

```sh
vt analyze  # 完整分析（不含 --gates-only）
```

### `vt accept` 命令说明

`vt accept RULE_ID` 将决策写入 `.vibetracing/human_decisions.json`，**不修改** `architecture_constraints.json`。compliance checker 在 analyze 时从 `human_decisions.json` 读取已接受的规则。

- 只接受 `verification_method == "manual"` 的规则
- 重复 accept 同一规则会提示"已被接受"
- machine 规则被拒绝（需程序验证，不支持人工确认）
- 迁移旧数据：`vt migrate-accepted-rules`（将 constraints.json 中的 embedded accepted_by 迁移到 human_decisions.json）

## 不可跳过的行为

以下行为**任何时候都不可跳过**：

- `vt finalize` 的 PRD↔Architecture 映射校验（死链检测 + MUST 覆盖）
- Gate 1 的 constraints 哈希校验（防篡改）
- Claim 的自引用检测（evidence_refs 不能仅指向自身）
- Schema 校验（task_list / constraints / claims 的 JSON Schema）

## 开发阶段与设计阶段的职责边界

| 阶段 | 命令 | 职责 |
|---|---|---|
| 设计阶段 | `vt init` → `vt finalize` | 锁定 PRD + constraints 基线 |
| 开发阶段 | `vt analyze` | 校验 task/claim/code 与基线的一致性 |
| 提交时 | `--pre-commit --gates-only` | 快速校验完整性门禁 |

设计阶段的产物（PRD、constraints）受哈希保护，不可在开发阶段静默修改。开发阶段的产物（task、claim、code）通过声明式校验与设计基线保持一致。

## 运行时日志排错指南

VT 每次运行会生成 JSON Lines 格式的运行日志，位于 `.vibetracing/logs/vt-{timestamp}.jsonl`。日志级别通过 `config.json` 的 `logging.level` 控制，开发阶段默认 `DEBUG`。

### 何时查看日志

- Gate 决策不符合预期时（应该 pass 但 blocked，或反过来）
- 某个 AC/requirement 的覆盖状态不符合预期时
- 架构合规检查结果异常时
- 性能问题排查（哪个阶段耗时异常）

### 常见排错场景

**场景 1：某个 AC 为什么是 uncovered？**

```bash
# 在最新日志中搜索该 AC 的映射链
python3 -c "
import json
latest = sorted(__import__('glob').glob('.vibetracing/logs/*.jsonl'))[-1]
with open(latest) as f:
    for line in f:
        d = json.loads(line)
        if d.get('event') == 'ac_mapping' and d.get('ac_id') == 'AC-VT-xxx-xx':
            print(json.dumps(d, indent=2, ensure_ascii=False))
"
```

日志会显示：parent_task_id → test_refs 列表 → 每个 test 的 pass/fail 状态 → uncovered_reason（no_tests / all_failed）。

**场景 2：某个 requirement 为什么是 partial？**

```bash
python3 -c "
import json
latest = sorted(__import__('glob').glob('.vibetracing/logs/*.jsonl'))[-1]
with open(latest) as f:
    for line in f:
        d = json.loads(line)
        if d.get('event') == 'req_mapping' and d.get('req_id') == 'REQ-VT-xxx':
            print(json.dumps(d, indent=2, ensure_ascii=False))
"
```

日志会显示：related_tasks 列表 → tasks_with_claims → tasks_without_claims。没有 claim 的 task 就是覆盖缺口。

**场景 3：Gate 被 blocked，是哪些 item 导致的？**

```bash
python3 -c "
import json
latest = sorted(__import__('glob').glob('.vibetracing/logs/*.jsonl'))[-1]
with open(latest) as f:
    for line in f:
        d = json.loads(line)
        if d.get('event') in ('gate_gap_eval', 'gate_risk_eval') and d.get('final_status') == 'blocked':
            print(json.dumps(d, indent=2, ensure_ascii=False))
"
```

日志会显示每个被 block 的 item 的 item_id、item_type、reason、是否 stale、是否被人类决策覆盖。

**场景 4：某条架构约束为什么被判 violated？**

```bash
python3 -c "
import json
latest = sorted(__import__('glob').glob('.vibetracing/logs/*.jsonl'))[-1]
with open(latest) as f:
    for line in f:
        d = json.loads(line)
        if d.get('event') in ('compliance_import_violation', 'compliance_dep_vt001_match'):
            print(json.dumps(d, indent=2, ensure_ascii=False))
"
```

日志会显示：具体文件、行号、import 语句、违反的规则类型。

**场景 5：哪个阶段耗时异常？**

```bash
python3 -c "
import json
latest = sorted(__import__('glob').glob('.vibetracing/logs/*.jsonl'))[-1]
with open(latest) as f:
    for line in f:
        d = json.loads(line)
        if d.get('event') == 'phase_end':
            print(f'{d[\"phase\"]:30s} {d[\"duration_ms\"]:>6}ms')
"
```

**场景 6：`vt finalize` 失败，卡在哪一步？**

```bash
python3 -c "
import json
latest = sorted(__import__('glob').glob('.vibetracing/logs/*.jsonl'))[-1]
with open(latest) as f:
    for line in f:
        d = json.loads(line)
        event = d.get('event', '')
        if event in ('phase_end', 'run_end') or 'error' in event.lower() or d.get('level') in ('ERROR', 'WARNING'):
            fields = {k:v for k,v in d.items() if k not in ('timestamp','run_id','elapsed_ms')}
            print(json.dumps(fields, indent=2, ensure_ascii=False))
"
```

日志会显示：每个阶段（load_files, prd_arch_mapping, hash computation, constraints_validation, git_operations）的耗时和结果。失败时会记录具体的 subprocess exit_code、哈希值、映射校验详情。

**场景 7：`vt finalize` 的映射校验为什么拒绝了我？**

```bash
python3 -c "
import json
latest = sorted(__import__('glob').glob('.vibetracing/logs/*.jsonl'))[-1]
with open(latest) as f:
    for line in f:
        d = json.loads(line)
        if d.get('event') in ('finalize_mapping', 'finalize_hash', 'finalize_config'):
            print(json.dumps(d, indent=2, ensure_ascii=False))
"
```

日志会显示：PRD 中发现了哪些 req、constraints 中发现了哪些 module、映射关系、计算出的哈希值。

**场景 8：`vt init` 创建了哪些文件？跳过了哪些？**

```bash
python3 -c "
import json
latest = sorted(__import__('glob').glob('.vibetracing/logs/*.jsonl'))[-1]
with open(latest) as f:
    for line in f:
        d = json.loads(line)
        if d.get('event') in ('init_step', 'run_end'):
            print(json.dumps(d, indent=2, ensure_ascii=False))
"
```

日志会显示：每个文件的创建/跳过状态、总耗时、files_created 和 files_skipped 列表。

**场景 9：已 accept 的规则仍然出现在 unclear 列表中？**

```bash
# 1. 检查 human_decisions.json 中是否有对应记录
cat .vibetracing/human_decisions.json | python3 -c "
import sys, json
data = json.load(sys.stdin)
for d in data.get('decisions', []):
    if d.get('category') == 'accepted_rule':
        print(f\"{d['targetId']} by {d['decidedBy']} at {d['timestamp']}\")
"

# 2. 检查 compliance checker 是否读取了 human_decisions
# 如果 accept 后 constraints.json 中仍有 accepted_by 字段（旧数据），
# 运行迁移脚本：vt migrate-accepted-rules
```

常见原因：
- accept 写入了 human_decisions.json 但 compliance checker 未收到（检查 pipeline 是否传递了 human_decisions 参数）
- 旧数据中 constraints.json 仍有 embedded accepted_by（运行 `vt migrate-accepted-rules` 迁移）

**场景 10：coverage_json 格式错误？**

```
Error: xxx.py failed (exit 0). 不支持的工具输出格式：coverage_json。
```

coverage 是批量工具，不应逐文件执行。如果出现此错误，检查 `tool_evidence_adapter.py` 的 `execute_all()` 是否在 per-file 循环中跳过了 `coverage` category。coverage 通过 `_measure_source_coverage()` 从 baseline 单独处理。

**场景 11：staged 文件触发"未配置的代码文件类型"WARNING？**

`_check_staged_extensions()` 只检查有工具配置的语言的扩展名。非代码文件（.md, .json, .html）不会触发此 WARNING。

如果仍然触发，检查 `architecture_constraints.json` 的 `language_tool_matrix` 中是否有某个语言条目配置了工具但扩展名不完整。

**场景 12：`vt accept` 为什么拒绝接受某条规则？**

```bash
python3 -c "
import json
latest = sorted(__import__('glob').glob('.vibetracing/logs/*.jsonl'))[-1]
with open(latest) as f:
    for line in f:
        d = json.loads(line)
        if d.get('event') in ('accept_validation', 'accept_error', 'accept_rule'):
            print(json.dumps(d, indent=2, ensure_ascii=False))
"
```

日志会显示：规则是否找到、verification_method 是否为 manual、是否已被接受过、写入 human_decisions.json 的结果。

**场景 13：`vt doctor` 的诊断结果详情**

```bash
python3 -c "
import json
latest = sorted(__import__('glob').glob('.vibetracing/logs/*.jsonl'))[-1]
with open(latest) as f:
    for line in f:
        d = json.loads(line)
        if d.get('event') in ('doctor_load', 'doctor_check', 'doctor_end'):
            print(json.dumps(d, indent=2, ensure_ascii=False))
"
```

日志会显示：每个数据文件的加载结果（pass/fail/warning）、每个诊断检查的结果和发现的问题数、总汇总。

### 日志级别说明

| 级别 | 内容 | 何时启用 |
|---|---|---|
| DEBUG | 逐项决策链（每个 req/ac/gap/risk 的映射和判定过程）、模块导入检查详情、finalize 映射/哈希详情、doctor 诊断明细 | 开发排错、规则合理性排查 |
| INFO | pipeline 阶段耗时、子进程执行、缓存统计、gate_decision、init/finalize/accept 操作步骤 | 日常运行监控 |
| WARNING | hint 回退到硬编码字符串、可恢复异常、accept 验证警告 | 发现潜在问题 |
| ERROR | 不可恢复异常、文件 I/O 失败、subprocess 非零退出 | 故障定位 |

生产环境建议设为 `INFO`，开发排错时设为 `DEBUG`。DEBUG 级别会产生大量日志（单次运行数百条），但每条都是可追溯的决策证据。

### 日志覆盖范围

| 命令 | 日志事件 |
|---|---|
| `vt init` | run_start, init_step（每个文件）, run_end |
| `vt finalize` | run_start, 6 个 phase_end, 10+ subprocess 调用, 哈希/映射/配置详情, run_end |
| `vt analyze` | run_start, 8 个 phase_end, 逐项 req/ac/gap/risk 决策链, 模块边界导入检查, gate 中间状态, run_end |
| `vt accept` | run_start, 约束加载/查找/验证, accept_rule, run_end |
| `vt doctor` | run_start, 5 个 doctor_load, 5 个 doctor_check, doctor_end 汇总 |
