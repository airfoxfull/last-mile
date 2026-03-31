import { createServer } from "node:http";
import { Command } from "@langchain/langgraph";
import { pipeline } from "./workflows/pipeline.js";

const PORT = parseInt(process.env.PORT ?? "3200", 10);

// ── 简单 HTTP 服务器 ──

const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", `http://localhost:${PORT}`);
  const body = await readBody(req);

  try {
    // POST /start — 启动流水线
    if (req.method === "POST" && url.pathname === "/start") {
      const { agentId, issueId, companyId, requirement, foolAgentId } = body;
      if (!agentId || !issueId) {
        return json(res, 400, { error: "缺少 agentId 或 issueId" });
      }

      const threadId = `pipeline-${issueId}-${Date.now()}`;
      const config = { configurable: { thread_id: threadId } };

      console.log(`[worker] 启动流水线 thread=${threadId}`);

      // 异步执行，不阻塞 HTTP 响应
      runPipeline(config, {
        agentId,
        issueId,
        companyId: companyId ?? "",
        requirement: requirement ?? "",
        foolAgentId: foolAgentId ?? null,
        phase: "planning",
        reworkCount: 0,
        maxReworks: 5,
        lastFailReason: "",
        reworkHistory: [],
        planBody: "",
        reportBody: "",
        challengeBody: "",
        planScore: null,
        resultScore: null,
      });

      return json(res, 202, { threadId, message: "流水线已启动" });
    }

    // POST /resume — 恢复流水线（人类审批/评分）
    if (req.method === "POST" && url.pathname === "/resume") {
      const { threadId, score, feedback } = body;
      if (!threadId || score == null) {
        return json(res, 400, { error: "缺少 threadId 或 score" });
      }

      const config = { configurable: { thread_id: threadId } };

      console.log(`[worker] 恢复流水线 thread=${threadId} score=${score}`);

      // 异步恢复
      resumePipeline(config, { score, feedback });

      return json(res, 202, { message: "流水线已恢复" });
    }

    // GET /status — 查询流水线状态
    if (req.method === "GET" && url.pathname === "/status") {
      const threadId = url.searchParams.get("threadId");
      if (!threadId) return json(res, 400, { error: "缺少 threadId" });

      const config = { configurable: { thread_id: threadId } };
      const state = await pipeline.getState(config);

      return json(res, 200, {
        threadId,
        phase: state.values?.phase ?? "unknown",
        reworkCount: state.values?.reworkCount ?? 0,
        next: state.next,
        interrupted: (state.tasks ?? []).some((t: any) => t.interrupts?.length > 0),
      });
    }

    return json(res, 404, { error: "Not found" });
  } catch (err: any) {
    console.error(`[worker] 错误:`, err);
    return json(res, 500, { error: err.message });
  }
});

// ── 辅助函数 ──

async function runPipeline(config: any, input: any) {
  try {
    for await (const chunk of await pipeline.stream(input, { ...config, streamMode: "updates" })) {
      const [node, update] = Object.entries(chunk)[0] ?? [];
      if (node) console.log(`[worker] 节点完成: ${node}`, (update as any)?.phase ?? "");
    }
    console.log(`[worker] 流水线暂停或完成`);
  } catch (err) {
    console.error(`[worker] 流水线错误:`, err);
  }
}

async function resumePipeline(config: any, resumeValue: any) {
  try {
    for await (const chunk of await pipeline.stream(
      new Command({ resume: resumeValue }),
      { ...config, streamMode: "updates" },
    )) {
      const [node, update] = Object.entries(chunk)[0] ?? [];
      if (node) console.log(`[worker] 节点完成: ${node}`, (update as any)?.phase ?? "");
    }
    console.log(`[worker] 流水线暂停或完成`);
  } catch (err) {
    console.error(`[worker] 恢复错误:`, err);
  }
}

function readBody(req: any): Promise<any> {
  return new Promise((resolve) => {
    let data = "";
    req.on("data", (c: Buffer) => (data += c.toString()));
    req.on("end", () => {
      try { resolve(JSON.parse(data)); } catch { resolve({}); }
    });
  });
}

function json(res: any, status: number, data: any) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(data));
}

// ── 启动 ──

server.listen(PORT, () => {
  console.log(`[worker] Last Mile LangGraph Worker 启动: http://localhost:${PORT}`);
  console.log(`[worker] POST /start   — 启动流水线`);
  console.log(`[worker] POST /resume  — 恢复流水线（人类审批）`);
  console.log(`[worker] GET  /status  — 查询状态`);
});
