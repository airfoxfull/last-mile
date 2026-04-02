"""场景 3：人类拒绝 + 返工

验证：
1. plan 被拒后返工（rework_count 递增）
2. 返工时 Agent 收到历史上下文（memory.md 包含返工记录）
3. 第二次 plan 改进后打 4 分通过
"""

import asyncio
import sys
import uuid

sys.path.insert(0, "E:/last-mile-repo/python")

from langgraph.types import Command
from lastmile.clawith import client
from lastmile.workflow.pipeline import pipeline

PLANNER_ID = "92b0c2d0-88a1-46b1-aec2-cc9233fbc122"
EXECUTOR_ID = "d6122b5f-d7c6-445d-9ae4-2140c6ad6c7a"
THREAD_ID = f"test-rework-{uuid.uuid4().hex[:8]}"

PASS = "[PASS]"
FAIL = "[FAIL]"
results = []


def check(name: str, condition: bool, detail: str = ""):
    tag = PASS if condition else FAIL
    msg = f"  {tag} {name}" + (f" — {detail}" if detail else "")
    print(msg)
    results.append((name, condition))


async def main():
    print(f"=== 场景 3：人类拒绝 + 返工 (thread={THREAD_ID}) ===\n")

    # 登录
    await client.login("296105415@qq.com", "Aa123456")
    print("登录成功\n")

    config = {"configurable": {"thread_id": THREAD_ID}}
    initial = {
        "agent_id": PLANNER_ID,
        "executor_id": EXECUTOR_ID,
        "fool_id": "",  # 不启用 Fool
        "requirement": "写一个 Python 脚本，读取 CSV 文件并生成柱状图",
        "phase": "planning",
        "rework_count": 0,
        "max_reworks": 5,
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

    # ── Round 1: 规划 → 门控 → 等待审批 ──
    print("--- Round 1: 规划 + 门控 ---")
    async for chunk in pipeline.astream(initial, config, stream_mode="updates"):
        if isinstance(chunk, dict):
            for node, update in chunk.items():
                phase = update.get("phase", "") if isinstance(update, dict) else ""
                print(f"  [{node}] -> {phase}")

    state = await pipeline.aget_state(config)
    phase_r1 = state.values.get("phase")
    rework_r1 = state.values.get("rework_count", 0)
    has_interrupt = bool(state.next)

    print(f"\n  阶段: {phase_r1}, 返工: {rework_r1}, 等待审批: {has_interrupt}")
    check("R1-门控后等待审批", has_interrupt and phase_r1 == "awaiting_approval")

    # ── Round 2: 人类打 2 分拒绝 ──
    print("\n--- Round 2: 人类打 2 分拒绝 ---")
    async for chunk in pipeline.astream(
        Command(resume={"score": 2, "feedback": "计划太粗糙，缺少具体库选型"}),
        config, stream_mode="updates",
    ):
        if isinstance(chunk, dict):
            for node, update in chunk.items():
                phase = update.get("phase", "") if isinstance(update, dict) else ""
                print(f"  [{node}] -> {phase}")

    state = await pipeline.aget_state(config)
    phase_r2 = state.values.get("phase")
    rework_r2 = state.values.get("rework_count", 0)
    rework_history = state.values.get("rework_history", [])

    print(f"\n  阶段: {phase_r2}, 返工: {rework_r2}")
    print(f"  返工历史: {rework_history}")

    # 验证 1: rework_count 递增
    check("R2-rework_count 递增", rework_r2 > rework_r1,
          f"{rework_r1} -> {rework_r2}")

    # 验证 2: 返工历史包含拒绝原因
    has_reject_in_history = any("计划被拒" in h for h in rework_history)
    check("R2-返工历史包含拒绝原因", has_reject_in_history,
          str(rework_history[-1]) if rework_history else "empty")

    # 验证 3: memory.md 包含返工记录
    memory_content = ""
    try:
        memory_content = await client.read_file(PLANNER_ID, "memory/memory.md")
    except Exception as e:
        memory_content = f"读取失败: {e}"

    has_memory = "返工" in memory_content or "rework" in memory_content.lower()
    check("R2-memory.md 包含返工记录", has_memory,
          f"memory 长度={len(memory_content)}")

    # 此时应该又到了 human_approval interrupt（第二轮规划完成后）
    has_interrupt_r2 = bool(state.next)
    check("R2-第二轮规划后再次等待审批", has_interrupt_r2)

    # ── Round 3: 人类打 4 分通过 ──
    print("\n--- Round 3: 人类打 4 分通过 ---")
    async for chunk in pipeline.astream(
        Command(resume={"score": 4, "feedback": "改进后的计划可以接受"}),
        config, stream_mode="updates",
    ):
        if isinstance(chunk, dict):
            for node, update in chunk.items():
                phase = update.get("phase", "") if isinstance(update, dict) else ""
                print(f"  [{node}] -> {phase}")

    state = await pipeline.aget_state(config)
    phase_r3 = state.values.get("phase")
    plan_score = state.values.get("plan_score")

    print(f"\n  阶段: {phase_r3}, plan_score: {plan_score}")

    # 验证 4: 通过后进入执行或等待评分
    passed = phase_r3 in ("checking_report", "report_passed", "report_failed") or bool(state.next)
    check("R3-打 4 分后进入执行阶段", passed, f"phase={phase_r3}")
    check("R3-plan_score 记录正确", plan_score == 4, f"plan_score={plan_score}")

    # ── Round 4: 如果到了 human_score，打 4 分完成 ──
    if state.next:
        print("\n--- Round 4: 人类评分（4 分完成） ---")
        async for chunk in pipeline.astream(
            Command(resume={"score": 4, "feedback": "执行结果满意"}),
            config, stream_mode="updates",
        ):
            if isinstance(chunk, dict):
                for node, update in chunk.items():
                    phase = update.get("phase", "") if isinstance(update, dict) else ""
                    print(f"  [{node}] -> {phase}")

        state = await pipeline.aget_state(config)
        final_phase = state.values.get("phase")
        result_score = state.values.get("result_score")
        print(f"\n  最终阶段: {final_phase}, result_score: {result_score}")
        check("R4-流水线完成", final_phase == "done", f"phase={final_phase}")

    # ── 汇总 ──
    print("\n" + "=" * 50)
    passed_count = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"场景 3 结果: {passed_count}/{total} 通过")
    if passed_count < total:
        for name, ok in results:
            if not ok:
                print(f"  FAILED: {name}")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
