# 设计阶段代码逻辑审查

对 `vt init`、`vt finalize`、`vt accept`、映射校验、门禁链路的代码逻辑进行架构与流程优化审查。

---

## 一、问题总览

按严重程度排序，共 22 项发现：

| # | 严重度 | 模块 | 问题 |
|---|--------|------|------|
| 1 | **High** | prd_arch_validator | `priority == "unclear"` 的需求被静默跳过，不计入 must_uncovered 或 should_uncovered，违反保守判断原则 |
| 2 | **High** | prd_arch_validator | 死链检查（递归）与覆盖率检查（浅层）使用不同作用域，同一需求可同时"非死链"且"未覆盖" |
| 3 | **High** | prd_arch_validator | 仅 `module_boundaries` 和 `data_flow_rules` 计入覆盖率，其余 9 类规则（principles、security 等）的 `related_requirements` 不算覆盖 |
| 4 | **High** | gates + pipeline | auto_generate_claim 在 Gate 2 之后执行，且 GhostCodeReconciler 读 git index 而非文件系统，自动生成的 claims 永远无法被 Gate 2 看到 |
| 5 | Medium | gates | Gate 1 失败时短路，Gate 1b（信息性警告）被跳过，用户丢失 PRD 漂移诊断信息 |
| 6 | Medium | gates | 门禁结果不累积，用户必须逐个修复后重新运行 |
| 7 | Medium | gates | config.json 损坏时静默返回空 dict，无诊断信息 |
| 8 | Medium | finalize | `git_has_uncommitted_changes` 不检测 untracked 文件，新建但未 `git add` 的 change_log 会被误判 |
| 9 | Medium | finalize | config.json 无原子写入，写入中途失败（磁盘满）会导致文件损坏 |
| 10 | Medium | finalize | amend 失败后 config.json 与 git commit 状态不一致，无测试覆盖 |
| 11 | Medium | init | 二次运行静默忽略新 `--name`/`--prefix` 参数，无警告 |
| 12 | Medium | init | 模板加载前无预检，目录已创建后才报错，留下空目录 |
| 13 | Medium | init | 无跨文件一致性校验，生成后不验证各文件间的 ID 是否一致 |
| 14 | Medium | prd_arch_validator | `_collect_related_reqs` 不校验 `related_requirements` 类型，字符串会被拆为单字符集合 |
| 15 | Medium | prd_arch_validator | REQ ID 无大小写/空白归一化，`"req-vt-001"` vs `"REQ-VT-001"` 被视为不同 |
| 16 | Medium | prd_arch_validator | PRD 解析失败时静默跳过（exit_code=0），映射校验被绕过 |
| 17 | Medium | gates | Gate 1c 对异常 constraints 结构无防御，空结构导致所有 MUST 需求被误报为未覆盖 |
| 18 | Low | init | 非 git 目录下 hook 安装静默跳过，无警告 |
| 19 | Low | init | `render_template` 中 prefix 含 "VT" 时可能双重替换 |
| 20 | Low | finalize | `constraints_path` 硬编码，忽略 config 中的路径配置 |
| 21 | Low | finalize | 映射校验失败与 change_log 缺失的错误不聚合，用户需多次修复 |
| 22 | Low | gates | `--gates-only` 硬编码 exit 0，丢失警告状态 |

---

## 二、按模块分析

### 2.1 `vt init` — 初始化

**问题 11：二次运行静默忽略参数**

`init.py:56-66`，config.json 存在时从已有文件读取值，忽略 CLI 传入的 `--name`/`--prefix`，仅打印 "Skipped existing file"。用户无法知道新参数被丢弃。

**问题 12：模板预检缺失**

`init.py:46-51`，目录已在 lines 32-36 创建，之后才加载模板。模板缺失时留下空目录。

**问题 13：无跨文件一致性校验**

生成后不验证 config.json 中的 `project_prefix` 是否与各模板文件中的 ID 前缀一致。`render_template`（line 73-82）的 `-VT-` 替换逻辑若 prefix 含 "VT" 可能双重替换。

