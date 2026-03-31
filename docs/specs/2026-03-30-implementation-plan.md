# Last Mile — 差距分析与改进方向

## Pre-Mortem 核心发现

### 三个保证失败的条件（全部当前存在）
1. Agent 可以完全绕过 Last Mile 协议直接工作
2. 没有任何机制强制链式流转的顺序
3. 知识库冷启动没有解决方案

### 根因
Last Mile 的工作流协议是"建议"而不是"强制"。Paperclip 心跳系统不知道 Last Mile 的存在——它只负责唤醒 Agent，不负责确保 Agent 按流水线协议工作。

---

## 框架研究结论

调研了 40+ 个开源框架后，关键发现：

### 核心洞察：需要"持久执行引擎"而不是"更好的 AI 框架"

AI 框架（CrewAI、LangGraph）让 Agent 更聪明，但不能**强制**它们遵守流程。
持久执行引擎（Temporal、Hatchet、Inngest）**从系统层面保证**每一步必须执行、不可跳过。

```
当前架构（失败模式）:
  Paperclip 心跳 → 唤醒 Agent → Agent 自由发挥 → 可能忽略 Last Mile 协议

理想架构:
  持久执行引擎 → 强制步骤1: 读交接 → 强制步骤2: 提计划 → 等人类审批 →
  强制步骤3: 执行 → 强制步骤4: 写报告 → 等人类评分 →
  强制步骤5: 写下游交接 → 触发下一阶段
```

### 最佳候选方案

| 方案 | 核心优势 | 适合度 | 风险 |
|------|---------|--------|------|
| **Temporal + Paperclip** | 持久执行、强制步骤、人类审批门控、崩溃恢复 | ★★★★★ | 架构复杂，需要部署 Temporal 集群 |
| **Hatchet + Paperclip** | 类似 Temporal 但更轻量、Postgres 原生、专为 AI 设计 | ★★★★☆ | 较新，社区小 |
| **Inngest + Paperclip** | Serverless 友好、TypeScript 原生、专为 AI 工作流设计 | ★★★★☆ | 托管服务依赖 |
| **LangGraph 独立** | 图结构强制流程、AI 原生、多 Agent 支持 | ★★★☆☆ | Python 生态，需要重写；不如持久执行引擎可靠 |
| **Dify 独立** | 全栈平台、可视化、118k stars、生产就绪 | ★★★☆☆ | 放弃 Paperclip 生态；通用平台不够专注 |

### 推荐方向：Hatchet + Paperclip

**为什么是 Hatchet：**
- MIT 开源，Postgres 原生（和 Paperclip 一样）
- 专门为"agentic LLM workflows"设计
- DAG 结构强制步骤顺序
- 内置人类审批门控
- TypeScript SDK（和 Paperclip 技术栈一致）
- 比 Temporal 轻量，不需要额外集群
- YC W24，活跃开发

**架构设想：**
```
Hatchet (工作流引擎，强制步骤)
  ├── Step 1: 总控分析 → 调用 Paperclip API 唤醒总控 Agent
  │   └── 必须产出: plan 文档 + 阶段拆解
  ├── Step 2: 人类审批 → Hatchet 暂停，等人类确认
  ├── Step 3: 阶段1执行 → 调用 Paperclip API 唤醒阶段 Agent
  │   ├── 子步骤 3a: Agent 读交接（强制）
  │   ├── 子步骤 3b: Agent 提计划（强制）
  │   ├── 子步骤 3c: 人类审批计划
  │   ├── 子步骤 3d: Agent 执行工作
  │   ├── 子步骤 3e: Agent 提报告（强制）
  │   └── 子步骤 3f: 人类评分
  ├── Step 4: 预算结算 → 根据评分计算奖惩
  ├── Step 5: 阶段2执行 → 同上
  ├── ...
  ├── Step N: 验收 → 多视角验收 Agent
  └── Step N+1: 知识提取 → 自动沉淀经验

Paperclip (Agent 执行层)
  ├── Agent 管理、适配器、心跳
  ├── 工作区隔离
  ├── 会话管理
  └── 成本追踪

Last Mile (业务逻辑层)
  ├── 流水线模板定义
  ├── 预算激励规则
  ├── 知识资产管理
  └── 满意度评分系统
```

**这个架构解决了所有 pre-mortem 发现的问题：**
- ✅ 协议不可绕过 — Hatchet 强制每一步必须执行
- ✅ 链式流转有保障 — DAG 结构保证顺序
- ✅ 人类审批是系统级门控 — 不是 Agent 自觉
- ✅ 预算结算自动化 — 在工作流步骤中强制执行
- ✅ 知识提取自动化 — 作为工作流的最后一步

---

## 下一步行动

### 重点候选框架深度对比

