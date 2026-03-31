import { hatchet, pipeline } from "./workflows/pipeline.js";

async function main() {
  console.log("[worker] Last Mile Pipeline Worker 启动中...");

  const worker = await hatchet.worker("lastmile-worker", {
    workflows: [pipeline],
    maxRuns: 10,
  });

  console.log("[worker] 已注册工作流: lastmile-pipeline");
  console.log("[worker] 等待任务...");

  await worker.start();
}

main().catch((err) => {
  console.error("[worker] 启动失败:", err);
  process.exit(1);
});
