# 设计阶段逻辑重设计

基于代码逻辑审查（`design_phase_code_logic_review.md`）发现的 22 项问题，从第一性原则重新设计整个设计阶段逻辑。

---

## 一、设计目标

**唯一不变量：设计基线的内部一致性。**

所有校验的目的是确保锁定的基线中，PRD、Architecture、Task 三者之间不存在矛盾。当前问题的根因：一致性检查被拆成多个独立模块，各有不同的作用域、数据源和错误策略。

---

## 二、重设计逻辑

### 2.1 设计阶段流程

```
vt init
  ├─ 预检模板文件存在性（失败则中止，不留空目录）
  ├─ 创建目录和文件（幂等，--force 可重生成）
  ├─ 安装 pre-commit hook（非 git 时显式警告）
  └─ 校验生成文件间的一致性（prefix/ID 一致性）

写文档（PRD / Architecture Constraints / Task List）

vt accept（可选，独立于 finalize）
  ├─ 写入 .vibetracing/human_decisions.json（不修改 constraints）
  ├─ 仅接受 verification_method == "manual" 的规则
  └─ machine 规则拒绝并提示"需通过程序验证"

vt finalize
  ├─ 1. 加载三份文档 + 结构校验
  ├─ 2. 统一交叉校验（单一函数，单一作用域）
  │     ├─ 死链：constraints 引用的 REQ 必须在 PRD 中存在
  │     ├─ 覆盖：所有 REQ（非仅 MUST）检查架构支撑
  │     │     └─ 递归扫描所有含 related_requirements 的节点（非仅顶层 list 段）
  │     ├─ Task ↔ AC：task 引用的 AC 必须在 PRD 中存在
  │     └─ 优先级：不允许 "unclear"（解析失败报错，不静默跳过）
  ├─ 3. 变更日志校验（仅 re-finalize）
  │     ├─ 结构化 JSON 格式（非自由 Markdown）
  │     ├─ _find_differences() 自动填充变更条目
  │     └─ 每条变更必须有 rationale（人类补充）
  └─ 4. 锁定
        ├─ 原子写入 config.json（写临时文件 → rename）
        ├─ 计算 SHA-256 hash（prd.md + architecture_constraints.json）
        └─ Git commit（先写 hash 到 config 再 commit，不用 amend）
```

### 2.2 开发阶段流程

```
vt analyze [--pre-commit]
  ├─ 1. 加载 config（损坏时报错诊断，不静默返回空 dict）
  ├─ 2. 漂移检测
  │     ├─ 比较当前 hash 与基线 hash
  │     ├─ 报告所有漂移文件（不短路，不因 constraints 漂移跳过 PRD 漂移）
  │     └─ 漂移为信息性输出，不阻断后续校验
  ├─ 3. 统一交叉校验（复用 finalize 同一函数 validate_consistency()）
  │     ├─ 死链 + 覆盖 + Task↔AC + 优先级
  │     └─ 累积所有错误，一次性报告
  ├─ 4. 幽灵代码检测（仅 pre-commit）
  │     ├─ auto_generate_claim 在检测之前执行
  │     └─ GhostCodeReconciler 读文件系统（非 git index）
  └─ 5. 累积所有门禁结果，一次性报告（不短路）
```

---

## 三、关键设计变更

| 变更项 | 当前设计 | 重设计 |
|--------|---------|--------|
| 校验函数 | finalize 和 analyze 各自实现 | 单一 `validate_consistency()` 复用 |
| 覆盖率作用域 | 仅顶层 list 段（2/11 类规则） | 递归扫描所有含 `related_requirements` 的节点 |
| 优先级处理 | unclear 静默跳过 | unclear 报错，不允许存在 |
| Gate 执行策略 | 短路，信息性与阻断性混合 | 分离：漂移检测（信息性）不短路，阻断性校验累积报告 |
| config 写入 | 直接 `open("w")` | tmp + rename 原子写入 |
| commit hash 存储 | commit → amend（两步，失败状态不一致） | 先写 hash 到 config → 一次性 commit |
| auto_generate 时序 | Gate 2 之后执行，写文件系统 | Gate 2 之前执行，写文件系统 |
| GhostCodeReconciler 数据源 | git index | 文件系统（与 auto_generate 一致） |
| change log 校验 | git dirty 检查（只看文件是否修改） | 结构化 JSON + 内容校验（每条变更需 rationale） |
| 错误报告 | 首个失败优先 | 累积所有错误一次性报告 |
| vt accept 存储 | 修改 architecture_constraints.json | 写入 human_decisions.json |
| vt accept 范围 | 接受所有规则 | 仅接受 verification_method == "manual" |

---

## 四、对位检验：22 项问题消除情况

