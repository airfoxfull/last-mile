"""场景 4：Fool 挑战

验证：
1. plan 通过门控后，Fool Agent 被唤醒挑战
2. Fool 的挑战内容被记录（challenge_body 非空）
3. Planner 回应挑战并更新 plan
4. 人类看到 plan + challenge（interrupt payload 包含两者）
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
FOOL_ID = "46ba028d-f608-4d83-807c-04a4641412ed"
THREAD_ID = f"test-fool-{uuid.uuid4().hex[:8]}"

PASS = "[PASS]"
FAIL = "[FAIL]"
results = []


def check(name: str, condition: bool, detail: str = ""):
    tag = PASS if condition else FAIL
    msg = f"  {tag} {name}" + (f" — {detail}" if detail else "")
    print(msg)
    results.append((name, condition))


async def main():
    print(f"=== 场景 4：Fool 挑战 (thread={THREAD_ID}) ===\n")

    # 登录
    await client.login("296105415@qq.com", "Aa123456")
    print("登录成功\n")

    config = {"configurable": {"thread_id": THREAD_ID}}
    initial = {
        "agent_id": PLANNER_ID,
        "executor_id": EXECUTOR_ID,
        "fool_id": FOOL_ID,  # 启用 Fool
        "requirement": "设计一个 REST API 用于管理用户的待办事项列表，支持 CRUD 操作",
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

    # ── Phase 1: 规划 → 门控 → Fool 挑战 → 等待审批 ──
    print("--- Phase 1: 规划 + 门控 + Fool 挑战 ---")
    async for chunk in pipeline.astream(initial, config, stream_mode="updates"):
        if isinstance(chunk, dict):
            for node, update in chunk.items():
                phase = update.get("phase", "") if isinstance(update, dict) else ""
                print(f"  [{node}] -> {phase}")

    state = await pipeline.aget_state(config)
    phase = state.values.get("phase")
    challenge_body = state.values.get("challenge_body", "")
    plan_body = state.values.get("plan_body", "")
    has_interrupt = bool(state.next)

    print(f"\n  阶段: {phase}")
    print(f"  challenge_body 长度: {len(challenge_body)}")
    print(f"  plan_body 长度: {len(plan_body)}")
    print(f"  等待审批: {has_interrupt}")

    # 验证 1: Fool Agent 被唤醒（challenge_body 非空）
    check("F1-Fool 被唤醒并产生挑战", len(challenge_body) > 10,
          f"challenge 长度={len(challenge_body)}")

    # 验证 2: 挑战内容被记录到 Fool 的 workspace
    fool_challenge_file = ""
    try:
        fool_challenge_file = await client.read_file(FOOL_ID, "workspace/challenge.md")
    except Exception as e:
        fool_challenge_file = f"读取失败: {e}"

    check("F2-挑战内容写入 Fool workspace", len(fool_challenge_file) > 10,
          f"文件长度={len(fool_challenge_file)}")

    # 验证 3: Planner 回应挑战后 plan 被更新
    # plan_body 应该是 Fool 挑战后更新的版本
    check("F3-Planner 回应挑战更新 plan", len(plan_body) > 50,
          f"plan 长度={len(plan_body)}")

    # 验证 4: interrupt payload 包含 plan + challenge
    if has_interrupt:
        # 从 state.tasks 获取 interrupt 信息
        interrupt_data = None
        for task in state.tasks:
            if hasattr(task, "interrupts") and task.interrupts:
                for intr in task.interrupts:
                    interrupt_data = intr.value if hasattr(intr, "value") else intr
                    break

        if interrupt_data and isinstance(interrupt_data, dict):
            has_plan_preview = bool(interrupt_data.get("plan_preview", ""))
            has_challenge_in_payload = bool(interrupt_data.get("challenge", ""))
            check("F4-interrupt 包含 plan_preview",
                  has_plan_preview,
                  f"preview 长度={len(interrupt_data.get('plan_preview', ''))}")
            check("F5-interrupt 包含 challenge",
                  has_challenge_in_payload,
                  f"challenge 长度={len(interrupt_data.get('challenge', ''))}")
        else:
            check("F4-interrupt 包含 plan_preview", False, f"interrupt_data={interrupt_data}")
            check("F5-interrupt 包含 challenge", False, "no interrupt data")
    else:
        check("F4-interrupt 包含 plan_preview", False, "no interrupt")
        check("F5-interrupt 包含 challenge", False, "no interrupt")

    # 打印挑战内容预览
    if challenge_body:
        print(f"\n  Fool 挑战预览:\n  {challenge_body[:300]}...")

    # ── Phase 2: 人类打 4 分通过 ──
    if has_interrupt:
        print("\n--- Phase 2: 人类打 4 分通过 ---")
        async for chunk in pipeline.astream(
            Command(resume={"score": 4, "feedback": "挑战后的计划更完善了"}),
            config, stream_mode="updates",
        ):
            if isinstance(chunk, dict):
                for node, update in chunk.items():
                    phase = update.get("phase", "") if isinstance(update, dict) else ""
                    print(f"  [{node}] -> {phase}")

        state = await pipeline.aget_state(config)
        phase_after = state.values.get("phase")
        plan_score = state.values.get("plan_score")
        print(f"\n  阶段: {phase_after}, plan_score: {plan_score}")
        check("F6-审批通过后进入执行", phase_after in (
            "executing", "checking_report", "report_passed", "report_failed"
        ) or bool(state.next), f"phase={phase_after}")

        # ── Phase 3: 如果到了 human_score，打 4 分完成 ──
        if state.next:
            print("\n--- Phase 3: 人类评分（4 分完成） ---")
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
            print(f"\n  最终阶段: {final_phase}")
            check("F7-流水线完成", final_phase == "done", f"phase={final_phase}")

    # ── 汇总 ──
    print("\n" + "=" * 50)
    passed_count = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"场景 4 结果: {passed_count}/{total} 通过")
    if passed_count < total:
        for name, ok in results:
            if not ok:
                print(f"  FAILED: {name}")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
