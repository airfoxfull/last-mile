export {};
// 触发 Last Mile 流水线
const WORKER_URL = process.env.WORKER_URL ?? "http://localhost:3200";
const PAPERCLIP_URL = process.env.PAPERCLIP_URL ?? "http://localhost:3100";

async function main() {
  const requirement = process.argv[2];
  if (!requirement) {
    console.error("用法: pnpm dev:run \"需求描述\"");
    process.exit(1);
  }

  const COMPANY_ID = process.env.COMPANY_ID ?? "";
  const AGENT_ID = process.env.AGENT_ID ?? "";
  const PROJECT_ID = process.env.PROJECT_ID ?? "";
  const FOOL_AGENT_ID = process.env.FOOL_AGENT_ID ?? "";

  if (!COMPANY_ID || !AGENT_ID) {
    console.error("请设置环境变量: COMPANY_ID, AGENT_ID");
    process.exit(1);
  }

  // 1. 在 Paperclip 创建 Issue
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
  const issue = (await issueRes.json()) as any;
  console.log(`[client] 创建 Issue: ${issue.id}`);

  // 2. 启动 LangGraph 流水线
  const startRes = await fetch(`${WORKER_URL}/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      agentId: AGENT_ID,
      issueId: issue.id,
      companyId: COMPANY_ID,
      requirement,
      foolAgentId: FOOL_AGENT_ID || null,
    }),
  });
  const result = (await startRes.json()) as any;

  console.log(`[client] 流水线已启动`);
  console.log(`[client] Thread ID: ${result.threadId}`);
  console.log(`[client] 需求: ${requirement}`);
  console.log("");
  console.log("后续操作:");
  console.log(`  查看状态: curl http://localhost:3200/status?threadId=${result.threadId}`);
  console.log(`  审批计划: pnpm dev:score -- --thread ${result.threadId} --score 4`);
  console.log(`  评分结果: pnpm dev:score -- --thread ${result.threadId} --score 4`);
}

main().catch((err) => {
  console.error("[client] 错误:", err);
  process.exit(1);
});