| # | 严重度 | 问题 | 状态 | 消除方式 |
|---|--------|------|------|---------|
| 1 | High | unclear 优先级静默跳过 | **消除** | 统一校验中不允许 unclear |
| 2 | High | 死链/覆盖率作用域不对称 | **消除** | 同一函数、同一作用域、递归扫描 |
| 3 | High | 仅 2/11 类规则计入覆盖 | **消除** | 统一扫描所有含 related_requirements 的规则 |
| 4 | High | auto_generate 时序/数据源错配 | **消除** | auto_generate 移至检测前，GhostCodeReconciler 读文件系统 |
| 5 | Medium | Gate 1 短路跳过信息性警告 | **消除** | 漂移检测独立于阻断性校验，不短路 |
| 6 | Medium | 门禁结果不累积 | **消除** | 累积所有错误一次性报告 |
| 7 | Medium | config 损坏静默跳过 | **消除** | 加载时诊断，损坏报错 |
| 8 | Medium | untracked 文件检测盲区 | **保留** | 结构化 change log 缓解（内容校验替代 git dirty 检查），但 git 层面 untracked 检测仍有盲区 |
| 9 | Medium | config 非原子写入 | **消除** | tmp + rename 原子写入 |
| 10 | Medium | amend 失败状态不一致 | **消除** | 先写 hash 再 commit，不用 amend |
| 11 | Medium | init 静默忽略参数 | **消除** | 冲突时警告 |
| 12 | Medium | 模板预检缺失 | **消除** | 加载前预检 |
| 13 | Medium | 无跨文件一致性校验 | **消除** | init 结束后校验 |
| 14 | Medium | related_requirements 类型无防御 | **消除** | 统一校验中增加类型检查 |
| 15 | Medium | REQ ID 无归一化 | **消除** | 统一校验中归一化（strip + lower） |
| 16 | Medium | PRD 解析失败静默跳过 | **消除** | exit_code != 0 |
| 17 | Medium | 异常 constraints 结构误报 | **消除** | 结构校验前置 |
| 18 | Low | 非 git 无警告 | **消除** | 显式警告 |
| 19 | Low | prefix 双重替换 | **保留** | init 模板渲染逻辑问题，与设计阶段流程无关，需单独修复 |
| 20 | Low | constraints_path 硬编码 | **消除** | 从 config 读取路径 |
| 21 | Low | 错误不聚合 | **消除** | 累积报告 |
| 22 | Low | --gates-only exit 0 | **消除** | 保留警告状态 |

**结果：20/22 消除，2/20 保留**（#8 untracked 检测、#19 prefix 替换），保留项均有缓解措施或属独立问题。

---

## 五、待讨论细节

> 此处记录后续需要讨论的细节，讨论后补充结论。

### 5.1 覆盖率的"覆盖"定义

当前仅 `module_boundaries` 和 `data_flow_rules` 有 `related_requirements`。重设计改为递归扫描所有含 `related_requirements` 的节点。需确认：
- 其他规则类型（如 `security_rules`、`quality_gates`）是否应该添加 `related_requirements` 字段？
- 还是说"覆盖"的定义应该扩展为：任何规则类型中引用了该 REQ 即算覆盖？

### 5.2 unclear 优先级的处理方式

当前 PRD parser 在优先级无法解析时回退为 "unclear"。重设计要求不允许 unclear。需确认：
- 是在校验层报错（要求用户修正 PRD）？
- 还是在 parser 层就拒绝（PRD 解析失败）？

### 5.3 统一校验函数的调用时机

`validate_consistency()` 在 finalize 和 analyze 中复用。需确认：
- analyze 中是否每次无条件调用？还是仅在漂移检测到变化时调用？
- 如果无条件调用，analyze 的性能是否可接受？

### 5.4 结构化 change log 的格式

需确认：
- JSON 侧车文件（`architecture_change_log.json`）还是嵌入现有 Markdown？
- 是否保留 Markdown 版本供人类阅读？如何保持两者同步？

### 5.5 GhostCodeReconciler 数据源切换

从 git index 改为文件系统。需确认：
- pre-commit 场景下，staged 但未 commit 的代码如何处理？
- 是否需要同时读 git index 和文件系统做合并？

### 5.6 vt finalize 的 commit hash 存储

当前用 amend 流程。重设计改为先写 hash 再 commit。需确认：
- commit 的 hash 值在 commit 前未知，如何写入 config？
- 方案 A：写 config → commit → 再次读取 HEAD hash → 再次写 config → 再次 commit（两次 commit）
- 方案 B：写 config（hash 留空）→ commit → 用 post-commit hook 回填 hash
- 方案 C：接受 config 中的 finalize_git_commit 为"上一次 commit"的 hash（非本次）
