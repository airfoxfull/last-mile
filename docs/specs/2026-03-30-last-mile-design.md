# Last Mile — 设计文档

> AI-Native 软件开发流水线 PoC

## 1. 产品定位

"最后一百米"——让任何开发团队都能轻松转型 AI-native。不做大模型，做标准化落地。

## 2. 核心概念

### 2.1 流水线（Pipeline）
一个可复用的阶段链模板。定义需求从消费端到交付的完整路径。

### 2.2 阶段（Stage）
流水线中的一个环节（前端、后端、测试、安全、运维等）。每个阶段有：
- 负责的 Agent（可配置模型/适配器）
- 负责的人类（满意度评价者）
- 默认验收标准模板

### 2.3 运行（Run）
一次需求通过流水线的完整执行。包含：
- 源需求
- 总控拆解结果
- 各阶段执行记录
- 人类满意度评分
- 验收结果
- 提取的知识

### 2.4 责任链
上游阶段为下游制定目标 → 下游执行 → 上游验收下游产出。
每一环为上游负责，不是为自己的验收负责。

### 2.5 满意度评分
人类对每个阶段的 Plan / 过程 / 结果 打 1-5 分 + 方向反馈（确认/纠偏）。

### 2.6 知识资产
从每次运行中自动提取的可复用模式、反模式、决策记录。

## 3. 技术架构

```
┌─────────────────────────────────────────────┐
│                  Web UI (React)              │
│  流水线管理 │ 运行看板 │ 评分面板 │ 知识库   │
└──────────────────┬──────────────────────────┘
                   │ REST + WebSocket
┌──────────────────┴──────────────────────────┐
│              API Server (Express)            │
│  pipelines │ runs │ stages │ knowledge       │
├─────────────────────────────────────────────┤
│           Pipeline Orchestrator              │
│  总控调度 │ 阶段流转 │ 验收编排 │ 知识提取   │
├─────────────────────────────────────────────┤
│           Agent Executor (模拟层)            │
│  PoC 阶段: 手动/半自动执行                   │
│  未来: 对接 Paperclip adapter / Symphony     │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────┴──────────────────────────┐
│              SQLite (本地存储)                │
└─────────────────────────────────────────────┘
```

### 3.1 技术栈

| 层 | 技术 | 理由 |
|----|------|------|
| 前端 | React 19 + Vite + TailwindCSS | 与 Paperclip 一致，快速开发 |
| 后端 | Express 5 + TypeScript | 与 Paperclip 一致 |
| 数据库 | SQLite (better-sqlite3) | PoC 轻量，零配置 |
| 实时 | WebSocket (ws) | 阶段状态实时推送 |
| 构建 | pnpm monorepo | 与 Paperclip 一致 |

### 3.2 项目结构

```
last-mile/
├── package.json              # monorepo root
├── pnpm-workspace.yaml
├── tsconfig.json
├── server/
│   ├── package.json
│   ├── src/
│   │   ├── index.ts          # 入口
│   │   ├── db/
│   │   │   ├── schema.ts     # SQLite schema
│   │   │   └── client.ts     # DB 连接
│   │   ├── services/
│   │   │   ├── pipelines.ts  # 流水线 CRUD
│   │   │   ├── runs.ts       # 运行管理
│   │   │   ├── orchestrator.ts # 编排引擎
│   │   │   ├── scoring.ts    # 满意度评分
│   │   │   └── knowledge.ts  # 知识资产
│   │   ├── routes/
│   │   │   ├── pipelines.ts
│   │   │   ├── runs.ts
│   │   │   ├── scoring.ts
│   │   │   └── knowledge.ts
│   │   └── ws/
│   │       └── events.ts     # WebSocket 事件
│   └── tsconfig.json
├── ui/
│   ├── package.json
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx      # 全局看板
│   │   │   ├── PipelineList.tsx   # 流水线列表
│   │   │   ├── PipelineEditor.tsx # 流水线编辑
│   │   │   ├── RunView.tsx        # 运行详情
│   │   │   ├── ScoringPanel.tsx   # 评分面板
│   │   │   └── KnowledgeBase.tsx  # 知识库
│   │   ├── components/
│   │   │   ├── StageCard.tsx      # 阶段卡片
│   │   │   ├── StagePipeline.tsx  # 阶段链可视化
│   │   │   ├── ScoreForm.tsx      # 评分表单
│   │   │   └── RunTimeline.tsx    # 运行时间线
│   │   └── lib/
│   │       ├── api.ts             # API 客户端
│   │       └── ws.ts              # WebSocket 客户端
│   ├── index.html
│   ├── vite.config.ts
│   └── tsconfig.json
└── shared/
    ├── package.json
    └── src/
        ├── types.ts           # 共享类型
        └── constants.ts       # 共享常量
```

## 4. 数据模型

### pipelines
```sql
CREATE TABLE pipelines (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  stage_order TEXT NOT NULL,        -- JSON: ["frontend","backend","testing"]
  consumer_type TEXT,               -- "end_user" | "internal" | "api_consumer"
  master_agent_config TEXT,         -- JSON: agent 配置
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
```

