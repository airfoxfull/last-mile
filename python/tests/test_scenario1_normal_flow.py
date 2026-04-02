"""场景 1：正常流程 — plan → gate → approve → execute → gate → score → done

用 LangGraph pipeline 直接跑，通过 Command(resume=...) 模拟人类打分。
需要 Clawith 在 localhost:8008 运行。
"""

import asyncio
import sys
import uuid

from langgraph.types import Command

# ── 配置 ──
EMAIL = "296105415@qq.com"
PASSWORD = "Aa123456"
PLANNER_ID = "92b0c2d0-88a1-46b1-aec2-cc9233fbc122"
EXECUTOR_ID = "d6122b5f-d7c6-445d-9ae4-2140c6ad6c7a"
FOOL_ID = "46ba028d-f608-4d83-807c-04a4641412ed"

REQUIREMENT = "写一个 Python 函数 fibonacci(n)，返回第 n 个斐波那契数。包含单元测试。"


async def main():
    from lastmile.clawith import client
    from lastmile.workflow.pipeline import pipeline

    # 1. 登录
    print("=" * 60)
    print("场景 1：正常流程测试")
    print("=" * 60)

    print("\n[1/7] 登录 Clawith...")
    try:
        auth = await client.login(EMAIL, PASSWORD)
        print(f"  登录成功，token: {auth['access_token'][:20]}...")
    except Exception as e:
        print(f"  登录失败: {e}")
        sys.exit(1)

    # 2. 初始状态
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "agent_id": PLANNER_ID,
        "executor_id": EXECUTOR_ID,
        "fool_id": FOOL_ID,
        "requirement": REQUIREMENT,
        "phase": "start",
        "rework_count": 0,
        "max_reworks": 3,
        "rework_history": [],
        "plan_body": "",
        "report_body": "",
        "challenge_body": "",
        "plan_score": None,
        "result_score": None,
        "plan_session_id": "",
        "exec_session_id": "",
        "last_fail_reason": "",
    }

    # 3. 第一轮：跑到 human_approval interrupt
    print("\n[2/7] 启动流水线（plan_agent → check_plan → fool_challenge → human_approval）...")
    phases_seen = []
    try:
        async for event in pipeline.astream(initial_state, config, stream_mode="updates"):
            for node_name, updates in event.items():
                phase = updates.get("phase", "")
                if phase:
                    phases_seen.append(phase)
                print(f"  节点 [{node_name}] → phase={phase}")
    except Exception as e:
        # interrupt 会导致 stream 结束
        print(f"  流中断（预期行为）: {type(e).__name__}")

    print(f"  经过的阶段: {phases_seen}")

    # 验证到达了 human_approval
    snapshot = await pipeline.aget_state(config)
    print(f"\n[3/7] 检查中断状态...")
    print(f"  next: {snapshot.next}")
    print(f"  phase: {snapshot.values.get('phase')}")

    has_interrupt = len(snapshot.next) > 0
    if not has_interrupt:
        print("  错误：流水线没有在 human_approval 中断！")
        sys.exit(1)
    print("  human_approval 中断确认")

    # 4. 模拟人类审批：打 4 分通过
    print("\n[4/7] 模拟人类审批（4/5 通过）...")
    phases_seen_2 = []
    try:
        async for event in pipeline.astream(
            Command(resume={"score": 4, "feedback": "计划不错"}),
            config,
            stream_mode="updates",
        ):
            for node_name, updates in event.items():
                phase = updates.get("phase", "")
                if phase:
                    phases_seen_2.append(phase)
                print(f"  节点 [{node_name}] → phase={phase}")
    except Exception as e:
        print(f"  流中断（预期行为）: {type(e).__name__}")

    print(f"  经过的阶段: {phases_seen_2}")

    # 5. 检查到达 human_score
    snapshot2 = await pipeline.aget_state(config)
    print(f"\n[5/7] 检查执行后状态...")
    print(f"  next: {snapshot2.next}")
    print(f"  phase: {snapshot2.values.get('phase')}")

    has_interrupt_2 = len(snapshot2.next) > 0
    if not has_interrupt_2:
        print("  错误：流水线没有在 human_score 中断！")
        # 可能已经结束了，检查 phase
        if snapshot2.values.get("phase") == "done":
            print("  （流水线已完成，跳过评分步骤）")
        else:
            sys.exit(1)
    else:
        print("  human_score 中断确认")

    # 6. 模拟人类评分：打 4 分通过
    print("\n[6/7] 模拟人类评分（4/5 通过）...")
    phases_seen_3 = []
    if has_interrupt_2:
        try:
            async for event in pipeline.astream(
                Command(resume={"score": 4, "feedback": "执行结果满意"}),
                config,
                stream_mode="updates",
            ):
                for node_name, updates in event.items():
                    phase = updates.get("phase", "")
                    if phase:
                        phases_seen_3.append(phase)
                    print(f"  节点 [{node_name}] → phase={phase}")
        except Exception as e:
            print(f"  异常: {type(e).__name__}: {e}")

        print(f"  经过的阶段: {phases_seen_3}")

    # 7. 最终验证
    final = await pipeline.aget_state(config)
    print(f"\n[7/7] 最终状态验证")
    print(f"  phase: {final.values.get('phase')}")
    print(f"  plan_score: {final.values.get('plan_score')}")
    print(f"  result_score: {final.values.get('result_score')}")
    print(f"  rework_count: {final.values.get('rework_count')}")
    print(f"  next: {final.next}")

    # 断言
    ok = True
    if final.values.get("phase") != "done":
        print(f"\n  FAIL: 最终 phase 应为 'done'，实际为 '{final.values.get('phase')}'")
        ok = False
    if final.values.get("plan_score") != 4:
        print(f"  FAIL: plan_score 应为 4，实际为 {final.values.get('plan_score')}")
        ok = False
    if final.values.get("result_score") != 4:
        print(f"  FAIL: result_score 应为 4，实际为 {final.values.get('result_score')}")
        ok = False
    if len(final.next) != 0:
        print(f"  FAIL: 流水线应已结束，但 next={final.next}")
        ok = False

    print("\n" + "=" * 60)
    if ok:
        print("场景 1 测试通过")
    else:
        print("场景 1 测试失败")
    print("=" * 60)

    return ok


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
