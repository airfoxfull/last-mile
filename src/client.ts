import { Hatchet } from "@hatchet-dev/typescript-sdk";

// Trigger a pipeline run
async function main() {
  const requirement = process.argv[2];
  if (!requirement) {
    console.error("用法: pnpm dev:run \"需求描述\"");
    process.exit(1);
  }

  // Config — adjust these to match your Paperclip setup
  const COMPANY_ID = process.env.COMPANY_ID ?? "";
  const AGENT_ID = process.env.AGENT_ID ?? "";
  const PROJECT_ID = process.env.PROJECT_ID ?? "";

  if (!COMPANY_ID || !AGENT_ID) {
    console.error("请设置环境变量: COMPANY_ID, AGENT_ID");
    console.error("  export COMPANY_ID=xxx AGENT_ID=yyy");
    process.exit(1);
  }

  const hatchet = Hatchet.init();

  // Create issue in Paperclip first
  const PAPERCLIP_URL = process.env.PAPERCLIP_URL ?? "http://localhost:3100";
  const issueRes = await fetch(`${PAPERCLIP_URL}/api/companies/${COMPANY_ID}/issues`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: requirement.slice(0, 80),
      description: requirement,
      projectId: PROJECT_ID || undefined,
      priority: "high",
    }),
  });
  const issue = await issueRes.json() as any;
  console.log(`[client] 创建 Issue: ${issue.id}`);

  // Trigger the pipeline workflow
  const run = await hatchet.admin.runWorkflow("lastmile-pipeline", {
    agentId: AGENT_ID,
    issueId: issue.id,
    requirement,
  });

  console.log(`[client] 流水线已启动`);
  console.log(`[client] 需求: ${requirement}`);
  console.log(`[client] Issue: ${issue.id}`);
  console.log("");
  console.log("流水线步骤:");
  console.log("  1. [plan]    Agent 提交规划 → 等待中...");
  console.log("  2. [approve] 人类审批 → 运行: pnpm dev:score --run-id <id> --approve --score 4");
  console.log("  3. [execute] Agent 执行 → 审批后自动开始");
}

main().catch((err) => {
  console.error("[client] 错误:", err);
  process.exit(1);
});
