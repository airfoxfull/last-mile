# Last Mile — 实现计划

> 基于设计文档 `2026-03-30-last-mile-design.md`

## Task List

### Phase A: 项目脚手架
- [x] Task 1: 初始化 pnpm monorepo（root + server + ui + shared）
- [x] Task 2: 配置 TypeScript（root tsconfig + 各包 tsconfig）
- [x] Task 3: shared 包：定义类型和常量

### Phase B: 后端 API
- [x] Task 4: SQLite schema + 数据库初始化（sql.js WASM）
- [x] Task 5: 流水线 CRUD API（pipelines + stages）
- [x] Task 6: 运行管理 API（runs + stage_runs）
- [x] Task 7: 评分 API（满意度评分提交 + 阶段推进）
- [x] Task 8: 验收 API（多视角验收提交 + 汇总）
- [x] Task 9: 知识资产 API
- [x] Task 10: WebSocket 事件推送

### Phase C: 前端 UI
- [x] Task 11: Vite + React + TailwindCSS + React Router 脚手架
- [x] Task 12: API 客户端 + WebSocket 客户端
- [x] Task 13: 流水线列表页 + 创建/编辑流水线
- [x] Task 14: 运行看板页（阶段链可视化 + 状态追踪）
- [x] Task 15: 评分面板（满意度表单 + 方向反馈）
- [x] Task 16: 验收面板（多视角验收表单 + 结果汇总）
- [x] Task 17: 知识库页面（列表 + 详情 + 编辑）
- [x] Task 18: 全局仪表盘（运行状态 + 满意度趋势图）

### Phase D: 集成验证
- [x] Task 19: 端到端流程测试 — 服务器启动成功，种子数据加载
- [x] Task 20: 预置"全栈功能开发"流水线模板 — 启动后自动创建

## Success Criteria

- 所有 Task 完成
- `pnpm --filter server test` 通过
- `pnpm --filter ui build` 通过
- `pnpm --filter shared exec tsc --noEmit` 通过
- 能手动走通完整流程：创建流水线 → 提交需求 → 阶段流转 → 评分 → 验收 → 知识记录

## Estimated Iterations

Ralph max-iterations: 40（20 个 task，预留翻倍空间处理返工）
