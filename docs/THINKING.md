# Last Mile — 完整思考记录

> 供后续 Agent 或开发者接手时理解项目的来龙去脉

## 项目起源

用户的核心观察：AI 编码能力已经很强（前 90%），但"最后一百米"——让团队真正转型 AI-native——仍然是空白。现状像送外卖送到小区门口就不管了。

用户的愿景：一个需求进来后，自动被总控 Agent 拆解，按消费端由近到远流转（前端→后端→测试→安全），每个环节的 Agent 自主工作，上游验收下游，人类只做满意度评分和方向纠偏。

## 演进路径

### Phase 1: 独立 PoC（E:/last-mile/）
- 独立的 Web 仪表盘（React + Express + SQLite）
- 流水线管理、满意度评分、预算激励、知识库
- 问题：**没有 Agent 执行能力**——只是一个 CRUD 应用

### Phase 2: Paperclip 插件
- 决定做成 Paperclip 插件，复用其 Agent 执行基础设施
- 注册了 8 个 Agent 工具（view-my-budget、read-handoff、submit-plan 等）
- 验证了真实 Agent 执行（汉化任务，人类评分 4/5）
- 问题：**Agent 可以绕过 Last Mile 协议直接工作**

### Phase 3: 框架调研
- 调研 40+ 个开源框架
- 5 个重点框架 demo 对比（Paperclip/Symphony/Clawith/Hatchet/DeerFlow）
- 关键发现：
  - DeerFlow 2.0 已放弃多节点 StateGraph，改为单 Agent 中间件链
  - Symphony 是调度器不是工作流引擎
  - Hatchet 是唯一硬强制方案但 mTLS 本地不可用
  - Clawith 的自进化最强但工作流不强制

### Phase 4: 三道门设计
- 回归 Paperclip 插件方案
- 核心洞察：**运行之内 Agent 自由，运行之间插件控制唤醒实现硬强制**
- 流水线 Agent 关闭定时心跳（intervalSec=0），只接受插件按需唤醒
- 三道门：plan 文档存在 + 人类审批 + report 质量检查

### Phase 5: 实战验证
- 门控连续 3 次正确拦住不合规产出 ✅
- 但 Agent 每次被唤醒都是白纸，不从失败中学习 ❌

## 关键技术决策及原因

### 为什么不用 Hatchet？
Hatchet 的 DAG 是服务端强制的（step2 进程在 step1 完成前不存在），理论上最好。但 hatchet-lite 的 gRPC 强制 mTLS，本地开发需要证书配置，在 Windows 上搞不定。

### 为什么不改 Paperclip 心跳服务？
尝试在心跳服务的 `finalizeAgentStatus` 里加 `logActivity` 调用（让 agent.status_changed 事件路由到插件），但导致服务崩溃。心跳服务 2800 行，改动风险太大。

### 为什么用分步 action 而不是事件驱动？
Paperclip 的心跳服务通过 `publishLiveEvent` 发 WebSocket 事件（给 UI），但不通过 `logActivity` 发插件事件。插件收不到 `agent.status_changed`。改用分步 action：start-pipeline → check-gates → approve-plan → score-result。

### 为什么 action 不能轮询？
插件 action 有 30 秒 RPC 超时。Agent 运行需要 60-300 秒。轮询放在 action 里会超时。

## 当前架构

```
Paperclip 插件 (plugin-last-mile)
├── actions:
│   ├── start-pipeline  — 唤醒 Agent 做规划（快速返回）
│   ├── check-gates     — 检查门控（plan 存在 + 格式正确）
│   ├── approve-plan    — 人类审批计划（>= 3 分通过）
│   └── score-result    — 人类评分结果（>= 3 分通过）
├── tools (Agent 可调用):
│   ├── view-my-budget, view-my-skills, check-rules
│   ├── read-handoff, submit-plan, submit-report, write-handoff
│   └── query-knowledge
└── state (Postgres 持久化):
    ├── agent:{id}/active-pipeline-stage — 阶段状态机
    └── issue:{id}/pipeline-run — 流水线运行状态
```

