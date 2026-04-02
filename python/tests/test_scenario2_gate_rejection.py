"""场景 2：门控拦截 + 返工

手动写一个格式不对的 plan 到 Planner workspace，然后直接调用
check_plan_gate 节点验证拦截逻辑。不需要真正唤醒 Agent。

同时测试 check_report_gate 的 bug 修复（之前 gate.ok=False 时会穿透）。
"""

import asyncio
import sys

# ── 配置 ──
EMAIL = "296105415@qq.com"
PASSWORD = "Aa123456"
PLANNER_ID = "92b0c2d0-88a1-46b1-aec2-cc9233fbc122"
EXECUTOR_ID = "d6122b5f-d7c6-445d-9ae4-2140c6ad6c7a"


async def test_check_plan_gate_rejects_bad_format():
    """测试 check_plan_gate：写一个缺少必需章节的 plan，验证门控拦截。"""
    from lastmile.clawith import client
    from lastmile.workflow.nodes import check_plan_gate

    print("-" * 50)
    print("测试 2a: check_plan_gate 拦截格式不对的 plan")
    print("-" * 50)

    # 写一个缺少 "## 风险评估" 和 "## 预算估算" 的 plan
    bad_plan = (
        "# 我的计划\n\n"
        "## 任务分析\n"
        "这是一个简单的任务，需要写一个函数。\n\n"
        "## 执行步骤\n"
        "1. 写代码\n"
        "2. 测试\n\n"
        "就这样，没有风险评估和预算估算。\n"
    )

    print(f"  写入格式不对的 plan（缺少 ## 风险评估、## 预算估算）...")
    await client.write_file(PLANNER_ID, "workspace/plan.md", bad_plan)

    # 验证写入成功
    readback = await client.read_file(PLANNER_ID, "workspace/plan.md")
    print(f"  回读确认: {len(readback)} 字")

    # 调用 check_plan_gate
    state = {
        "agent_id": PLANNER_ID,
        "executor_id": EXECUTOR_ID,
        "rework_count": 0,
        "rework_history": [],
    }

    print(f"  调用 check_plan_gate...")
    result = await check_plan_gate(state)

    print(f"  结果: phase={result.get('phase')}")
    print(f"  rework_count={result.get('rework_count')}")
    print(f"  last_fail_reason={result.get('last_fail_reason', '')}")

    ok = True
    if result.get("phase") != "plan_failed":
        print(f"  FAIL: phase 应为 'plan_failed'，实际为 '{result.get('phase')}'")
        ok = False
    if result.get("rework_count") != 1:
        print(f"  FAIL: rework_count 应为 1，实际为 {result.get('rework_count')}")
        ok = False

    fail_reason = result.get("last_fail_reason", "")
    if "风险评估" not in fail_reason or "预算估算" not in fail_reason:
        print(f"  FAIL: 失败原因应提到缺少的章节，实际为: {fail_reason}")
        ok = False

    if ok:
        print("  PASS")
    return ok


async def test_check_plan_gate_passes_good_format():
    """测试 check_plan_gate：写一个格式正确的 plan，验证门控通过。"""
    from lastmile.clawith import client
    from lastmile.workflow.nodes import check_plan_gate

    print("\n" + "-" * 50)
    print("测试 2b: check_plan_gate 通过格式正确的 plan")
    print("-" * 50)

    good_plan = (
        "# 斐波那契函数实现计划\n\n"
        "## 任务分析\n"
        "需要实现一个 fibonacci(n) 函数，返回第 n 个斐波那契数。\n"
        "需要包含单元测试覆盖边界情况。\n\n"
        "## 执行步骤\n"
        "1. 创建 fibonacci.py，实现递推算法\n"
        "2. 创建 test_fibonacci.py，覆盖 n=0,1,2,10 等\n"
        "3. 运行测试确认通过\n\n"
        "## 风险评估\n"
        "- 大数溢出：Python 原生支持大整数，风险低\n"
        "- 负数输入：需要处理边界\n\n"
        "## 预算估算\n"
        "- 预计 1 个 Agent 调用，约 500 token\n"
        "- 总耗时 < 2 分钟\n"
    )

    print(f"  写入格式正确的 plan...")
    await client.write_file(PLANNER_ID, "workspace/plan.md", good_plan)

    state = {
        "agent_id": PLANNER_ID,
        "executor_id": EXECUTOR_ID,
        "rework_count": 0,
        "rework_history": [],
    }

    print(f"  调用 check_plan_gate...")
    result = await check_plan_gate(state)

    print(f"  结果: phase={result.get('phase')}")

    ok = True
    if result.get("phase") != "plan_passed":
        print(f"  FAIL: phase 应为 'plan_passed'，实际为 '{result.get('phase')}'")
        ok = False
    else:
        print("  PASS")
    return ok


async def test_check_report_gate_rejects_bad_format():
    """测试 check_report_gate bug 修复：格式不对的 report 应被拦截。"""
    from lastmile.clawith import client
    from lastmile.workflow.nodes import check_report_gate

    print("\n" + "-" * 50)
    print("测试 2c: check_report_gate 拦截格式不对的 report（bug 修复验证）")
    print("-" * 50)

    bad_report = (
        "# 工作报告\n\n"
        "我完成了任务。代码写好了。\n"
        "没有按格式写完成情况和变更文件章节。\n"
    )

    print(f"  写入格式不对的 report（缺少 ## 完成情况、## 变更文件）...")
    await client.write_file(EXECUTOR_ID, "workspace/report.md", bad_report)

    state = {
        "agent_id": PLANNER_ID,
        "executor_id": EXECUTOR_ID,
        "rework_count": 0,
        "rework_history": [],
    }

    print(f"  调用 check_report_gate...")
    result = await check_report_gate(state)

    print(f"  结果: phase={result.get('phase')}")
    print(f"  rework_count={result.get('rework_count')}")

    ok = True
    if result.get("phase") != "report_failed":
        print(f"  FAIL: phase 应为 'report_failed'，实际为 '{result.get('phase')}'")
        print(f"  （这是之前的 bug — gate.ok=False 时穿透到 report_passed）")
        ok = False
    if result.get("rework_count") != 1:
        print(f"  FAIL: rework_count 应为 1，实际为 {result.get('rework_count')}")
        ok = False

    if ok:
        print("  PASS（bug 修复验证通过）")
    return ok