### pipeline_stages
```sql
CREATE TABLE pipeline_stages (
  id TEXT PRIMARY KEY,
  pipeline_id TEXT NOT NULL REFERENCES pipelines(id),
  name TEXT NOT NULL,
  role TEXT NOT NULL,               -- "frontend" | "backend" | "testing" | ...
  stage_index INTEGER NOT NULL,
  agent_config TEXT,                -- JSON: 该阶段 agent 配置
  human_owner TEXT,                 -- 负责评分的人
  acceptance_template TEXT,         -- 默认验收标准模板
  created_at TEXT DEFAULT (datetime('now'))
);
```

### pipeline_runs
```sql
CREATE TABLE pipeline_runs (
  id TEXT PRIMARY KEY,
  pipeline_id TEXT NOT NULL REFERENCES pipelines(id),
  requirement TEXT NOT NULL,        -- 原始需求描述
  requirement_analysis TEXT,        -- JSON: 总控分析结果
  current_stage_index INTEGER DEFAULT 0,
  global_acceptance_criteria TEXT,  -- JSON: 全局验收标准
  status TEXT DEFAULT 'pending',    -- pending|running|review|accepted|rejected|cancelled
  started_at TEXT,
  completed_at TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
```

### stage_runs
```sql
CREATE TABLE stage_runs (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES pipeline_runs(id),
  stage_id TEXT NOT NULL REFERENCES pipeline_stages(id),
  stage_index INTEGER NOT NULL,
  upstream_goals TEXT,              -- JSON: 上游制定的目标
  downstream_goals TEXT,            -- JSON: 为下游制定的目标
  work_output TEXT,                 -- 工作产出描述
  status TEXT DEFAULT 'pending',    -- pending|running|review|passed|failed|skipped
  plan_satisfaction INTEGER,        -- 1-5
  process_satisfaction INTEGER,     -- 1-5
  result_satisfaction INTEGER,      -- 1-5
  direction_feedback TEXT,          -- JSON: {type, detail}
  started_at TEXT,
  completed_at TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
```

### acceptance_reviews
```sql
CREATE TABLE acceptance_reviews (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES pipeline_runs(id),
  perspective TEXT NOT NULL,        -- "functional"|"consumer"|"technical"|"consistency"
  result TEXT NOT NULL,             -- "pass"|"fail"|"conditional"
  findings TEXT,                    -- JSON: 发现的问题
  created_at TEXT DEFAULT (datetime('now'))
);
```

### knowledge_assets
```sql
CREATE TABLE knowledge_assets (
  id TEXT PRIMARY KEY,
  category TEXT NOT NULL,           -- "pattern"|"anti_pattern"|"decision"|"lesson"
  scope TEXT DEFAULT 'project',     -- "project"|"stage"|"company"
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  source_run_id TEXT REFERENCES pipeline_runs(id),
  confidence REAL DEFAULT 0.5,
  usage_count INTEGER DEFAULT 0,
  tags TEXT,                        -- JSON array
  status TEXT DEFAULT 'active',
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);
```

## 5. 核心流程

### 5.1 需求提交
```
用户在 UI 中输入需求描述
  → 选择流水线模板
  → 创建 pipeline_run
  → 状态: pending
```

### 5.2 总控分析（PoC: 手动触发）
```
点击"开始分析"
  → 总控 Agent 分析需求:
    - 消费端是谁
    - 各阶段目标
    - 全局验收标准
  → 结果写入 requirement_analysis
  → 为每个阶段创建 stage_run + upstream_goals
  → 状态: running
```

### 5.3 阶段执行
```
当前阶段 Agent 执行:
  → 读取 upstream_goals
  → 执行工作
  → 生成 work_output
  → 为下游生成 downstream_goals
  → 状态: review

人类评分:
  → 查看 plan / 过程 / 结果
  → 打分 1-5 + 方向反馈
  → 满意度 ≥ 3: 推进下一阶段
  → 满意度 < 3: 返回修正
```

### 5.4 多视角验收
```
最后阶段完成后:
  → 并行启动 4 个验收视角
  → 汇总结果
  → 全部通过: accepted
  → 有失败: rejected + 具体问题
```

### 5.5 知识提取
```
运行完成后:
  → 分析满意度数据
  → 提取成功模式 / 反模式
  → 写入 knowledge_assets
  → 未来运行可引用
```

## 6. PoC 范围（MVP）

### 包含
- [x] 流水线模板 CRUD
- [x] 需求提交和运行创建
- [x] 阶段链可视化（看板式）
- [x] 手动推进阶段（模拟 agent 执行）
- [x] 满意度评分表单
- [x] 多视角验收面板（手动填写）
- [x] 知识资产 CRUD
- [x] 全局仪表盘（运行状态、满意度趋势）

### 不包含（未来）
- [ ] 真实 Agent 执行（对接 Paperclip/Symphony）
- [ ] 自动知识提取（需要 LLM）
- [ ] 外部需求源接入（GitHub/Linear/飞书）
- [ ] 多公司/多团队隔离
- [ ] 预算和成本追踪
- [ ] 用户认证

## 7. 成功标准

1. 能创建流水线模板并定义阶段链
2. 能提交需求并看到阶段链可视化
3. 能手动推进阶段并提交满意度评分
4. 能进行多视角验收
5. 能记录和浏览知识资产
6. 仪表盘展示运行状态和满意度数据
