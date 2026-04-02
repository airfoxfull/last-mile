"""场景 6：多流水线并发 + checkpoint 隔离

验证：
1. 3 个不同 thread_id 的流水线可以同时存在
2. pipeline.aget_state(config) 返回正确的独立状态
3. 一个流水线的返工不影响另一个
4. checkpoint（MemorySaver）正确隔离
5. 不同评分独立记录

策略：顺序启动 3 条流水线到 human_approval interrupt，
然后交叉审批（不同分数），验证状态隔离。
"""

import asyncio
import sys

sys.path.insert(0, "E:/last-mile-repo/python")

from langgraph.types import Command
from lastmile.clawith import client
from lastmile.workflow.pipeline import pipeline

# ── 配置 ──
EMAIL = "296105415@qq.com"
PASSWORD = "Aa123456"
PLANNER_ID = "92b0c2d0-88a1-46b1-aec2-cc9233fbc122"
EXECUTOR_ID = "d6122b5f-d7c6-445d-9ae4-2140c6ad6c7a"

PIPELINES = [
    {
        "thread_id": "test-concurrent-a",
        "requirement": "写一个 Python 函数 fibonacci(n)，返回第 n 个斐波那契数",
        "plan_score": 4,   # 通过
        "result_score": 5,
    },
    {
        "thread_id": "test-concurrent-b",
        "requirement": "写一个 Python 脚本，读取 CSV 文件并生成柱状图",
        "plan_score": 2,   # 拒绝 → 返工
        "result_score": None,  # 返工后再打分
    },
    {
        "thread_id": "test-concurrent-c",
        "requirement": "写一个 REST API 服务，提供用户注册和登录功能",
        "plan_score": 3,   # 刚好通过
        "result_score": 4,
    },
]

PASS = "[PASS]"
FAIL = "[FAIL]"
results = []


def check(name: str, condition: bool, detail: str = ""):
    tag = PASS if condition else FAIL
    msg = f"  {tag} {name}" + (f" — {detail}" if detail else "")
    print(msg)
    results.append((name, condition))