## 已验证有效的

1. **门控机制** — check-gates 正确检测 plan 文档缺失，自动返工，reworkCount 递增
2. **Agent 真实执行** — claude_local 适配器能自主修改代码（汉化 99 个文件）
3. **插件 action** — 分步调用不超时，状态持久化到 Postgres
4. **Agent 工具** — 8 个工具正确注册，Agent 理论上可调用

## 未解决的核心问题

### 1. Agent 无跨运行记忆（最关键）
Agent 每次被唤醒都是白纸。它不知道：
- 自己被返工了几次
- 上次为什么被打回
- 门控的具体反馈是什么
- 自己的历史表现

**需要**：框架层面的记忆注入——每次唤醒时，自动把历史上下文注入 Agent 的 prompt。不是手动写，是框架机制。

### 2. Agent 不会通过 API 写文档
prompt 里写了 curl 命令，但 Agent 用 Claude Code 的工具而不是 curl。它不知道怎么调用 Paperclip API。

**需要**：让 Agent 使用 Last Mile 插件的工具（lastmile.pipeline:submit-plan）而不是直接 curl。或者在 Agent 的 instructions 文件里教它怎么用。

### 3. Paperclip 事件路由缺失
心跳服务不把 agent.status_changed 路由到插件事件总线。这意味着插件无法自动检测 Agent 运行完成。

**当前方案**：人类手动调用 check-gates。
**理想方案**：Paperclip 核心团队修复事件路由，或者插件用定时 job 轮询。

### 4. The Fool 辩论循环未实现
设计了 Fool Agent 挑战 → 原 Agent 回应 → 收敛 → 人类裁决的机制，但代码里只有占位。需要配置一个 Fool Agent（用不同模型）并实现辩论流程。

### 5. Skill 深度融合只实现了 feature-forge 格式检查
5 个深度融合 Skill 中只有 feature-forge（plan 格式检查）真正写进了代码。code-reviewer、security-reviewer、spec-miner、the-fool 都还是设计。

## Phase 6: LangGraph 替换 Hatchet（2026-03-31）

### 为什么替换？
- Hatchet 的 mTLS 在本地开发搞不定，需要 Docker 跑 hatchet-lite + PostgreSQL
- Paperclip 插件的 30 秒 action 超时限制了轮询
- 没有 checkpoint 机制，Agent 无跨运行记忆

### 为什么选 LangGraph？
- 原生支持循环（返工回边）——其他框架都是 DAG
- `interrupt()` + `Command(resume=...)` 原生 HITL 审批门
- Checkpoint 持久化（SQLite/Postgres）——Agent 记忆问题自然解决
- TypeScript SDK（`@langchain/langgraph`），和 Paperclip 同语言
- 无额外基础设施，直接 Node.js 进程

### 新架构
- LangGraph 做工作流编排（状态图 + 门控 + HITL + 记忆）
- Paperclip 做 Agent 执行后端（适配器 + 心跳 + API）
- LangGraph 通过 Paperclip REST API 唤醒 Agent、读写文档

### 已实现
- 7 节点状态图：plan_agent → check_plan → fool_challenge → human_approval → execute_agent → check_report → human_score
- 3 个返工回边（plan 格式不通过、plan 被拒、report 不通过）
- 2 个 HITL 中断点（human_approval、human_score）
- 记忆注入：每次返工唤醒时自动注入 reworkCount + 失败原因 + 上次 plan 摘要
- The Fool 辩论循环（可选，配置 foolAgentId 启用）
- HTTP 服务器：POST /start、POST /resume、GET /status
- CLI 工具：dev:run 启动、dev:score 审批

## 完整状态机（含未实现的 fool_challenging）

