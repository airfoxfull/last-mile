import {
  StateGraph,
  START,
  END,
  Annotation,
  interrupt,
  MemorySaver,
} from "@langchain/langgraph";
import { paperclip } from "../paperclip/client.js";
import { checkPlan, checkReport } from "../gates.js";

// ── 状态定义 ──

const PipelineState = Annotation.Root({
  agentId: Annotation<string>({ reducer: (_, b) => b, default: () => "" }),
  issueId: Annotation<string>({ reducer: (_, b) => b, default: () => "" }),
  companyId: Annotation<string>({ reducer: (_, b) => b, default: () => "" }),
  requirement: Annotation<string>({ reducer: (_, b) => b, default: () => "" }),
  foolAgentId: Annotation<string | null>({ reducer: (_, b) => b, default: () => null }),

  phase: Annotation<string>({ reducer: (_, b) => b, default: () => "planning" }),
  reworkCount: Annotation<number>({ reducer: (_, b) => b, default: () => 0 }),
  maxReworks: Annotation<number>({ reducer: (_, b) => b, default: () => 5 }),

  lastFailReason: Annotation<string>({ reducer: (_, b) => b, default: () => "" }),
  reworkHistory: Annotation<string[]>({ reducer: (_, b) => b, default: () => [] }),

  planBody: Annotation<string>({ reducer: (_, b) => b, default: () => "" }),
  reportBody: Annotation<string>({ reducer: (_, b) => b, default: () => "" }),
  challengeBody: Annotation<string>({ reducer: (_, b) => b, default: () => "" }),

  planScore: Annotation<number | null>({ reducer: (_, b) => b, default: () => null }),
  resultScore: Annotation<number | null>({ reducer: (_, b) => b, default: () => null }),
});

// ── 辅助函数 ──

