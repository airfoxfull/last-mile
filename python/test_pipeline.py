"""端到端测试：完整流水线 plan → gate → fool → approve → execute → gate → score"""

import asyncio
import sys
sys.path.insert(0, ".")

from langgraph.types import Command
from src.clawith import client
from src.workflow.pipeline import pipeline

def print_stream(chunk):
    """统一处理 stream chunk 格式"""
    if isinstance(chunk, dict):
        for node, update in chunk.items():
            phase = update.get("phase", "") if isinstance(update, dict) else ""
            print(f"  [{node}] → {phase}")
    elif isinstance(chunk, tuple) and len(chunk) == 2:
        node, update = chunk
        phase = update.get("phase", "") if isinstance(update, dict) else ""
        print(f"  [{node}] → {phase}")

PLANNER_ID = "92b0c2d0-88a1-46b1-aec2-cc9233fbc122"
EXECUTOR_ID = "d6122b5f-d7c6-445d-9ae4-2140c6ad6c7a"
FOOL_ID = "46ba028d-f608-4d83-807c-04a4641412ed"


async def main():
    # 登录
    await client.login("296105415@qq.com", "Aa123456")
    print("✅ 登录成功\n")

    requirement = "把项目的 README.md 翻译成英文"

    config = {"configurable": {"thread_id": "test-pipeline-002"}}
    initial = {
        "agent_id": PLANNER_ID,
        "executor_id": EXECUTOR_ID,
        "fool_id": "",  # 先不用 Fool，简化测试
        "requirement": requirement,
        "phase": "planning",
        "rework_count": 0,
        "max_reworks": 3,
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

    # Phase 1: 运行到 human_approval（会 interrupt）
    print("=" * 60)
    print("Phase 1: 规划 + 门控")
    print("=" * 60)

    async for chunk in pipeline.astream(initial, config, stream_mode="updates"):
        if isinstance(chunk, dict):
            for node, update in chunk.items():
                phase = update.get("phase", "") if isinstance(update, dict) else ""
                print(f"  [{node}] → {phase}")
        elif isinstance(chunk, tuple) and len(chunk) == 2:
            node, update = chunk
            phase = update.get("phase", "") if isinstance(update, dict) else ""
            print(f"  [{node}] → {phase}")

    # 检查状态
    state = await pipeline.aget_state(config)
    print(f"\n当前阶段: {state.values.get('phase')}")
    print(f"返工次数: {state.values.get('rework_count')}")
    print(f"等待审批: {bool(state.next)}")

    if state.values.get("plan_body"):
        print(f"\n📋 计划预览:\n{state.values['plan_body'][:300]}...")

    if not state.next:
        print("\n流水线已完成或出错")
        return

    # Phase 2: 人类审批（模拟打 4 分）
    print("\n" + "=" * 60)
    print("Phase 2: 人类审批（模拟 4 分）")
    print("=" * 60)

    async for chunk in pipeline.astream(
        Command(resume={"score": 4, "feedback": "计划不错"}),
        config, stream_mode="updates"
    ):
        print_stream(chunk)

    # 检查状态
    state = await pipeline.aget_state(config)
    print(f"\n当前阶段: {state.values.get('phase')}")

    if state.values.get("report_body"):
        print(f"\n📋 报告预览:\n{state.values['report_body'][:300]}...")

    if not state.next:
        print("\n流水线已完成")
        return

    # Phase 3: 人类评分（模拟打 4 分）
    print("\n" + "=" * 60)
    print("Phase 3: 人类评分（模拟 4 分）")
    print("=" * 60)

    async for chunk in pipeline.astream(
        Command(resume={"score": 4, "feedback": "执行满意"}),
        config, stream_mode="updates"
    ):
        print_stream(chunk)

    state = await pipeline.aget_state(config)
    print(f"\n最终阶段: {state.values.get('phase')}")
    print(f"计划评分: {state.values.get('plan_score')}")
    print(f"结果评分: {state.values.get('result_score')}")
    print(f"返工次数: {state.values.get('rework_count')}")
    print("\n✅ 流水线完成！")


if __name__ == "__main__":
    asyncio.run(main())
