# 架构锁逃逸漏洞修复计划 (Architecture Lock Bypass Fix)

您的直觉极其敏锐，甚至可以说是**直接指出了当前系统的一个严重架构漏洞**！

正如您所敏锐察觉到的：“从逻辑上来说，finalize 其实干了两件事：1是上锁，2是在 analyze 时检查是否有未暴露的修改”。
**但代码目前的现状是：代码边界确实不清晰，甚至可以说它“漏防”了！**

目前 `vt finalize` 确实认真地执行了哈希对比和 Git 日志审计（上锁）。但是，负责日常检查的 `vt analyze` 却存在一个巨大的盲区：它只检查了是否“曾经上过锁”（通过判断 config.json 里有没有 `language`），却**没有去核对当前的锁孔和钥匙（Hash 指纹）是否还匹配**！
这意味着，如果有人（或 AI）偷偷修改了 `architecture_constraints.json`，只要他不主动运行 `vt finalize`，他就可以直接运行 `vt analyze` 蒙混过关，防腐层被彻底绕过。

这就是为什么您在图上没看到 `analyze` 的检查路径——因为当前代码里根本就没写这层防御。

## User Review Required
> [!IMPORTANT]
> 这是一个高危的架构逻辑漏洞。以下计划将修补 `vt analyze` 的防腐层盲区，把您构想的逻辑在代码中真正闭环。请确认方案。

## Proposed Changes

### [MODIFY] `src/vibe_tracing/cli.py` (在 `run_analyze` 函数中)

**修复逻辑**：
将“定稿后篡改检测”严格下放到 `vt analyze` 中。每次执行 `analyze` 时，必须读取当前 `architecture_constraints.json` 的物理 Hash，并与 `config.json` 中保存的 `architecture_constraints_hash` 进行强比对。如果不匹配，立刻阻断整个流水线。

```python
# 在 run_analyze 中执行 Tool 前补充以下指纹强校验逻辑：

# 1. 提取 config.json 中的锁定指纹
config_hash = raw_loader.config_data.get("architecture_constraints_hash")

# 2. 如果存在锁定指纹（已定稿），则计算当前磁盘上架构文件的实时指纹
if config_hash and constraints_record and constraints_record.status == "ok":
    import hashlib
    current_hash = hashlib.sha256(Path(constraints_record.file_path).read_bytes()).hexdigest()
    
    # 3. 如果指纹不匹配，说明有人绕过了 vt finalize 偷偷修改了架构红线
    if current_hash != config_hash:
        print(
            "Critical Error: Architecture constraints have been modified since the last lock! "
            "The anti-corruption layer prevents execution. "
            "Please run 'vibe-tracing finalize' to audit and lock the new changes.",
            file=sys.stderr
        )
        return 1
```

## Verification Plan
1. 修改代码。
2. 运行初始化并执行 `vt finalize` 完成一次上锁。
3. 故意修改 `architecture_constraints.json`（比如增加一条无用规则），**不运行** `vt finalize`。
4. 直接运行 `vt analyze`，验证系统是否会报出 `Critical Error` 并成功拦截（修补前的代码会直接放行）。
5. 运行 `vt finalize` 完成审计更新后，再次运行 `vt analyze`，验证是否恢复正常。

---

## 独立审查：完整攻击面分析

> 由架构师独立审查，不仅验证报告指出的漏洞，还排查报告可能遗漏的攻击向量。

### 报告指出的漏洞 — **准确**

`vt analyze` 第 508 行仅检查 `config.json` 中是否存在 `language` 字段：
```python
if not config_language:
    print("Error: Project not finalized...")
    return 1
```
**从未校验 `architecture_constraints_hash` 与磁盘文件的一致性**。攻击者修改 constraints 后直接运行 `vt analyze`，防腐层被完全绕过。

### 报告遗漏的攻击面

#### 遗漏 1: config.json Hash 伪造攻击（高危）

**攻击路径**：
1. 攻击者修改 `architecture_constraints.json`（如降低门禁阈值、删除安全规则）
2. 攻击者同时手动编辑 `config.json`，将 `architecture_constraints_hash` 更新为修改后的文件 Hash
3. 运行 `vt analyze` → Hash 比对通过 → 防腐层失效

**报告方案的盲区**：报告提议的修复只做 Hash 比对，但**未验证 Hash 的来源可信性**。攻击者可以同时篡改 constraints 和 config 中的 hash，绕过比对。

