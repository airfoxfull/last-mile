# 5 框架 Demo 对比结果

## 统一场景：2 阶段流水线（规划→审批→执行）

### 核心发现：只有 Hatchet 能真正"硬强制"

| 框架 | 强制机制 | 强制级别 | 人类审批 | 实现难度 |
|------|---------|---------|---------|---------|
| **Hatchet** | DAG `parents` 数组，服务端调度，step2 的 worker 进程在 step1 完成前根本不会启动 | **硬强制** | `durableTask` + `waitForEvent`，进程挂起等外部事件 | 低（3 个函数） |
| **Paperclip** | Agent instructions 写"先提计划"，插件监听事件控制唤醒时机 | **软强制**（Agent 可忽略 instructions） | 插件事件 + 手动唤醒 | 中 |
| **Clawith** | Autonomy L3 可以逐工具审批，但没有工作流状态机 | **逐操作审批**（不是阶段级强制） | L3 审批门控（per-tool-call） | 高（需要 hack） |
| **DeerFlow 2.0** | 2.0 已放弃多节点 StateGraph，改为单 Agent + 中间件链。没有图级工作流强制 | **无**（中间件只能拦截工具调用） | ClarificationMiddleware 终止运行 | 高（需要外部编排） |
| **Symphony** | 无 DAG/流水线概念，是调度器不是工作流引擎。用 Linear 状态转换做粗粒度门控 | **无**（靠外部任务板状态） | Linear 状态转换（手动） | 高（需要 Elixir + 大量扩展） |

### 详细分析

#### Hatchet ✅ 最佳
```typescript
// 这就是全部代码——3 个函数定义了强制流水线
const plan = workflow.task({ name: 'plan', fn: async (input) => {
  // Agent 生成计划
  return { plan: "..." };
}});

const approve = workflow.durableTask({ name: 'approve', parents: [plan], fn: async (input, ctx) => {
  // 挂起等待人类审批——进程释放，零资源消耗
  const event = await ctx.waitForEvent('approval:response');
  return { approved: event.approved };
}});

const execute = workflow.task({ name: 'execute', parents: [approve], fn: async (input, ctx) => {
  // 只有审批通过后才会执行——服务端保证
  const planResult = await ctx.parentOutput(plan);
  // 调用 Claude CLI 执行
}});
```

**为什么是硬强制：** `execute` 的 worker 进程在 `approve` 完成前**根本不存在**。不是"告诉 Agent 不要做"，是"Agent 的进程还没被创建"。

#### Paperclip ⚠️ 可用但软
- 已验证能跑 Agent（汉化任务 4/5 分）
- 但强制性依赖 instructions 文本——Agent 可以忽略
- 插件可以控制唤醒时机，但 Agent 被唤醒后自由度太高

#### Clawith ⚠️ 有潜力但方向不对
- Autonomy L3 是 per-tool-call 审批，不是 per-phase 审批
- 没有工作流状态机——不知道"当前在规划阶段还是执行阶段"
- SOUL/MEMORY 系统很好，但解决的是记忆问题不是流程问题
- 自进化（MorphAgent）是论文概念，代码里没有实现

#### DeerFlow 2.0 ❌ 方向变了
- **关键发现：2.0 放弃了多节点 StateGraph，改为单 Agent + 中间件链**
- 之前的分析基于 1.0 的架构（Coordinator→Planner→Coder→Analyzer），2.0 已经不是这样了
- 2.0 是"超级 Agent 运行时"，不是"多 Agent 工作流引擎"
- 没有图级工作流强制，只有中间件拦截

#### Symphony ❌ 不是工作流引擎
- 明确是"调度器/运行器"，不是工作流引擎
- 单节点 Elixir 应用，GenServer 轮询 Linear
- 没有 DAG/流水线概念——这是设计上的 non-goal
- 用 Linear 状态转换做门控可以 work，但太粗糙

---

## 评分

| 维度 (权重) | Hatchet | Paperclip | Clawith | DeerFlow | Symphony |
|------------|---------|-----------|---------|----------|----------|
| 工作流强制 (30%) | **10** | 4 | 5 | 2 | 2 |
| 搭建速度 (20%) | **8** | 9 | 5 | 4 | 3 |
| 人类审批 (15%) | **10** | 6 | 7 | 4 | 5 |
| 扩展潜力 (15%) | **8** | 7 | 8 | 5 | 4 |
| 技术栈匹配 (10%) | **9** | 10 | 9 | 4 | 2 |
| 社区生态 (10%) | 7 | 5 | 6 | 6 | 5 |
| **加权总分** | **8.85** | **6.45** | **6.30** | **3.70** | **3.25** |

---

## 结论

**Hatchet 是唯一能"硬强制"工作流步骤的框架。**

其他框架的"强制"都是某种程度的"软约束"——依赖 Agent 自觉、依赖 prompt 指令、或者依赖外部任务板状态。只有 Hatchet 的 DAG 是服务端强制的：step2 的进程在 step1 完成前不存在。

## 推荐方案

**Hatchet（工作流引擎）+ Paperclip（Agent 执行）+ Clawith 模式（自进化/记忆）**

- Hatchet 做骨架：强制步骤顺序、人类审批门控、持久执行
- Paperclip 做手脚：Agent 适配器、工作区隔离、成本追踪
- 借鉴 Clawith：SOUL/MEMORY 持久化、Autonomy 分级
- Last Mile 做灵魂：预算分离、返工指标、知识沉淀
