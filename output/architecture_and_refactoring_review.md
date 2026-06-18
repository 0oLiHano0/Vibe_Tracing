# Vibe Tracing 架构重构方案深度评审报告

本报告针对以下两份设计文档进行深度技术评审：
1. [docs/evidence_refactoring_plan.md](file:///Users/lihan/Project/Vibe_Tracing/docs/evidence_refactoring_plan.md) (证据体系与门禁判定引擎重构方案)
2. [docs/analyze_redesign.md](file:///Users/lihan/Project/Vibe_Tracing/docs/analyze_redesign.md) (Analyze 阶段重构：文件分布与接口契约)

经过对 Vibe Tracing 现有源码、测试用例和架构约束文件的深度静态分析，重构方案整体设计思路（SQLite 内存表 + 数据扁平化 + 一任务一声明文件）非常切合项目演进方向，能够有效解决单一 JSON 膨胀和多层嵌套查询的痛点。然而，方案在**自我治理一致性、导入一致性、缓存失效机制、子命令兼容性**四个维度存在若干**关键设计遗漏/缺陷**，若不加修正，重构实施后将导致系统崩溃或门禁失效。

---

## 1. 致命缺陷：自我治理配置 (`architecture_constraints.json`) 未同步更新

### 问题分析
Vibe Tracing 采用自省机制（`test_vt_can_analyze_itself`），使用 `docs/architecture_constraints.json` 约束自身代码结构。
重构方案中，以下变更会直接导致该约束文件失效或冲突：
1. **模块与文件路径重组**：所有 `.py` 文件被移入 `cli/`、`domain/`、`infra/`、`analyzers/`。而约束文件中的 `module_boundaries` 依然声明了旧的扁平路径（如 `cli.py`、`raw_input_loader.py`），且新增的目录结构没有在 boundaries 中定义。
2. **证据与声明文件变更**：方案中删除了 `evidence_index.json` 和 `claims/current.json`，并拆分出 `test_results.json` 等文件。但约束文件中有数十处规则（如 `PRINCIPLE-VT-011`、`PRINCIPLE-VT-014`、`STORE-VT-002`）硬编码要求必须生成 `evidence_index.json` 和校验 `current.json`。

### 影响
如果不更新 `architecture_constraints.json`，重构后的代码在执行 `vt analyze` 自省时，**门禁系统将直接判定自身架构违规（Block）**，导致 CI/CD 流程阻断。

### 解决方案
必须在实施计划的 **Phase 6** 中增加一个子任务，专门更新 `docs/architecture_constraints.json`：
* 将 `evidence_index.json` 替换为新拆分的 `test_results.json` 和 `coverage_reports.json`。
* 将 `claims/current.json` 替换为 `.vibetracing/claims/CLAIM-*.json`。
* 更新 `module_boundaries` 下所有模块的 `owned_files` 以匹配新的嵌套 package 路径。

---

## 2. 核心漏洞：`architecture_compliance_checker.py` 无法识别嵌套包导入

### 问题分析
在 `architecture_compliance_checker.py` 中，`_get_module_for_import` 方法通过检查导入模块的第二级路径（`parts[1]`）来映射架构模块：
```python
parts = imported_module.split(".")
sub = parts[1] # 对于旧导入 vibe_tracing.claim_loader，sub = "claim_loader"
for boundary in self.constraints.get("module_boundaries", []):
    for owned in boundary.get("owned_files", []):
        if owned.removesuffix(".py") == sub:
            return boundary["module_id"], boundary["name"]
```
但在重构后，导入路径变为了 `vibe_tracing.domain.claim_loader`。
此时 `parts[1]` 为 `"domain"`，它无法匹配任何 `owned_files`（如 `claim_loader.py`）。

### 影响
这会导致 `_get_module_for_import` 对所有新导入均返回 `(None, None)`。**所有的跨模块依赖白名单 (`allowed_to_call`) 和黑名单 (`forbidden_to_call`) 校验将全部失效**，系统无法拦截架构依赖违规。

### 解决方案
修改 `architecture_compliance_checker.py` 中提取子模块名的逻辑，兼容嵌套包结构：
```python
if len(parts) >= 3 and parts[1] in ("cli", "domain", "analyzers", "infra"):
    sub = parts[2]
else:
    sub = parts[1]
```

---

## 3. 潜在 Bug：陈旧缓存无法失效 (Cache Invalidation Leak)

### 问题分析
重构方案抛弃了 mtime 比对，采用 SQLite `INSERT OR REPLACE` (UPSERT) 更新证据。
如果用户**删除或重命名**了某个测试用例（例如将 `test_old` 改为 `test_new`）：
1. 启动时，旧的 `test_results.json` 缓存被载入数据库，`test_old` 的记录被标记为 `carried_over = 1`。
2. pytest 运行，新生成了 `test_new` 的结果，UPSERT 入库（`carried_over = 0`）。
3. 由于 `test_old` 不再运行，它在数据库中不会被覆盖，其 `carried_over` 仍为 `1`。
4. 导出时，`test_old` 依然会被写回 `test_results.json`。

### 影响
**被删除/改名的测试用例证据将永久残留在 `test_results.json` 中**，形成“幽灵测试”，从而导致门禁判定采信了已经不存在的测试通过证据。

### 解决方案
引入局部缓存清理逻辑：
* 在执行 pytest/coverage 工具前，或者写入新证据前，根据本次运行的**目标文件 $F$**，在数据库中清理该文件对应的所有旧缓存：
  * **测试结果**：`DELETE FROM test_results WHERE (nodeid LIKE 'F::%' OR nodeid = 'F') AND carried_over = 1`
  * **覆盖率**：`DELETE FROM coverage_reports WHERE source_path = 'F' AND carried_over = 1`
* 加载历史缓存时，检查文件在磁盘上是否物理存在，若已删除则不予载入。

---

## 4. 接口遗漏：`vt doctor` 和 `vt init` 兼容性未定义

### 问题分析
重构方案将 `vt doctor` 和 `vt init` 标为“不在重构范围内（不变文件）”。
但实际上：
* `doctor.py` 内部直接硬编码读取 `.vibetracing/claims/current.json` 和 `output/evidence_index.json`，并进行一致性核对。
* `init.py` 依然会在初始化时创建已废弃的空 `current.json` 文件。

### 影响
重构完成后，一旦运行 `vt doctor`，它将因为找不到 `current.json` 和 `evidence_index.json` 而报错或报告 0 个 Claim。

### 解决方案
必须把 `vt doctor` 和 `vt init` 纳入 Phase 6 的适配修改中：
* `doctor.py`：使用新重构的 `ClaimLoader.load()` 加载多文件，并适配 `test_results.json` 与 `coverage_reports.json` 的双文件读取。
* `init.py`：不再生成 `current.json`，改为创建 `.vibetracing/claims/` 目录并放置 `.gitkeep` 或 Claim 模板。

---

## 5. 设计细节修正建议

### 5.1 Claims 表外键：硬约束 vs 软校验
方案在第三章 2 中提出“不设置硬性物理 FOREIGN KEY，通过 LEFT JOIN 软校验，以便收集全量错误”。但在第三章 3.A 和第五章 5.5 中，又对 `claims.related_task` 使用了硬外键。
* **弊端**：如果用户同时提交了 3 个 Claim，其中 2 个关联了不存在的 Task。硬外键会在插入第一个错误 Claim 时抛出 `IntegrityError` 中断事务，使用户无法一次性看到所有错误。
* **建议**：将 `claims` 表的 `related_task` 也改为 `LEFT JOIN` 软校验。保持所有关系校验策略的完全一致，以提供最佳的 Agent 批量报错体验。

### 5.2 活跃声明 (Active Claims) 的识别范围
方案提出仅通过 `git diff --cached` 识别暂存区中的 `CLAIM-*.json`。
* **局限性**：在本地开发过程中，开发者通常会在 `git add` 之前运行 `vt analyze` 预览门禁状态。如果只读取 staged 文件，他们刚修改的未暂存（unstaged）或未跟踪（untracked）的 Claim 文件将无法被识别。
* **建议**：活跃声明应整合 `git diff --name-only`（未暂存）+ `git diff --cached --name-only`（已暂存）+ `git status --porcelain`（未跟踪）的结果，以确保本地预览体验与 pre-commit 钩子一致。

### 5.3 现有工作区 Schema 违规修复 (提示)
在当前的测试套件中，`tests/test_self_governance.py` 报错，原因是 `docs/architecture_constraints.json` 中的 `storage_rules[0]` 包含了 schema 未定义的 `allowed_dependencies` 和 `forbidden_dependencies` 属性。
* **修复建议**：在进行本次重构前，应先将这两个属性移至 `dependency_rules` 下，或者修改 `architecture_constraints.schema.json` 允许该属性，以恢复测试绿灯。
