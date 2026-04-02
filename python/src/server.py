"""Last Mile HTTP 服务器 — 启动/恢复/查询流水线"""

import uuid
import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langgraph.types import Command

from src.workflow.pipeline import pipeline

app = FastAPI(title="Last Mile Pipeline Server")


class StartRequest(BaseModel):
    agent_id: str
    executor_id: str
    requirement: str
    fool_id: str = ""
    max_reworks: int = 5


class ResumeRequest(BaseModel):
    thread_id: str
    score: int
    feedback: str = ""


@app.post("/start")
async def start_pipeline(req: StartRequest):
    thread_id = f"pipeline-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "agent_id": req.agent_id,
        "executor_id": req.executor_id,
        "fool_id": req.fool_id,
        "requirement": req.requirement,
        "phase": "planning",
        "rework_count": 0,
        "max_reworks": req.max_reworks,
        "last_fail_reason": "",
        "rework_history": [],
        "plan_body": "",
        "report_body": "",
        "challenge_body": "",
        "plan_score": None,
        "result_score": None,
        "plan_session_id": "",
        "exec_session_id": "",
    }

    # 异步执行
    asyncio.create_task(_run(config, initial_state))
    return {"thread_id": thread_id, "message": "流水线已启动"}


@app.post("/resume")
async def resume_pipeline(req: ResumeRequest):
    config = {"configurable": {"thread_id": req.thread_id}}
    state = await pipeline.aget_state(config)

    if not state.next:
        raise HTTPException(400, "流水线未在等待审批")

    asyncio.create_task(_resume(config, {"score": req.score, "feedback": req.feedback}))
    return {"message": "流水线已恢复"}


@app.get("/status")
async def get_status(thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    state = await pipeline.aget_state(config)

    return {
        "thread_id": thread_id,
        "phase": state.values.get("phase", "unknown"),
        "rework_count": state.values.get("rework_count", 0),
        "next": list(state.next),
        "interrupted": len(state.next) > 0,
    }


async def _run(config, initial_state):
    try:
        async for chunk in pipeline.astream(initial_state, config, stream_mode="updates"):
            for node, update in chunk.items():
                print(f"[server] 节点完成: {node} → {update.get('phase', '')}")
        print("[server] 流水线暂停或完成")
    except Exception as e:
        print(f"[server] 错误: {e}")


async def _resume(config, resume_value):
    try:
        async for chunk in pipeline.astream(Command(resume=resume_value), config, stream_mode="updates"):
            for node, update in chunk.items():
                print(f"[server] 节点完成: {node} → {update.get('phase', '')}")
        print("[server] 流水线暂停或完成")
    except Exception as e:
        print(f"[server] 恢复错误: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3200)
