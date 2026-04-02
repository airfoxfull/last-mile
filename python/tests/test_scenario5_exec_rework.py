"""场景 5：执行阶段返工

验证：
1. Planner 正常通过门控 + 人类审批 (score=4)
2. 手动写入格式不对的 report -> check_report_gate 正确拦截
3. Executor 返工后 report 通过门控
4. 人类评分 score=2 拒绝 -> 再次返工
5. 人类评分 score=4 通过 -> phase=done
6. rework_count 在执行阶段正确递增

策略：
- 编译一个带 interrupt_before=["check_report"] 的 pipeline
- 这样每次 check_report 前都能注入/修改 report 内容
"""

import asyncio
import sys
import uuid

sys.path.insert(0, "E:/last-mile-repo/python")

from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver
from lastmile.clawith import client
from lastmile.workflow.pipeline import builder
from lastmile.workflow.state import State

PLANNER_ID = "92b0c2d0-88a1-46b1-aec2-cc9233fbc122"
EXECUTOR_ID = "d6122b5f-d7c6-445d-9ae4-2140c6ad6c7a"
THREAD_ID = f"test-scenario5-{uuid.uuid4().hex[:8]}"

PASS = "[PASS]"
FAIL = "[FAIL]"
results = []


def check(name: str, condition: bool, detail: str = ""):
    tag = PASS if condition else FAIL
    msg = f"  {tag} {name}" + (f" — {detail}" if detail else "")
    print(msg)
    results.append((name, condition))


async def stream_to_stop(graph, input_val, config):
    """运行 graph 直到 interrupt 或结束，打印节点更新"""
    async for chunk in graph.astream(input_val, config, stream_mode="updates"):
        if isinstance(chunk, dict):
            for node, update in chunk.items():
                phase = update.get("phase", "") if isinstance(update, dict) else ""
                print(f"  [{node}] -> {phase}")
    return await graph.aget_state(config)