```
planning
  → [Agent 运行完成]
  → [门1: plan 文档存在 + 格式正确?]
    → 不通过 → 返工（自动唤醒，reworkCount++）
    → 通过 ↓
fool_challenging  ← 【未实现，代码里没有这个阶段】
  → [Fool Agent 挑战计划]
  → [原 Agent 回应]
  → awaiting_plan_approval ↓
awaiting_plan_approval
  → [门2: 人类评分 >= 3?]
    → 不通过 → planning（返工）
    → 通过 ↓
executing
  → [Agent 运行完成]
  → [门3: report 文档存在 + 包含质量确认?]
    → 不通过 → 返工
    → 通过 ↓
awaiting_result_score
  → [人类评分 >= 3?]
    → 不通过 → executing（返工）
    → 通过 → done
```

当前代码（events.ts）跳过了 `fool_challenging`，直接从 `planning` 到 `awaiting_plan_approval`。

## Agent 记忆注入的具体方案（已实现 ✅）

LangGraph checkpoint 天然保存完整状态。每次返工唤醒 Agent 时，从状态构建记忆前缀：

```
【历史记录 — 请务必阅读】
- 本任务已返工 ${reworkCount} 次
- 返工原因: ${reworkHistory.join('; ')}
- 上次提交的 plan 摘要: ${planBody.slice(0, 300)}
- 请根据以上反馈改进你的计划

【当前任务】
...
```

实现位置：`src/workflows/pipeline.ts` 的 `planAgent()` 和 `executeAgent()` 函数。

## Agent 不用 curl 的根因

Agent 的 instructions 文件（Paperclip 里每个 Agent 的配置）没有教它 Paperclip API 的认证方式（`$PAPERCLIP_API_KEY` 和 `$PAPERCLIP_API_URL` 这两个环境变量在 Agent 运行环境里是否存在未验证）。Agent 回退到自己熟悉的工具（Claude Code 的 Write/Edit 工具）。

解决方案：
1. 在 Agent instructions 里明确写出 API 调用示例（带真实 URL 格式）
2. 或者让 Agent 使用 Last Mile 插件注册的工具（`lastmile.pipeline:submit-plan`）而不是 curl

## 预算激励模型（设计完成，未实现）

- 规划预算 = 执行预算 × 0.3（宽松，鼓励充分思考）
- 执行预算 = 任务基础预算 × 等级倍数
- 核心奖惩指标：返工次数（不是 token 消耗）
- 多维度加权：返工 40% + 质量 30% + 创新 20% + 效率 10%

## 文件位置

| 内容 | 位置 |
|------|------|
| Paperclip 插件代码 | E:/paperclip/packages/plugins/plugin-last-mile/ |
| 独立 PoC（参考） | E:/last-mile/ |
| GitHub 仓库 | https://github.com/airfoxfull/last-mile |
| 设计文档 | E:/last-mile-repo/docs/specs/ |
| LangGraph 工作流代码 | E:/last-mile-repo/src/workflows/pipeline.ts |
| LangGraph Worker | E:/last-mile-repo/src/worker.ts |
| Paperclip API Client | E:/last-mile-repo/src/paperclip/client.ts |
| 门控函数 | E:/last-mile-repo/src/gates.ts |
| CLI 启动 | E:/last-mile-repo/src/client.ts |
| CLI 评分 | E:/last-mile-repo/src/cli/score.ts |

## 下一步优先级

~~1. 端到端测试 — 连接真实 Paperclip 实例~~
~~2. Agent 工具使用~~
~~3. SQLite → Postgres~~
~~4. 多阶段链式流转~~
~~5. 预算激励实现~~

> 以上优先级已过时。Phase 7 做了底座切换决策。

## Phase 7: 底座切换 — Clawith + LangGraph（2026-04-02）

### 为什么换底座？

经过 Paperclip/Clawith/Symphony/Dify/Kestra/Letta 6 个框架的全面对比，
提炼出 Last Mile 底座的 6 个必备条件：

1. Agent 一等实体（身份/配置/历史/技能/预算）
2. 工作流强制（DAG/图结构，不可跳过）
3. HITL 暂停/恢复（系统级审批门控）
4. 文档/Artifact 管理
5. 跨运行记忆
6. Web UI

