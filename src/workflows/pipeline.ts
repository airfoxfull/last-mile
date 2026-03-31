import { Hatchet } from "@hatchet-dev/typescript-sdk";
import { paperclip } from "../paperclip/client.js";

const hatchet = Hatchet.init();

// ── Pipeline Workflow: plan → approve → execute ──

const pipeline = hatchet.workflow({
  name: "lastmile-pipeline",
  description: "Last Mile 强制流水线：规划 → 审批 → 执行",
});

// Step 1: Plan — Agent 必须先提交执行计划
const plan = pipeline.task({
  name: "plan",
  fn: async (input) => {
    const { agentId, issueId, requirement } = input as any;

    console.log(`[plan] 唤醒 Agent ${agentId}，要求提交规划`);

    // Write handoff document for the agent
    await paperclip.writeDocument(issueId, "handoff", "任务交接", [
      `# 任务交接`,
      ``,
      `## 需求`,
      requirement,
      ``,
      `## 你的任务`,
      `请分析这个需求，制定执行计划。`,
      `计划必须包含：任务拆分、风险评估、预算估算。`,
      ``,
      `## 约束`,
      `- 先提交计划，等人类审批后才能执行`,
      `- 不要直接改代码，只写计划文档`,
    ].join("\n"));

    // Wake the agent
    await paperclip.invokeAgent(agentId, issueId, "请阅读交接文档，提交执行计划");

    // Wait for agent to finish (poll issue status)
    let attempts = 0;
    while (attempts < 60) {
      await new Promise((r) => setTimeout(r, 10000)); // 10s interval
      const issue = await paperclip.getIssue(issueId);
      if (issue.status === "in_review" || issue.status === "done") {
        console.log(`[plan] Agent 已提交计划`);
        break;
      }
      attempts++;
    }

    // Read the plan document
    let planDoc;
    try {
      planDoc = await paperclip.readDocument(issueId, "agent-plan");
    } catch {
      planDoc = { latestBody: "(Agent 未提交计划文档)" };
    }

    return {
      issueId,
      agentId,
      requirement,
      plan: planDoc.latestBody ?? planDoc.body ?? "(空)",
    };
  },
});

// Step 2: Approve — 人类审批（硬阻塞）
const approve = pipeline.durableTask({
  name: "approve",
  parents: [plan],
  fn: async (input, ctx) => {
    const data = input as any;
    console.log(`[approve] 等待人类审批...`);
    console.log(`[approve] 计划摘要: ${data.plan.slice(0, 200)}...`);

    // Durable wait — process suspends, zero resource consumption
    const event = await ctx.waitForEvent("pipeline:approval") as any;

    const approved = (event as any).approved;
    const score = (event as any).score ?? 0;
    const feedback = (event as any).feedback ?? "";

    console.log(`[approve] 人类决定: ${approved ? "通过" : "拒绝"}, 分数: ${score}`);

    if (!approved) {
      // Write feedback to issue
      await paperclip.addComment(data.issueId, `❌ 计划被拒绝。反馈: ${feedback}`);
      throw new Error(`计划被拒绝: ${feedback}`);
    }

    await paperclip.addComment(data.issueId, `✅ 计划已批准，分数: ${score}/5`);

    return {
      ...data,
      planScore: score,
      approved: true,
    };
  },
});

// Step 3: Execute — Agent 按计划执行（只有审批通过后才会到这里）
const execute = pipeline.task({
  name: "execute",
  parents: [approve],
  fn: async (input) => {
    const data = input as any;

    console.log(`[execute] 审批已通过，唤醒 Agent 执行`);

    // Update handoff for execution phase
    await paperclip.writeDocument(data.issueId, "handoff", "执行指令", [
      `# 执行指令`,
      ``,
      `## 已批准的计划`,
      data.plan,
      ``,
      `## 你的任务`,
      `按照上面的计划执行。完成后提交工作报告。`,
    ].join("\n"));

    // Wake agent for execution
    await paperclip.invokeAgent(data.agentId, data.issueId, "计划已批准，请按计划执行");

    // Wait for completion
    let attempts = 0;
    while (attempts < 120) {
      await new Promise((r) => setTimeout(r, 10000));
      const issue = await paperclip.getIssue(data.issueId);
      if (issue.status === "in_review" || issue.status === "done") {
        console.log(`[execute] Agent 执行完成`);
        break;
      }
      attempts++;
    }

    // Read report
    let report;
    try {
      report = await paperclip.readDocument(data.issueId, "report");
    } catch {
      report = { latestBody: "(Agent 未提交报告)" };
    }

    console.log(`[execute] 流水线完成`);

    return {
      issueId: data.issueId,
      requirement: data.requirement,
      plan: data.plan,
      planScore: data.planScore,
      report: report.latestBody ?? report.body ?? "(空)",
      status: "completed",
    };
  },
});

export { pipeline, hatchet };