**问题 18：非 git 目录无警告**

`init.py:120-130`，`.git/hooks` 不存在时 hook 安装静默跳过，用户收到成功消息但 hook 未安装。

### 2.2 `vt finalize` — 基线锁定

**问题 8：untracked 文件检测盲区**

`finalize.py:66` 调用 `git_has_uncommitted_changes()`，该函数检查 `git diff` 和 `git diff --cached`，但不检查 untracked 文件。用户新建 `architecture_change_log.md` 但未 `git add` 时，校验误判为"未更新"。

**问题 9：config.json 非原子写入**

`finalize.py:176-177, 229-230` 直接 `open("w")` 写入。中途失败（磁盘满、权限）会留下损坏文件，下次运行 JSON 解析失败。

**问题 10：amend 失败状态不一致**

`finalize.py:196-203, 251-258`，commit → rev-parse → 写 config → amend 的流程中，若 amend 失败：
- config.json 磁盘文件已写入 `finalize_git_commit`
- git commit 中不包含该值
- 工作目录 dirty，无测试覆盖此路径

**问题 20：constraints_path 硬编码**

`finalize.py:81` 硬编码 `docs/architecture_constraints.json`，忽略 config.json 中的 `paths.architecture_constraints` 配置。

**问题 21：错误不聚合**

映射校验（line 128）失败后直接返回，用户看不到 change_log 缺失（line 162）的错误。需多次修复-重跑循环。

### 2.3 `prd_arch_validator` — 映射校验

**问题 1：unclear 优先级静默跳过**

`prd_arch_validator.py:91,95`，`priority == "unclear"` 的需求不属于 must 也不属于 should，完全从覆盖率统计中消失。PRD parser 在优先级无法解析时回退为 "unclear"（`prd_parser.py:291,336`），这些需求本应保守处理。

**问题 2：死链检查与覆盖率检查作用域不对称**

- 死链检查（line 76）：`_collect_related_reqs` 递归遍历整个 constraints 树
- 覆盖率检查（line 83-88）：仅扫描顶层 list 段的直接子项

结果：嵌套结构中的 `related_requirements` 会被死链检查发现，但不计入覆盖率。同一需求可同时"非死链"且"未覆盖"。

**问题 3：仅 2/11 类规则计入覆盖率**

实际 constraints 文件中，仅 `module_boundaries` 和 `data_flow_rules` 有 `related_requirements`。`architecture_principles`、`dependency_rules`、`security_rules` 等 9 类规则的引用不计入覆盖。需求的架构支撑定义过于狭窄。

**问题 14：`related_requirements` 类型无防御**

`_collect_related_reqs`（line 39）对 `data["related_requirements"]` 直接调用 `.update()`。若值为字符串（非 list），会被拆为单字符集合。

**问题 15：REQ ID 无归一化**

死链检查（line 79）直接做集合差，无 `.strip()` 或 `.lower()`。`" REQ-VT-001 "` 和 `"req-vt-001"` 均被误判为死链。

**问题 16：PRD 解析失败静默跳过**

`validate_prd_architecture_mapping_from_path`（line 137-144）捕获异常后返回 `exit_code=0`，损坏的 PRD 不阻断 finalize。

### 2.4 门禁链路（gates + pipeline）

**问题 4：auto_generate 与 Gate 2 时序/数据源双重错配**

这是最严重的架构缺陷：

```
pipeline.py:283-287  →  _run_integrity_gates()  →  Gate 2 读 git index
pipeline.py:290-291  →  _auto_generate_claim_from_staged()  →  写文件系统
```

- 时序错配：auto_generate 在 Gate 2 之后执行
- 数据源错配：GhostCodeReconciler 读 `git show :claims_rel`（git index），auto_generate 写文件系统

结果：自动生成的 claims 永远无法被 Gate 2 看到。用户 stage 了代码但没有 claims 时，Gate 2 必然拦截，auto_generate 的缓解机制完全失效。

