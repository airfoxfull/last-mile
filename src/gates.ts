/**
 * 门控检查函数 — 从 Paperclip 插件迁移
 */

export interface GateResult {
  ok: boolean;
  missing: string[];
}

/** 门1: feature-forge 格式检查 — plan 文档必须包含 4 个必需章节 */
export function checkPlan(body: string): GateResult {
  const need = ["## 任务分析", "## 执行步骤", "## 风险评估", "## 预算估算"];
  const missing = need.filter((h) => !body.includes(h));
  if (body.length < 50) missing.push("内容过短");
  return { ok: missing.length === 0, missing };
}

/** 门3: code-reviewer 格式检查 — report 文档必须包含完成情况和变更文件 */
export function checkReport(body: string): GateResult {
  const need = ["## 完成情况", "## 变更文件"];
  const missing = need.filter((h) => !body.includes(h));
  if (body.length < 30) missing.push("内容过短");
  return { ok: missing.length === 0, missing };
}