| 维度 | Symphony | DeerFlow 2.0 | Clawith | Hatchet | Temporal |
|------|----------|-------------|---------|---------|----------|
| **工作流强制** | 无（Agent 自由执行） | 是（LangGraph 图结构） | 部分（Hook 约束+Agent 自治） | 是（DAG 强制步骤） | 是（持久执行强制） |
| **链式流转** | 无（单 Agent 单任务） | 可扩展（图结构支持） | 可扩展（委派机制） | 原生支持 | 原生支持 |
| **多 Agent 协作** | 无（并行独立任务） | 是（5 Agent 层级协作） | 是（组织架构+委派） | 需自建 | 需自建 |
| **人类审批门控** | 仅 PR 审查 | 是（执行中暂停审批） | 是（消息反馈） | 是（原生暂停等待） | 是（Signal 机制） |
| **知识持久化** | 无（每次从零开始） | 是（文件系统+检查点） | 是（SOUL/MEMORY 文件） | 需自建 | 需自建 |
| **自进化** | 无 | 部分（渐进技能加载） | 是（MorphAgent 三指标优化） | 无 | 无 |
| **预算激励** | 无 | 无 | 部分（Token 预算感知研究） | 需自建 | 需自建 |
| **技术栈** | Elixir | Python (LangGraph) | TypeScript (OpenClaw) | Go+TypeScript | Go+多语言 |
| **成熟度** | 早期（2026.3） | 中等（2.0 版本） | 中等（活跃社区） | 中等（YC W24） | 成熟（Netflix 级） |
| **软件开发专注** | 是（编码专用） | 否（研究自动化） | 否（通用 Agent） | 否（通用工作流） | 否（通用工作流） |

### 关键发现

**Symphony** — 编码执行能力强（隔离工作区、CI 反馈循环、PR 交付），但缺少 Last Mile 需要的一切灵魂（链式流转、知识持久、人类审批、预算激励）。适合做执行层，不适合做编排层。

**DeerFlow 2.0** — LangGraph 图结构能强制工作流步骤，5 Agent 层级协作模式接近 Last Mile 的链式流转，有执行中人类审批，有知识持久化。但专注研究自动化而非软件开发，需要大量定制。

**Clawith** — 自进化机制（MorphAgent）是所有框架中最接近 Last Mile "越用越好"愿景的。触发器架构（Cron/Hook/Webhook）提供了灵活的事件驱动能力。组织架构感知和委派机制接近链式流转。但工作流不是强制的——Agent 有很大自治权，可能绕过协议。

**Hatchet/Temporal** — 工作流强制性最强，但没有 AI 能力，需要自建所有 Agent 逻辑。

### 综合推荐：混合架构

没有一个框架能单独满足所有需求。最佳方案是混合：

```
层级 1: 工作流引擎（强制协议）
  选项 A: Hatchet — 轻量、Postgres 原生、TypeScript
  选项 B: DeerFlow 2.0 的 LangGraph 层 — 图结构强制、AI 原生

层级 2: Agent 自治与进化（灵魂）
  借鉴 Clawith: MorphAgent 自进化、SOUL/MEMORY 持久化、触发器架构
  借鉴 DeerFlow: 层级协作、执行中审批、沙箱执行

层级 3: 编码执行（干活）
  选项 A: Paperclip 适配器 — 已有 7 种模型适配器、心跳、工作区隔离
  选项 B: Symphony 执行模式 — 隔离工作区、CI 反馈、PR 交付

层级 4: Last Mile 业务逻辑（差异化）
  链式责任流转、预算激励、满意度评分、知识自进化
```

### 最具可行性的两条路

**路线 A: DeerFlow 2.0 二开 + Paperclip 执行**
- 用 DeerFlow 的 LangGraph 图结构做工作流引擎（强制步骤）
- 用 DeerFlow 的 Agent 层级协作模式做链式流转
- 借鉴 Clawith 的 MorphAgent 做自进化
- 用 Paperclip 做实际的编码 Agent 执行
- 在 DeerFlow 上层加 Last Mile 的预算激励和满意度评分
- 优势：AI 原生、图结构强制、有执行中审批
- 风险：Python 生态，和 Paperclip (TypeScript) 集成需要跨语言

**路线 B: Hatchet + Clawith 模式 + Paperclip 执行**
- 用 Hatchet 做工作流引擎（DAG 强制步骤、人类审批门控）
- 借鉴 Clawith 的自进化和触发器模式
- 用 Paperclip 做 Agent 执行
- 全 TypeScript 技术栈
- 优势：技术栈统一、工作流强制性最强
- 风险：需要自建更多 AI 逻辑

### Phase 1: 验证可行性
- 分别跑通 DeerFlow 2.0 和 Hatchet 的最小 demo
- 验证与 Paperclip API 的集成
- 对比开发体验和强制性
- 选定最终路线
