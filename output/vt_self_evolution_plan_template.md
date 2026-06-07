# VT 自我进化与演进计划

## 一、 概述 (Overview)
> [!NOTE]
> 本章节面向人类（PM）。用不超过 150 字扼要概述本轮自省的整体质量评估，以及下一轮演进的核心业务目标。

---

## 二、 诊断与反思 (Diagnostics & Reflections)
<!-- 以下内容面向 Agent，采用结构化 Key-Value 格式，便于 LLM 精确提取 -->

- **Reflect ID**: EVO-REF-001
  - **Violation Principle**: [1-8 自省原则编号]
  - **Diagnosis**: [偏差或缺陷的具体物理表现描述]
  - **Root Cause**: [产生该问题的物理根因，非表面短路原因]
  - **Affected Scope**: [受影响的文件路径或类名]

- **Reflect ID**: EVO-REF-002
  - **Violation Principle**: ...

---

## 三、 原子化动作指令 (Atomic Action Tasks)
<!-- 以下内容面向 Subagents，采用标准任务清单与条件标记，可直接被解析为任务队列 -->

- [ ] **Task ID**: EVO-TASK-001
  - **Action**: [MODIFY | NEW | DELETE]
  - **Target File**: [文件相对路径，如 src/vibe_tracing/cli.py]
  - **Instruction**: [原子化物理修改指令，必须逻辑无歧义，排除模糊叙述]
  - **AC (Acceptance Criteria)**: [精确的物理校验通过条件，如“通过单元测试 X”或“Schema 校验无错”]
  - **Subagent**: [分配的子代理角色，如 "research" 或 "self"]

- [ ] **Task ID**: EVO-TASK-002
  - **Action**: ...