**问题 5：Gate 1 短路跳过 Gate 1b**

`gates.py:164-165`，Gate 1 失败直接 return，Gate 1b（PRD 漂移警告）被跳过。Gate 1b 设计为"始终运行"（line 167 注释），但短路逻辑使其无法在 Gate 1 失败时执行。

**问题 6：门禁结果不累积**

`_run_integrity_gates`（lines 163-177）使用"首个失败优先"策略。映射校验失败时，幽灵代码检测被跳过。独立问题应累积报告。

**问题 7：config.json 损坏静默处理**

`RawInputLoader._load_config()`（raw_input_loader.py:63）捕获 JSON 异常返回 `{}`，无诊断信息。Gate 1 因 `stored_hash` 为 None 而静默通过。

**问题 17：Gate 1c 对异常结构无防御**

`validate_prd_architecture_mapping`（line 84）遍历 constraints 的顶层 list 段。若 constraints 结构异常（无 list 段），`covered_reqs` 为空，所有 MUST 需求被误报为未覆盖。

---

## 三、架构层面的系统性问题

### 3.1 错误处理哲学不一致

| 模块 | 策略 | 问题 |
|------|------|------|
| init | catch-all `except Exception`，print 通用消息 | 丢失错误上下文 |
| finalize | catch-all + return 1 | 丢失错误上下文 |
| prd_arch_validator | catch-all + return exit_code=0（静默跳过） | 损坏输入不阻断 |
| gates | 无 catch，依赖上层 | 结构异常直接崩溃或误报 |

四个模块有四种错误处理策略，没有统一的错误处理契约。

### 3.2 数据源不统一

| 数据 | 读取来源 | 问题 |
|------|---------|------|
| claims | Gate 2 从 git index 读 | auto_generate 写文件系统，数据源错配 |
| config | gates 从 RawInputLoader 读 | finalize 直接读文件，路径可能不同 |
| constraints | finalize 硬编码路径 | config 中有 `paths.architecture_constraints` 但被忽略 |

### 3.3 校验覆盖面缺口

| 校验 | 设计阶段 | 开发阶段 |
|------|---------|---------|
| PRD ↔ Architecture 映射 | finalize 时校验 | analyze 时 Gate 1c 校验 |
| Task ↔ AC 映射 | **无校验** | Gate 2 部分覆盖（AC 新鲜度） |
| Task ↔ Architecture 交叉 | **无校验** | **无校验** |
| 优先级完整性 | **无校验**（unclear 被跳过） | **无校验** |

需求的三向一致性（PRD ↔ Architecture ↔ Task）缺少统一的端到端校验。

---

## 四、建议优先级

### P0 — 逻辑缺陷，影响正确性

1. **问题 4**：修复 auto_generate 与 Gate 2 的时序/数据源错配。方案：auto_generate 移至 Gate 2 之前，且生成后写入 git index（或让 GhostCodeReconciler 也读文件系统）
2. **问题 1**：unclear 优先级需求按 must 处理（保守原则）
3. **问题 2+3**：统一死链检查与覆盖率检查的作用域，或明确文档化差异

### P1 — 鲁棒性问题

4. **问题 9**：config.json 原子写入（写临时文件 → rename）
5. **问题 10**：amend 失败后增加回滚或状态修复逻辑
6. **问题 8**：`git_has_uncommitted_changes` 增加 untracked 文件检测
7. **问题 5**：Gate 1b（信息性）与 Gate 1（阻断性）分离执行
8. **问题 7**：config.json 损坏时打印警告而非静默跳过
9. **问题 14+15**：`_collect_related_reqs` 增加类型检查和 ID 归一化

### P2 — 体验优化

10. **问题 6**：门禁结果累积，一次性报告所有问题
11. **问题 11**：init 二次运行时警告参数被忽略
12. **问题 21**：finalize 错误聚合
13. **问题 16**：PRD 解析失败时 exit_code 改为非零
