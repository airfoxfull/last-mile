import { HatchetClient } from "@hatchet-dev/typescript-sdk";

// CLI tool for human scoring / approval
async function main() {
  const args = process.argv.slice(2);

  const approve = args.includes("--approve");
  const reject = args.includes("--reject");
  const scoreIdx = args.indexOf("--score");
  const score = scoreIdx >= 0 ? Number(args[scoreIdx + 1]) : 0;
  const feedbackIdx = args.indexOf("--feedback");
  const feedback = feedbackIdx >= 0 ? args[feedbackIdx + 1] : "";
  const issueIdx = args.indexOf("--issue");
  const issueId = issueIdx >= 0 ? args[issueIdx + 1] : "";

  if (!approve && !reject) {
    console.log("Last Mile 评分工具");
    console.log("");
    console.log("用法:");
    console.log("  pnpm dev:score -- --approve --score 4 --issue <issueId>");
    console.log("  pnpm dev:score -- --reject --feedback \"需要更详细的计划\" --issue <issueId>");
    console.log("");
    console.log("参数:");
    console.log("  --approve          批准");
    console.log("  --reject           拒绝");
    console.log("  --score <1-5>      满意度评分");
    console.log("  --feedback <text>  反馈意见");
    console.log("  --issue <id>       Issue ID");
    process.exit(0);
  }

  const hatchet = HatchetClient.init();

  console.log(`[score] ${approve ? "批准" : "拒绝"}, 分数: ${score}, Issue: ${issueId}`);

  // Push approval event to Hatchet
  await hatchet.events.push("pipeline:approval", {
    approved: approve,
    score,
    feedback,
    issueId,
  });

  console.log(`[score] 事件已发送`);
}

main().catch((err) => {
  console.error("[score] 错误:", err);
  process.exit(1);
});