没有任何单一框架超过 3/6。但 Clawith 达到 5/6（只缺 DAG 工作流强制）。

### 为什么选 Clawith？

Clawith（"OpenClaw for Teams"）开箱即用：
- soul.md/memory.md/focus.md 持久化 → 解决"Agent 无跨运行记忆"（之前最大的痛点）
- L3 审批门控 → 系统级人类审批
- 6 种触发器（cron/once/interval/poll/on_message/webhook）
- Plaza 知识流 → 经验自动沉淀
- per-agent token 配额 → 预算管控基础
- 飞书/钉钉/企微/Slack/Discord/Teams 集成
- 多租户 RBAC → 50+ 人团队直接用
- 18 页 Web UI → Agent 管理、审批、知识库
- Apache 2.0 许可证

### 为什么不继续 Paperclip？

| 问题 | Paperclip | Clawith |
|------|-----------|---------|
| Agent 记忆 | ❌ 每次白纸 | ✅ memory.md 自动持久化 |
| 事件路由 | ❌ 心跳不路由到插件 | ✅ 6 种触发器 |
| Action 超时 | ❌ 30 秒 | ✅ 无限制 |
| 消息渠道 | ❌ 没有 | ✅ 飞书/钉钉/Slack |
| 审批门控 | ❌ 需手动调 check-gates | ✅ L3 自动阻断 |

### 为什么不选 Dify/Kestra？

- Dify：许可证限制（不能多租户 SaaS），没有 Agent 身份概念，知识库不适合做记忆
- Kestra：没有 AI Agent 概念，"600+ 插件"夸大（核心 ~97），Java 生态

### 为什么不选 Symphony？

Symphony 是调度器/运行器，明确不做工作流引擎、不做 UI、不做 Agent 身份。
它适合做层级 3（编码执行），不适合做底座。

### 新架构

```
LangGraph（工作流引擎，Python）
  ├── DAG：plan → check_gate → fool → approve → execute → check_report → score
  ├── 调 Clawith REST API 唤醒 Agent
  ├── 读写 Agent workspace 文件
  ├── 门控检查（格式验证）
  ├── 请求 Clawith L3 审批 → webhook 回调 → resume
  └── Checkpoint 保存工作流状态

Clawith（Agent 平台）
  ├── Agent 身份（soul.md + memory.md + focus.md）
  ├── L3 审批门控
  ├── 触发器（webhook 接收 LangGraph 事件）
  ├── Plaza 知识流
  ├── 配额管理
  ├── 渠道集成（飞书/钉钉/Slack）
  └── Web UI
```

### 技术栈变化

TypeScript → Python（LangGraph Python SDK 更成熟）
Paperclip REST API → Clawith REST API
CLI 审批 → Clawith Web UI + 飞书/钉钉

### Clawith 风险

- 2.7K stars，项目只有 1 个月大
- 主要贡献者 1 人（QinRui，773/1205 commits）
- Python 技术栈
- API 可能频繁变动

### 落地计划

Phase 0: 搭建 Clawith 本地环境，验证核心 API
Phase 1: 创建 3 个 Agent（Planner/Executor/Fool）
Phase 2: Python LangGraph 工作流（7 节点，调 Clawith API）
Phase 3: 人类审批闭环（Clawith L3 → webhook → LangGraph resume）
Phase 4: 业务逻辑（链式流转、预算激励、满意度评分、知识沉淀）

## 文件位置（更新）

| 内容 | 位置 |
|------|------|
| Paperclip 插件代码（历史） | E:/paperclip/packages/plugins/plugin-last-mile/ |
| TypeScript LangGraph 代码（历史） | E:/last-mile-repo/src/workflows/pipeline.ts |
| GitHub 仓库 | https://github.com/airfoxfull/last-mile |
| 设计文档 | E:/last-mile-repo/docs/specs/ |
| Clawith 源码（待 clone） | E:/clawith/ |
| Python LangGraph 代码（待创建） | E:/last-mile-repo/python/ |
