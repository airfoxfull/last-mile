# Paperclip Demo: 强制 2 阶段流水线

## 方案

不改心跳服务核心代码，而是通过 Last Mile 插件的事件监听 + Agent instructions 实现强制流程。

### 机制

1. Agent 的 instructions 文件明确写死工作流：
   - 第一次被唤醒：只能提交计划文档，然后停止
   - 第二次被唤醒（计划被批准后）：执行工作，提交报告

2. 插件监听 issue.updated 事件：
   - 检测到 plan 文档被创建 → 通知人类审批
   - 人类批准后 → 插件再次唤醒 Agent 进入执行阶段

3. 阶段状态通过 issue documents 的 key 来判断：
   - 有 `plan` 文档但没有 `plan-approved` 标记 → 等待审批
   - 有 `plan-approved` → 可以执行
   - 有 `report` 文档 → 执行完成，等待评分

### 强制性验证

Agent 能不能绕过？
- instructions 里写了"如果没有 plan-approved 标记，禁止修改代码"
- 但这是"建议"不是"系统强制"——Agent 理论上可以忽略
- 这就是 Paperclip 方案的核心弱点

### 结论

Paperclip 能实现流程，但强制性依赖 Agent 自觉遵守 instructions。
这是"软强制"，不是"硬强制"。