async def test_check_report_gate_passes_good_format():
    """测试 check_report_gate：格式正确的 report 应通过。"""
    from lastmile.clawith import client
    from lastmile.workflow.nodes import check_report_gate

    print("\n" + "-" * 50)
    print("测试 2d: check_report_gate 通过格式正确的 report")
    print("-" * 50)

    good_report = (
        "# 工作报告\n\n"
        "## 完成情况\n"
        "- fibonacci(n) 函数已实现，使用递推算法\n"
        "- 单元测试已编写，覆盖 n=0,1,2,10,20\n"
        "- 所有测试通过\n\n"
        "## 变更文件\n"
        "- fibonacci.py（新增）\n"
        "- test_fibonacci.py（新增）\n"
    )

    print(f"  写入格式正确的 report...")
    await client.write_file(EXECUTOR_ID, "workspace/report.md", good_report)

    state = {
        "agent_id": PLANNER_ID,
        "executor_id": EXECUTOR_ID,
        "rework_count": 0,
        "rework_history": [],
    }

    print(f"  调用 check_report_gate...")
    result = await check_report_gate(state)

    print(f"  结果: phase={result.get('phase')}")

    ok = True
    if result.get("phase") != "report_passed":
        print(f"  FAIL: phase 应为 'report_passed'，实际为 '{result.get('phase')}'")
        ok = False
    else:
        print("  PASS")
    return ok


async def test_pure_gate_functions():
    """测试纯函数 check_plan / check_report（不需要 Clawith）。"""
    from lastmile.workflow.gates import check_plan, check_report

    print("\n" + "-" * 50)
    print("测试 2e: 纯门控函数单元测试")
    print("-" * 50)

    ok = True

    # check_plan: 缺章节
    r1 = check_plan("## 任务分析\n一些内容\n## 执行步骤\n步骤")
    if r1.ok:
        print("  FAIL: 缺少 风险评估+预算估算 应失败")
        ok = False
    else:
        print(f"  check_plan 缺章节: ok={r1.ok}, missing={r1.missing} — PASS")

    # check_plan: 内容过短
    r2 = check_plan("太短了")
    if r2.ok:
        print("  FAIL: 内容过短应失败")
        ok = False
    else:
        print(f"  check_plan 过短: ok={r2.ok}, missing={r2.missing} — PASS")

    # check_plan: 全部通过
    full = (
        "## 任务分析\n分析内容\n## 执行步骤\n步骤内容\n"
        "## 风险评估\n风险内容\n## 预算估算\n预算内容\n"
    )
    r3 = check_plan(full)
    if not r3.ok:
        print(f"  FAIL: 完整 plan 应通过，missing={r3.missing}")
        ok = False
    else:
        print(f"  check_plan 完整: ok={r3.ok} — PASS")

    # check_report: 缺章节
    r4 = check_report("## 完成情况\n完成了一些事情，内容足够长")
    if r4.ok:
        print("  FAIL: 缺少 变更文件 应失败")
        ok = False
    else:
        print(f"  check_report 缺章节: ok={r4.ok}, missing={r4.missing} — PASS")

    # check_report: 全部通过
    r5 = check_report("## 完成情况\n任务已全部完成并通过测试\n## 变更文件\nfile.py")
    if not r5.ok:
        print(f"  FAIL: 完整 report 应通过，missing={r5.missing}")
        ok = False
    else:
        print(f"  check_report 完整: ok={r5.ok} — PASS")

    return ok


async def main():
    from lastmile.clawith import client

    print("=" * 60)
    print("场景 2：门控拦截 + 返工测试")
    print("=" * 60)

    # 登录
    print("\n[登录] Clawith...")
    try:
        auth = await client.login(EMAIL, PASSWORD)
        print(f"  登录成功，token: {auth['access_token'][:20]}...")
    except Exception as e:
        print(f"  登录失败: {e}")
        sys.exit(1)

    results = []

    # 纯函数测试（不依赖 Clawith 文件系统）
    results.append(("2e: 纯门控函数", await test_pure_gate_functions()))

    # 集成测试（依赖 Clawith 文件系统）
    results.append(("2a: plan 格式拦截", await test_check_plan_gate_rejects_bad_format()))
    results.append(("2b: plan 格式通过", await test_check_plan_gate_passes_good_format()))
    results.append(("2c: report 格式拦截(bug修复)", await test_check_report_gate_rejects_bad_format()))
    results.append(("2d: report 格式通过", await test_check_report_gate_passes_good_format()))

    # 汇总
    print("\n" + "=" * 60)
    print("场景 2 测试汇总")
    print("=" * 60)
    all_ok = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {status}: {name}")
        if not passed:
            all_ok = False

    print("\n" + ("全部通过" if all_ok else "有测试失败"))
    print("=" * 60)
    return all_ok


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