/** 轮询 Agent 直到完成（idle）或超时 */
async function pollAgent(agentId: string, maxMs = 600_000, intervalMs = 10_000) {
  const start = Date.now();
  while (Date.now() - start < maxMs) {
    try {
      const agent = await paperclip.getAgent(agentId) as any;
      if (agent.status === "idle" || agent.status === "paused") return true;
    } catch { /* ignore transient errors */ }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return false;
}

// ── 节点 1: plan_agent — 写 handoff + 唤醒 Agent + 轮询完成 ──

async function planAgent(state: typeof PipelineState.State) {
  const { agentId, issueId, requirement, reworkCount, reworkHistory, planBody } = state;

  // 构建记忆上下文（解决 Agent 无跨运行记忆问题）
  let memoryPrefix = "";
  if (reworkCount > 0) {
    memoryPrefix = [
      `【历史记录 — 请务必阅读】`,
      `- 本任务已返工 ${reworkCount} 次`,
      `- 返工原因: ${reworkHistory.join("; ")}`,
      planBody ? `- 上次提交的 plan 摘要: ${planBody.slice(0, 300)}` : "",
      `- 请根据以上反馈改进你的计划`,
      ``,
    ].filter(Boolean).join("\n");
  }

  // 写 handoff 文档
  await paperclip.writeDocument(issueId, "handoff", "任务交接", [
    `# 任务交接`,
    ``,
    `## 需求`,
    requirement,
    ``,
    `## 你的任务`,
    `请分析这个需求，制定执行计划。`,
    `计划必须包含：## 任务分析、## 执行步骤、## 风险评估、## 预算估算`,
    ``,
    `## 约束`,
    `- 先提交计划，等人类审批后才能执行`,
    `- 不要直接改代码，只写计划文档`,
  ].join("\n"));

  // 唤醒 Agent
  const prompt = memoryPrefix + [
    `你现在处于【规划阶段】。任务: ${requirement}`,
    ``,
    `你【必须】做:`,
    `1. 阅读交接文档（issue document key: handoff）`,
    `2. 写一份执行计划文档（issue document key: plan），格式要求:`,
    `   ## 任务分析`,
    `   ## 执行步骤`,
    `   ## 风险评估`,
    `   ## 预算估算`,
    ``,
    `你【不能】修改任何代码文件。只能读代码和写文档。`,
    `完成后把 issue 状态改为 in_review。`,
  ].join("\n");

  console.log(`[plan_agent] 唤醒 Agent ${agentId}（返工 #${reworkCount}）`);
  await paperclip.invokeAgent(agentId, issueId, prompt);
  await pollAgent(agentId);

  return { phase: "checking_plan" };
}

// ── 节点 2: check_plan — 读 plan 文档 + feature-forge 格式验证 ──

async function checkPlanGate(state: typeof PipelineState.State) {
  const { issueId, reworkCount, maxReworks, reworkHistory } = state;

  let planBody = "";
  try {
    const doc = await paperclip.readDocument(issueId, "plan") as any;
    planBody = doc.latestBody ?? doc.body ?? "";
  } catch { /* no plan doc */ }

  if (!planBody) {
    const reason = "未检测到计划文档（key: plan）";
    console.log(`[check_plan] ⚠️ ${reason}，返工 #${reworkCount + 1}`);
    await paperclip.addComment(issueId, `⚠️ 门控1: ${reason}。自动返工第 ${reworkCount + 1} 次。`);
    return {
      planBody: "",
      phase: "plan_failed",
      reworkCount: reworkCount + 1,
      lastFailReason: reason,
      reworkHistory: [...reworkHistory, reason],
    };
  }

  const gate = checkPlan(planBody);
  if (!gate.ok) {
    const reason = `格式不符，缺少: ${gate.missing.join("、")}`;
    console.log(`[check_plan] ⚠️ ${reason}，返工 #${reworkCount + 1}`);
    await paperclip.addComment(issueId, `⚠️ 门控1（feature-forge）: ${reason}。自动返工第 ${reworkCount + 1} 次。`);
    return {
      planBody,
      phase: "plan_failed",
      reworkCount: reworkCount + 1,
      lastFailReason: reason,
      reworkHistory: [...reworkHistory, reason],
    };
  }

  console.log(`[check_plan] ✅ 门控1通过`);
  await paperclip.addComment(issueId, "✅ 门控1通过（计划存在 + 格式正确）。");
  return { planBody, phase: "plan_passed" };
}

// ── 节点 3: fool_challenge — The Fool 辩论循环（可选） ──

async function foolChallenge(state: typeof PipelineState.State) {
  const { foolAgentId, agentId, issueId, planBody } = state;

  if (!foolAgentId) {
    console.log(`[fool] 跳过（未配置 foolAgentId）`);
    return { phase: "awaiting_approval" };
  }

  // Fool Agent 挑战计划
  const challengePrompt = [
    `你是【挑战者】。你的任务是找出以下计划的漏洞、风险和不合理之处。`,
    ``,
    `## 计划内容`,
    planBody,
    ``,
    `请写一份挑战文档（issue document key: challenge），指出:`,
    `1. 计划中的假设是否成立？`,
    `2. 有哪些被忽略的风险？`,
    `3. 执行步骤是否有遗漏？`,
    `4. 预算估算是否合理？`,
  ].join("\n");

  console.log(`[fool] 唤醒 Fool Agent ${foolAgentId}`);
  await paperclip.invokeAgent(foolAgentId, issueId, challengePrompt);
  await pollAgent(foolAgentId);

  let challengeBody = "";
  try {
    const doc = await paperclip.readDocument(issueId, "challenge") as any;
    challengeBody = doc.latestBody ?? doc.body ?? "";
  } catch { /* no challenge doc */ }

  if (!challengeBody) {
    console.log(`[fool] Fool Agent 未提交挑战文档，跳过`);
    return { challengeBody: "", phase: "awaiting_approval" };
  }

  // 原 Agent 回应挑战
  const responsePrompt = [
    `你的计划被挑战了。请阅读挑战文档（issue document key: challenge），`,
    `然后更新你的计划文档（issue document key: plan）来回应这些质疑。`,
    ``,
    `## 挑战内容`,
    challengeBody,
  ].join("\n");

  console.log(`[fool] 唤醒原 Agent ${agentId} 回应挑战`);
  await paperclip.invokeAgent(agentId, issueId, responsePrompt);
  await pollAgent(agentId);

  // 重新读取更新后的 plan
  let updatedPlan = planBody;
  try {
    const doc = await paperclip.readDocument(issueId, "plan") as any;
    updatedPlan = doc.latestBody ?? doc.body ?? planBody;
  } catch { /* keep original */ }

  await paperclip.addComment(issueId, "✅ The Fool 辩论完成。人类可查看: plan + challenge。");
  return { challengeBody, planBody: updatedPlan, phase: "awaiting_approval" };
}

// ── 节点 4: human_approval — interrupt() 等人类打分 ──

async function humanApproval(state: typeof PipelineState.State) {
  const { issueId, reworkCount, reworkHistory } = state;

  await paperclip.updateIssue(issueId, { status: "in_review" });
  console.log(`[human_approval] 等待人类审批...`);

  const response = interrupt({
    type: "plan_approval",
    message: "请审批计划（1-5 分，>= 3 通过）",
    issueId,
  }) as { score: number; feedback?: string };

  const { score, feedback } = response;
  console.log(`[human_approval] 人类评分: ${score}/5`);

  if (score < 3) {
    const reason = `计划被拒（${score}/5）: ${feedback ?? ""}`;
    await paperclip.addComment(issueId, `❌ ${reason}`);
    return {
      planScore: score,
      phase: "plan_rejected",
      reworkCount: reworkCount + 1,
      lastFailReason: reason,
      reworkHistory: [...reworkHistory, reason],
    };
  }

  await paperclip.addComment(issueId, `✅ 计划批准（${score}/5）。开始执行。`);
  return { planScore: score, phase: "executing" };
}

// ── 节点 5: execute_agent — 写执行 handoff + 唤醒 Agent + 轮询 ──

async function executeAgent(state: typeof PipelineState.State) {
  const { agentId, issueId, planBody, planScore, reworkCount, reworkHistory, reportBody } = state;

  let memoryPrefix = "";
  if (state.phase === "exec_rework") {
    memoryPrefix = [
      `【历史记录】`,
      `- 执行阶段已返工 ${reworkCount} 次`,
      `- 上次返工原因: ${state.lastFailReason}`,
      reportBody ? `- 上次报告摘要: ${reportBody.slice(0, 200)}` : "",
      ``,
    ].filter(Boolean).join("\n");
  }

  await paperclip.writeDocument(issueId, "handoff", "执行指令", [
    `# 执行指令`,
    ``,
    `## 已批准的计划（${planScore}/5）`,
    planBody,
    ``,
    `## 你的任务`,
    `按照上面的计划执行。完成后提交工作报告（issue document key: report）。`,
    `报告必须包含: ## 完成情况 和 ## 变更文件`,
  ].join("\n"));

  const prompt = memoryPrefix + `计划已批准（${planScore}/5）。请按计划执行，完成后提交工作报告。`;

  console.log(`[execute_agent] 唤醒 Agent ${agentId} 执行`);
  await paperclip.invokeAgent(agentId, issueId, prompt);
  await pollAgent(agentId);

  return { phase: "checking_report" };
}

// ── 节点 6: check_report — 读 report + code-reviewer 格式验证 ──

async function checkReportGate(state: typeof PipelineState.State) {
  const { issueId, reworkCount, reworkHistory } = state;

  let reportBody = "";
  try {
    const doc = await paperclip.readDocument(issueId, "report") as any;
    reportBody = doc.latestBody ?? doc.body ?? "";
  } catch { /* no report doc */ }

  if (!reportBody) {
    const reason = "未检测到工作报告（key: report）";
    console.log(`[check_report] ⚠️ ${reason}`);
    await paperclip.addComment(issueId, `⚠️ 门控3: ${reason}。自动返工第 ${reworkCount + 1} 次。`);
    return {
      reportBody: "",
      phase: "report_failed",
      reworkCount: reworkCount + 1,
      lastFailReason: reason,
      reworkHistory: [...reworkHistory, reason],
    };
  }

  const gate = checkReport(reportBody);
  if (!gate.ok) {
    const reason = `报告格式不符，缺少: ${gate.missing.join("、")}`;
    console.log(`[check_report] ⚠️ ${reason}`);
    await paperclip.addComment(issueId, `⚠️ 门控3（code-reviewer）: ${reason}`);
  }

  console.log(`[check_report] ✅ 门控3通过`);
  await paperclip.addComment(issueId, "✅ 门控3通过。等待人类评分。");
  return { reportBody, phase: "report_passed" };
}

// ── 节点 7: human_score — interrupt() 等人类评分结果 ──

async function humanScore(state: typeof PipelineState.State) {
  const { issueId, planScore, reworkCount, reworkHistory } = state;

  await paperclip.updateIssue(issueId, { status: "in_review" });
  console.log(`[human_score] 等待人类评分...`);

  const response = interrupt({
    type: "result_score",
    message: "请评分执行结果（1-5 分，>= 3 通过）",
    issueId,
  }) as { score: number; feedback?: string };

  const { score, feedback } = response;
  console.log(`[human_score] 人类评分: ${score}/5`);

  if (score < 3) {
    const reason = `结果不满意（${score}/5）: ${feedback ?? ""}`;
    await paperclip.addComment(issueId, `❌ ${reason}`);
    return {
      resultScore: score,
      phase: "exec_rework",
      reworkCount: reworkCount + 1,
      lastFailReason: reason,
      reworkHistory: [...reworkHistory, reason],
    };
  }

  await paperclip.addComment(issueId,
    `✅ 完成（计划 ${planScore}/5，结果 ${score}/5，返工 ${reworkCount} 次）`);
  await paperclip.updateIssue(issueId, { status: "done" });
  return { resultScore: score, phase: "done" };
}

// ── 路由函数 ──

function afterCheckPlan(state: typeof PipelineState.State): "plan_agent" | "fool_challenge" {
  if (state.phase === "plan_failed") {
    if (state.reworkCount >= state.maxReworks) {
      console.log(`[router] 返工次数达上限 ${state.maxReworks}，强制进入审批`);
      return "fool_challenge";
    }
    return "plan_agent"; // 返工循环
  }
  return "fool_challenge"; // 通过 → Fool 挑战（或跳过）
}

function afterHumanApproval(state: typeof PipelineState.State): "plan_agent" | "execute_agent" {
  return state.phase === "plan_rejected" ? "plan_agent" : "execute_agent";
}

function afterCheckReport(state: typeof PipelineState.State): "execute_agent" | "human_score" {
  if (state.phase === "report_failed") {
    if (state.reworkCount >= state.maxReworks) return "human_score";
    return "execute_agent";
  }
  return "human_score";
}

function afterHumanScore(state: typeof PipelineState.State): "execute_agent" | "__end__" {
  return state.phase === "exec_rework" ? "execute_agent" : "__end__";
}

// ── 构建图 ──

const checkpointer = new MemorySaver();

const builder = new StateGraph(PipelineState)
  .addNode("plan_agent", planAgent)
  .addNode("check_plan", checkPlanGate)
  .addNode("fool_challenge", foolChallenge)
  .addNode("human_approval", humanApproval)
  .addNode("execute_agent", executeAgent)
  .addNode("check_report", checkReportGate)
  .addNode("human_score", humanScore)
  // 边
  .addEdge(START, "plan_agent")
  .addEdge("plan_agent", "check_plan")
  .addConditionalEdges("check_plan", afterCheckPlan)
  .addEdge("fool_challenge", "human_approval")
  .addConditionalEdges("human_approval", afterHumanApproval)
  .addEdge("execute_agent", "check_report")
  .addConditionalEdges("check_report", afterCheckReport)
  .addConditionalEdges("human_score", afterHumanScore);

export const pipeline = builder.compile({ checkpointer });
export { checkpointer };