async def main():
    print(f"=== 场景 5：执行阶段返工 (thread={THREAD_ID}) ===\n")

    # 登录
    await client.login("296105415@qq.com", "Aa123456")
    print("登录成功\n")

    # 编译带 interrupt_before=["check_report"] 的 pipeline
    # 这样每次 check_report 前我们都能注入/修改 report
    checkpointer = MemorySaver()
    graph = builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["check_report"],
    )

    config = {"configurable": {"thread_id": THREAD_ID}}
    initial = {
        "agent_id": PLANNER_ID,
        "executor_id": EXECUTOR_ID,
        "fool_id": "",
        "requirement": "写一个 Python 脚本，读取 JSON 文件并输出统计摘要",
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

    # ══════════════════════════════════════════════════
    # Step 1: 规划 → 门控 → 等待审批 (human_approval interrupt)
    # ══════════════════════════════════════════════════
    print("--- Step 1: 规划 + 门控 → 等待审批 ---")
    state = await stream_to_stop(graph, initial, config)
    phase = state.values.get("phase")
    print(f"\n  阶段: {phase}, next: {state.next}")
    check("S1-plan 通过门控等待审批",
          bool(state.next) and phase == "awaiting_approval",
          f"phase={phase}")

    # ══════════════════════════════════════════════════
    # Step 2: 人类打 4 分通过 plan → executor 执行 → 暂停在 check_report 前
    # ══════════════════════════════════════════════════
    print("\n--- Step 2: 审批通过 → executor 执行 → 暂停在 check_report 前 ---")
    state = await stream_to_stop(graph,
        Command(resume={"score": 4, "feedback": "计划可以"}), config)
    phase = state.values.get("phase")
    plan_score = state.values.get("plan_score")
    rework_count_s2 = state.values.get("rework_count", 0)
    print(f"\n  阶段: {phase}, plan_score: {plan_score}, next: {state.next}")
    check("S2-plan_score=4", plan_score == 4, f"{plan_score}")
    check("S2-暂停在 check_report 前",
          state.next and "check_report" in state.next,
          f"next={state.next}")

    # ══════════════════════════════════════════════════
    # Step 3: 写入格式不对的 report → 恢复 → check_report 拦截
    # ══════════════════════════════════════════════════
    print("\n--- Step 3: 注入坏 report → check_report 应拦截 ---")
    bad_report = (
        "# 工作报告\n\n"
        "我完成了任务，代码已经写好了。\n"
        "主要修改了 main.py 文件。\n"
        "没有什么问题。\n"
    )
    await client.write_file(EXECUTOR_ID, "workspace/report.md", bad_report)
    print("  已写入坏 report（缺少 ## 完成情况 和 ## 变更文件）")

    # 恢复执行 → check_report 读到坏 report → 失败 → 路由回 execute_agent
    # → execute_agent 执行 → 再次暂停在 check_report 前
    state = await stream_to_stop(graph, None, config)
    phase = state.values.get("phase")
    rework_count_s3 = state.values.get("rework_count", 0)
    rework_history = state.values.get("rework_history", [])
    last_fail = state.values.get("last_fail_reason", "")
    print(f"\n  阶段: {phase}, rework_count: {rework_count_s3}")
    print(f"  last_fail_reason: {last_fail}")
    print(f"  rework_history: {rework_history}")

    check("S3-check_report 拦截坏 report",
          rework_count_s3 > rework_count_s2,
          f"rework {rework_count_s2} -> {rework_count_s3}")
    check("S3-返工历史包含报告格式问题",
          any("报告格式不符" in h or "未检测到" in h for h in rework_history),
          str(rework_history[-1]) if rework_history else "empty")
    check("S3-再次暂停在 check_report 前（返工后）",
          bool(state.next) and "check_report" in state.next,
          f"next={state.next}")

    # ══════════════════════════════════════════════════
    # Step 4: 不注入坏 report，让真实 report 通过 → human_score interrupt
    # ══════════════════════════════════════════════════
    print("\n--- Step 4: 让返工后的 report 通过门控 → human_score ---")
    # 恢复执行 check_report（这次用 executor 返工后写的 report）
    state = await stream_to_stop(graph, None, config)
    phase = state.values.get("phase")
    report_body = state.values.get("report_body", "")
    print(f"\n  阶段: {phase}, next: {state.next}")
    print(f"  report 长度: {len(report_body)}")

    # 如果 report 仍然没通过门控（Agent 返工后可能还是格式不对），
    # 手动写一个合格的 report 让流程继续
    if phase == "report_failed" or (state.next and "check_report" in (state.next or [])):
        print("  返工后 report 仍未通过，手动写入合格 report")
        good_report = (
            "# 工作报告\n\n"
            "## 完成情况\n"
            "已完成 JSON 文件读取和统计摘要输出功能。\n\n"
            "## 变更文件\n"
            "- main.py: 新增 JSON 解析和统计逻辑\n"
            "- utils.py: 新增辅助函数\n"
        )
        await client.write_file(EXECUTOR_ID, "workspace/report.md", good_report)
        # 如果当前在 execute_agent 后暂停，直接恢复让 check_report 跑
        if state.next and "check_report" in state.next:
            state = await stream_to_stop(graph, None, config)
            phase = state.values.get("phase")
        # 如果路由回了 execute_agent，需要再跑一轮
        elif phase == "report_failed":
            state = await stream_to_stop(graph, None, config)
            # 这会跑 execute_agent -> 暂停在 check_report 前
            # 再写入好 report
            await client.write_file(EXECUTOR_ID, "workspace/report.md", good_report)
            state = await stream_to_stop(graph, None, config)
            phase = state.values.get("phase")

    report_passed = phase == "report_passed" and bool(state.next)
    check("S4-report 通过门控到 human_score",
          report_passed,
          f"phase={phase}, next={state.next}")

    # ══════════════════════════════════════════════════
    # Step 5: 人类评分 score=2 拒绝 → 返工
    # ══════════════════════════════════════════════════
    print("\n--- Step 5: 人类评分 2 分拒绝 → 返工 ---")
    rework_before_reject = state.values.get("rework_count", 0)
    state = await stream_to_stop(graph,
        Command(resume={"score": 2, "feedback": "结果太粗糙，缺少错误处理"}), config)
    phase = state.values.get("phase")
    rework_count_s5 = state.values.get("rework_count", 0)
    rework_history = state.values.get("rework_history", [])
    print(f"\n  阶段: {phase}, rework_count: {rework_count_s5}")
    print(f"  rework_history: {rework_history}")

    check("S5-score<3 路由回 execute_agent",
          rework_count_s5 > rework_before_reject,
          f"rework {rework_before_reject} -> {rework_count_s5}")
    check("S5-返工历史包含评分拒绝",
          any("不满意" in h for h in rework_history),
          str(rework_history[-1]) if rework_history else "empty")
    check("S5-暂停在 check_report 前（评分拒绝返工后）",
          bool(state.next) and "check_report" in (state.next or []),
          f"next={state.next}")

    # ══════════════════════════════════════════════════
    # Step 6: 写入合格 report → 通过门控 → 人类评分 4 分 → done
    # ══════════════════════════════════════════════════
    print("\n--- Step 6: 合格 report → 人类评分 4 分 → 完成 ---")
    # 写入合格 report 确保通过
    good_report_final = (
        "# 工作报告\n\n"
        "## 完成情况\n"
        "已完成全部功能，包含错误处理和边界检查。\n\n"
        "## 变更文件\n"
        "- main.py: JSON 解析、统计、错误处理\n"
        "- utils.py: 辅助函数\n"
        "- test_main.py: 单元测试\n"
    )
    await client.write_file(EXECUTOR_ID, "workspace/report.md", good_report_final)

    # 恢复 check_report
    state = await stream_to_stop(graph, None, config)
    phase = state.values.get("phase")
    print(f"\n  check_report 后阶段: {phase}, next: {state.next}")
    check("S6-report 通过门控", phase == "report_passed",
          f"phase={phase}")

    # 人类评分 4 分通过
    print("  人类评分 4 分...")
    state = await stream_to_stop(graph,
        Command(resume={"score": 4, "feedback": "返工后结果满意"}), config)
    final_phase = state.values.get("phase")
    result_score = state.values.get("result_score")
    final_rework = state.values.get("rework_count", 0)
    print(f"\n  最终阶段: {final_phase}, result_score: {result_score}")
    print(f"  总返工次数: {final_rework}")

    check("S6-最终 phase=done", final_phase == "done",
          f"phase={final_phase}")
    check("S6-result_score=4", result_score == 4,
          f"result_score={result_score}")
    check("S6-总返工次数 >= 2", final_rework >= 2,
          f"rework_count={final_rework}")

    # ══════════════════════════════════════════════════
    # 汇总
    # ══════════════════════════════════════════════════
    print("\n" + "=" * 60)
    passed_count = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"场景 5 结果: {passed_count}/{total} 通过")
    if passed_count < total:
        for name, ok in results:
            if not ok:
                print(f"  FAILED: {name}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
