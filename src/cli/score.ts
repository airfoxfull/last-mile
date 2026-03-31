export {};
// 人类审批/评分 CLI
const WORKER_URL = process.env.WORKER_URL ?? "http://localhost:3200";

async function main() {
  const args = process.argv.slice(2);
  const threadId = getArg(args, "--thread");
  const score = parseInt(getArg(args, "--score") ?? "", 10);
  const feedback = getArg(args, "--feedback") ?? "";

  if (!threadId || isNaN(score)) {
    console.error("用法: pnpm dev:score -- --thread <threadId> --score <1-5> [--feedback \"反馈\"]");
    console.error("");
    console.error("示例:");
    console.error("  pnpm dev:score -- --thread pipeline-xxx-123 --score 4");
    console.error("  pnpm dev:score -- --thread pipeline-xxx-123 --score 2 --feedback \"计划不够详细\"");
    process.exit(1);
  }

  // 先查状态
  const statusRes = await fetch(`${WORKER_URL}/status?threadId=${threadId}`);
  const status = (await statusRes.json()) as any;

  if (!status.interrupted) {
    console.log(`[score] 流水线未在等待审批（当前阶段: ${status.phase}）`);
    process.exit(1);
  }

  console.log(`[score] 当前阶段: ${status.phase}, 返工次数: ${status.reworkCount}`);
  console.log(`[score] 提交评分: ${score}/5${feedback ? `, 反馈: ${feedback}` : ""}`);

  // 恢复流水线
  const res = await fetch(`${WORKER_URL}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ threadId, score, feedback }),
  });
  const result = (await res.json()) as any;
  console.log(`[score] ${result.message}`);
}

function getArg(args: string[], flag: string): string | undefined {
  const idx = args.indexOf(flag);
  return idx >= 0 && idx + 1 < args.length ? args[idx + 1] : undefined;
}

main().catch((err) => {
  console.error("[score] 错误:", err);
  process.exit(1);
});