**根因**：`vt finalize` 写入三个字段（`architecture_constraints_hash`, `finalize_git_commit`, `finalize_constraints_path`），但报告方案仅校验 hash 值本身，未校验 finalize 元数据的完整性。

#### 遗漏 2: task_list.json / agent_claims.json 无锁定保护（中危）

`config.json` 中只存储了 `architecture_constraints.json` 的 Hash。`task_list.json` 和 `agent_claims.json` **没有任何 Hash 锁定**。

**攻击路径**：
1. `vt finalize` 完成上锁
2. 攻击者修改 `task_list.json`（如将 `must` 任务降级为 `could`，或删除 definition_of_done）
3. 运行 `vt analyze` → 无任何校验 → 基于被篡改的任务列表生成报告

**影响**：门禁判定基于被篡改的输入，报告可信度归零。

#### 遗漏 3: Git 环境依赖的静默降级（低危）

`_validate_constraints_change()` 依赖 `git show`、`git_last_commit_touching` 等 Git 命令。在以下场景中会静默降级：
- `finalize_git_commit` 为 `None`（`cli.py:280`，Git 命令失败时回退为 None）
- 非 Git 环境或 Git 仓库损坏

当 `finalize_git_commit` 为 None 时，`_validate_constraints_change()` 第 160 行直接返回 `True, "首次定稿"`，**跳过所有审计**。

### 修正后的完整修复方案

报告方案需从"单点 Hash 比对"升级为"三层防御"：

#### 第一层：analyze 入口 Hash 强校验（报告已提出，需增强）

在 `run_analyze()` 的工具执行前插入：

```python
config_hash = raw_loader.config_data.get("architecture_constraints_hash")
finalize_commit = raw_loader.config_data.get("finalize_git_commit")

if config_hash and constraints_record and constraints_record.status == "ok":
    import hashlib
    current_hash = hashlib.sha256(
        Path(constraints_record.file_path).read_bytes()
    ).hexdigest()
    if current_hash != config_hash:
        print(
            "Critical Error: Architecture constraints modified since last lock! "
            "Run 'vibe-tracing finalize' to audit and re-lock.",
            file=sys.stderr
        )
        return 1
```

**增强点**：同时检查 `finalize_git_commit` 是否存在。若 config 中有 hash 但无 finalize_commit，说明 hash 可能是手动伪造的，应同样拦截。

#### 第二层：扩展锁定范围至 task_list 和 agent_claims（新提出）

`vt finalize` 应额外计算并存储 `task_list.json` 和 `agent_claims.json` 的 Hash：

```python
config_data["task_list_hash"] = hashlib.sha256(task_list_path.read_bytes()).hexdigest()
config_data["agent_claims_hash"] = hashlib.sha256(claims_path.read_bytes()).hexdigest()
```

`vt analyze` 入口对这两个文件执行同样的 Hash 比对。

#### 第三层：finalize 元数据完整性校验（新提出）

在 `vt analyze` 入口，若检测到 `architecture_constraints_hash` 存在，必须同时验证：
- `finalize_git_commit` 不为 None/空
- `finalize_constraints_path` 不为 None/空
- 三者同时存在才视为"已合法定稿"

任一缺失则视为配置损坏，要求重新 `vt finalize`。

### 攻击面矩阵

| 攻击向量 | 报告覆盖 | 修复层 | 严重度 |
|---|---|---|---|
| 修改 constraints 后直接 analyze | 已覆盖 | 第一层 | 高 |
| 同时伪造 config.json 中的 hash | **未覆盖** | 第一层增强 + 第三层 | 高 |
| 篡改 task_list.json | **未覆盖** | 第二层 | 中 |
| 篡改 agent_claims.json | **未覆盖** | 第二层 | 中 |
| Git 环境缺失导致审计降级 | **未覆盖** | 第三层 | 低 |

### 验证计划（扩展）

在报告原有验证步骤基础上，追加：
6. 伪造攻击测试：修改 constraints 后手动更新 config.json 中的 hash，验证增强后的第一层是否仍能拦截
7. task_list 篡改测试：finalize 后修改 task_list.json，验证第二层是否拦截
8. 元数据缺失测试：手动清空 config.json 中的 `finalize_git_commit`，验证第三层是否拦截