def make_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def make_initial(p: dict) -> dict:
    return {
        "agent_id": PLANNER_ID,
        "executor_id": EXECUTOR_ID,
        "fool_id": "",  # 不启用 Fool，加速测试
        "requirement": p["requirement"],
        "phase": "start",
        "rework_count": 0,
        "max_reworks": 5,
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


async def stream_to_interrupt(input_val, config, label: str):
    """运行流水线直到 interrupt，打印节点经过。"""
    async for chunk in pipeline.astream(input_val, config, stream_mode="updates"):
        if isinstance(chunk, dict):
            for node, update in chunk.items():
                phase = update.get("phase", "") if isinstance(update, dict) else ""
                print(f"  [{label}][{node}] -> {phase}")


async def main():
    print("=" * 60)
    print("场景 6：多流水线并发 + checkpoint 隔离")
    print("=" * 60)

    # ── 登录 ──
    print("\n[登录] Clawith...")
    await client.login(EMAIL, PASSWORD)
    print("[登录] 成功\n")

    configs = {p["thread_id"]: make_config(p["thread_id"]) for p in PIPELINES}

    # ================================================================
    # Phase 1: 顺序启动 3 条流水线，各自跑到 human_approval interrupt
    # ================================================================
    print("--- Phase 1: 顺序启动 3 条流水线 ---\n")

    for p in PIPELINES:
        tid = p["thread_id"]
        print(f"  启动 [{tid}]: {p['requirement'][:30]}...")
        await stream_to_interrupt(make_initial(p), configs[tid], tid)
        print()

    # ── 验证 1: 3 条流水线都在 human_approval interrupt ──
    print("--- 验证 1: 3 条流水线都在 interrupt ---")
    for p in PIPELINES:
        tid = p["thread_id"]
        state = await pipeline.aget_state(configs[tid])
        at_interrupt = bool(state.next)
        phase = state.values.get("phase")
        check(
            f"{tid}-在 interrupt",
            at_interrupt and phase == "awaiting_approval",
            f"phase={phase}, next={state.next}",
        )

    # ── 验证 2: 状态独立 — requirement 各不相同 ──
    print("\n--- 验证 2: 状态独立 — requirement 各不相同 ---")
    for p in PIPELINES:
        tid = p["thread_id"]
        state = await pipeline.aget_state(configs[tid])
        req = state.values.get("requirement", "")
        check(
            f"{tid}-requirement 正确",
            p["requirement"] in req,
            f"got: {req[:40]}...",
        )

    # ================================================================
    # Phase 2: 交叉审批 — 不同分数
    # Pipeline A: 4 分通过
    # Pipeline B: 2 分拒绝（触发返工）
    # Pipeline C: 3 分通过
    # ================================================================
    print("\n--- Phase 2: 交叉审批（不同分数） ---\n")

    # B 先拒绝（2 分）
    tid_b = PIPELINES[1]["thread_id"]
    print(f"  [{tid_b}] 打 2 分拒绝...")
    await stream_to_interrupt(
        Command(resume={"score": 2, "feedback": "计划太粗糙"}),
        configs[tid_b], tid_b,
    )

    # A 通过（4 分）
    tid_a = PIPELINES[0]["thread_id"]
    print(f"\n  [{tid_a}] 打 4 分通过...")
    await stream_to_interrupt(
        Command(resume={"score": 4, "feedback": "计划不错"}),
        configs[tid_a], tid_a,
    )

    # C 通过（3 分）
    tid_c = PIPELINES[2]["thread_id"]
    print(f"\n  [{tid_c}] 打 3 分通过...")
    await stream_to_interrupt(
        Command(resume={"score": 3, "feedback": "勉强可以"}),
        configs[tid_c], tid_c,
    )

    # ── 验证 3: 各流水线状态独立 ──
    print("\n--- 验证 3: 审批后状态独立 ---")

    state_a = await pipeline.aget_state(configs[tid_a])
    state_b = await pipeline.aget_state(configs[tid_b])
    state_c = await pipeline.aget_state(configs[tid_c])

    # A: plan_score=4, 应该在执行阶段或 human_score interrupt
    check(
        f"{tid_a}-plan_score=4",
        state_a.values.get("plan_score") == 4,
        f"got {state_a.values.get('plan_score')}",
    )

    # B: plan_score=2, 应该返工后又到了 interrupt
    check(
        f"{tid_b}-plan_score=2（被拒）",
        state_b.values.get("plan_score") == 2,
        f"got {state_b.values.get('plan_score')}",
    )
    rework_b = state_b.values.get("rework_count", 0)
    check(
        f"{tid_b}-rework_count > 0",
        rework_b > 0,
        f"rework_count={rework_b}",
    )

    # C: plan_score=3, 应该在执行阶段或 human_score interrupt
    check(
        f"{tid_c}-plan_score=3",
        state_c.values.get("plan_score") == 3,
        f"got {state_c.values.get('plan_score')}",
    )

    # ── 验证 4: B 的返工不影响 A 和 C ──
    print("\n--- 验证 4: B 的返工不影响 A 和 C ---")
    rework_a = state_a.values.get("rework_count", 0)
    rework_c = state_c.values.get("rework_count", 0)

    # A 和 C 的 rework_count 应该是 0（只有门控可能加过，但不应被 B 影响）
    check(
        f"{tid_a}-rework 不受 B 影响",
        rework_a == 0,
        f"rework_count={rework_a}",
    )
    check(
        f"{tid_c}-rework 不受 B 影响",
        rework_c == 0,
        f"rework_count={rework_c}",
    )

    # ================================================================
    # Phase 3: 完成 A 和 C（打 result_score），B 返工后通过
    # ================================================================
    print("\n--- Phase 3: 完成剩余流水线 ---\n")

    # A: 如果在 human_score interrupt，打 5 分
    if state_a.next:
        print(f"  [{tid_a}] 打 result_score=5...")
        await stream_to_interrupt(
            Command(resume={"score": 5, "feedback": "完美"}),
            configs[tid_a], tid_a,
        )

    # C: 如果在 human_score interrupt，打 4 分
    if state_c.next:
        print(f"\n  [{tid_c}] 打 result_score=4...")
        await stream_to_interrupt(
            Command(resume={"score": 4, "feedback": "不错"}),
            configs[tid_c], tid_c,
        )

    # B: 返工后应该又到了 human_approval，打 4 分通过
    if state_b.next:
        print(f"\n  [{tid_b}] 返工后打 4 分通过...")
        await stream_to_interrupt(
            Command(resume={"score": 4, "feedback": "改进后可以"}),
            configs[tid_b], tid_b,
        )

    # B: 如果到了 human_score，打 3 分
    state_b2 = await pipeline.aget_state(configs[tid_b])
    if state_b2.next:
        print(f"\n  [{tid_b}] 打 result_score=3...")
        await stream_to_interrupt(
            Command(resume={"score": 3, "feedback": "勉强通过"}),
            configs[tid_b], tid_b,
        )

    # ── 验证 5: 最终状态完全独立 ──
    print("\n--- 验证 5: 最终状态完全独立 ---")

    final_a = await pipeline.aget_state(configs[tid_a])
    final_b = await pipeline.aget_state(configs[tid_b])
    final_c = await pipeline.aget_state(configs[tid_c])

    # A: plan_score=4, result_score=5, rework_count=0
    check(f"{tid_a}-最终 plan_score=4",
          final_a.values.get("plan_score") == 4,
          f"got {final_a.values.get('plan_score')}")
    check(f"{tid_a}-最终 result_score=5",
          final_a.values.get("result_score") == 5,
          f"got {final_a.values.get('result_score')}")
    check(f"{tid_a}-最终 rework_count=0",
          final_a.values.get("rework_count", -1) == 0,
          f"got {final_a.values.get('rework_count')}")

    # B: plan_score=4（第二次审批）, rework_count > 0
    check(f"{tid_b}-最终 plan_score=4（返工后）",
          final_b.values.get("plan_score") == 4,
          f"got {final_b.values.get('plan_score')}")
    check(f"{tid_b}-最终 rework_count > 0",
          final_b.values.get("rework_count", 0) > 0,
          f"got {final_b.values.get('rework_count')}")

    # C: plan_score=3, result_score=4, rework_count=0
    check(f"{tid_c}-最终 plan_score=3",
          final_c.values.get("plan_score") == 3,
          f"got {final_c.values.get('plan_score')}")
    check(f"{tid_c}-最终 result_score=4",
          final_c.values.get("result_score") == 4,
          f"got {final_c.values.get('result_score')}")
    check(f"{tid_c}-最终 rework_count=0",
          final_c.values.get("rework_count", -1) == 0,
          f"got {final_c.values.get('rework_count')}")

    # ── 验证 6: 流水线都已结束（或 B 可能还在跑） ──
    print("\n--- 验证 6: 流水线终态 ---")
    for label, final in [("A", final_a), ("C", final_c)]:
        tid = f"test-concurrent-{label.lower()}"
        phase = final.values.get("phase")
        done = phase == "done" and len(final.next) == 0
        check(f"{tid}-已完成", done, f"phase={phase}, next={final.next}")

    # B 可能还没完成（取决于返工后的执行结果）
    phase_b = final_b.values.get("phase")
    b_progressed = phase_b in ("done", "checking_report", "report_passed",
                                "report_failed", "exec_rework") or bool(final_b.next)
    check(f"{tid_b}-有进展", b_progressed, f"phase={phase_b}")

    # ================================================================
    # 汇总
    # ================================================================
    print("\n" + "=" * 60)
    passed_count = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"场景 6 结果: {passed_count}/{total} 通过")
    if passed_count < total:
        for name, ok in results:
            if not ok:
                print(f"  FAILED: {name}")
    print("=" * 60)

    return passed_count == total


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
