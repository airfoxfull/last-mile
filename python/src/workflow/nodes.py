"""LangGraph 节点实现 — 调 Clawith API"""

import uuid
from src.clawith import client
from src.workflow.gates import check_plan, check_report
from src.workflow.state import State


async def plan_agent(state: State) -> dict:
    """节点1: 唤醒 Planner Agent 做规划"""
    agent_id = state["agent_id"]
    requirement = state["requirement"]
    rework_count = state.get("rework_count", 0)
    rework_history = state.get("rework_history", [])
    plan_body = state.get("plan_body", "")

    # 构建记忆上下文
    memory = ""
    if rework_count > 0:
        memory = (
            f"【历史记录 — 请务必阅读】\n"
            f"- 本任务已返工 {rework_count} 次\n"
            f"- 返工原因: {'; '.join(rework_history)}\n"
        )
        if plan_body:
            memory += f"- 上次 plan 摘要: {plan_body[:300]}\n"
        memory += "- 请根据以上反馈改进你的计划\n\n"

    # 写 memory.md 注入历史（Clawith 自动注入 system prompt）
    if memory:
        existing = await client.read_file(agent_id, "memory/memory.md")
        await client.write_file(agent_id, "memory/memory.md",
            existing + f"\n\n## 返工记录 (第{rework_count}次)\n{memory}")

    # 写 handoff 文档
    handoff = (
        f"# 任务交接\n\n"
        f"## 需求\n{requirement}\n\n"
        f"## 你的任务\n"
        f"请分析需求，制定执行计划。\n"
        f"计划必须包含：## 任务分析、## 执行步骤、## 风险评估、## 预算估算\n\n"
        f"## 约束\n- 只写计划，不要执行\n"
        f"- 把计划写入 workspace/plan.md\n"
    )
    await client.write_file(agent_id, "workspace/handoff.md", handoff)

    # 发消息给 Agent
    prompt = memory + (
        f"你现在处于【规划阶段】。请阅读 workspace/handoff.md，"
        f"然后把执行计划写入 workspace/plan.md。"
        f"计划必须包含：## 任务分析、## 执行步骤、## 风险评估、## 预算估算。"
        f"不要执行任何代码，只写计划。"
    )

    session_id = state.get("plan_session_id") or str(uuid.uuid4())
    print(f"[plan_agent] 唤醒 Planner {agent_id}（返工 #{rework_count}）")

    response = await client.send_message(agent_id, prompt, session_id)
    print(f"[plan_agent] Agent 回复: {str(response)[:200]}")

    return {"phase": "checking_plan", "plan_session_id": session_id}


async def check_plan_gate(state: State) -> dict:
    """节点2: 读 plan 文档，feature-forge 格式验证"""
    agent_id = state["agent_id"]
    rework_count = state.get("rework_count", 0)
    rework_history = state.get("rework_history", [])

    plan_body = ""
    try:
        plan_body = await client.read_file(agent_id, "workspace/plan.md")
    except Exception:
        pass

    if not plan_body:
        reason = "未检测到计划文档（workspace/plan.md）"
        print(f"[check_plan] ⚠️ {reason}")
        return {
            "plan_body": "",
            "phase": "plan_failed",
            "rework_count": rework_count + 1,
            "last_fail_reason": reason,
            "rework_history": rework_history + [reason],
        }

    gate = check_plan(plan_body)
    if not gate.ok:
        reason = f"格式不符，缺少: {'、'.join(gate.missing)}"
        print(f"[check_plan] ⚠️ {reason}")
        return {
            "plan_body": plan_body,
            "phase": "plan_failed",
            "rework_count": rework_count + 1,
            "last_fail_reason": reason,
            "rework_history": rework_history + [reason],
        }

    print("[check_plan] ✅ 门控1通过")
    return {"plan_body": plan_body, "phase": "plan_passed"}


async def fool_challenge(state: State) -> dict:
    """节点3: The Fool 辩论循环（可选）"""
    fool_id = state.get("fool_id", "")
    if not fool_id:
        print("[fool] 跳过（未配置 fool_id）")
        return {"phase": "awaiting_approval"}

    agent_id = state["agent_id"]
    plan_body = state.get("plan_body", "")

    # Fool 挑战
    challenge_prompt = (
        f"你是【挑战者】。找出以下计划的漏洞、风险和不合理之处：\n\n"
        f"{plan_body}\n\n"
        f"把挑战写入 workspace/challenge.md"
    )
    print(f"[fool] 唤醒 Fool Agent {fool_id}")
    await client.send_message(fool_id, challenge_prompt)

    challenge_body = ""
    try:
        challenge_body = await client.read_file(fool_id, "workspace/challenge.md")
    except Exception:
        pass

    if not challenge_body:
        print("[fool] Fool 未提交挑战文档，跳过")
        return {"challenge_body": "", "phase": "awaiting_approval"}

    # 原 Agent 回应
    response_prompt = (
        f"你的计划被挑战了：\n\n{challenge_body}\n\n"
        f"请更新 workspace/plan.md 回应这些质疑。"
    )
    await client.send_message(agent_id, response_prompt)

    updated_plan = plan_body
    try:
        updated_plan = await client.read_file(agent_id, "workspace/plan.md")
    except Exception:
        pass

    print("[fool] ✅ 辩论完成")
    return {"challenge_body": challenge_body, "plan_body": updated_plan, "phase": "awaiting_approval"}


async def human_approval(state: State) -> dict:
    """节点4: interrupt() 等人类打分"""
    from langgraph.types import interrupt

    print("[human_approval] 等待人类审批...")
    response = interrupt({
        "type": "plan_approval",
        "message": "请审批计划（1-5 分，>= 3 通过）",
        "plan_body": state.get("plan_body", "")[:500],
    })

    score = response.get("score", 0) if isinstance(response, dict) else 0
    feedback = response.get("feedback", "") if isinstance(response, dict) else ""
    print(f"[human_approval] 评分: {score}/5")

    rework_count = state.get("rework_count", 0)
    rework_history = state.get("rework_history", [])

    if score < 3:
        reason = f"计划被拒（{score}/5）: {feedback}"
        return {
            "plan_score": score,
            "phase": "plan_rejected",
            "rework_count": rework_count + 1,
            "last_fail_reason": reason,
            "rework_history": rework_history + [reason],
        }

    return {"plan_score": score, "phase": "executing"}


async def execute_agent(state: State) -> dict:
    """节点5: 唤醒 Executor Agent 执行"""
    executor_id = state["executor_id"]
    agent_id = state["agent_id"]
    plan_body = state.get("plan_body", "")
    plan_score = state.get("plan_score", 0)

    # 写执行 handoff
    handoff = (
        f"# 执行指令\n\n"
        f"## 已批准的计划（{plan_score}/5）\n{plan_body}\n\n"
        f"## 你的任务\n按计划执行，完成后把报告写入 workspace/report.md。\n"
        f"报告必须包含: ## 完成情况 和 ## 变更文件\n"
    )
    await client.write_file(executor_id, "workspace/handoff.md", handoff)

    prompt = f"计划已批准（{plan_score}/5）。请阅读 workspace/handoff.md，按计划执行，完成后写 workspace/report.md。"

    session_id = state.get("exec_session_id") or str(uuid.uuid4())
    print(f"[execute_agent] 唤醒 Executor {executor_id}")
    await client.send_message(executor_id, prompt, session_id)

    return {"phase": "checking_report", "exec_session_id": session_id}


async def check_report_gate(state: State) -> dict:
    """节点6: 读 report，code-reviewer 格式验证"""
    executor_id = state["executor_id"]
    rework_count = state.get("rework_count", 0)
    rework_history = state.get("rework_history", [])

    report_body = ""
    try:
        report_body = await client.read_file(executor_id, "workspace/report.md")
    except Exception:
        pass

    if not report_body:
        reason = "未检测到工作报告（workspace/report.md）"
        print(f"[check_report] ⚠️ {reason}")
        return {
            "report_body": "",
            "phase": "report_failed",
            "rework_count": rework_count + 1,
            "last_fail_reason": reason,
            "rework_history": rework_history + [reason],
        }

    gate = check_report(report_body)
    if not gate.ok:
        reason = f"报告格式不符，缺少: {'、'.join(gate.missing)}"
        print(f"[check_report] ⚠️ {reason}")

    print("[check_report] ✅ 门控3通过")
    return {"report_body": report_body, "phase": "report_passed"}


async def human_score(state: State) -> dict:
    """节点7: interrupt() 等人类评分结果"""
    from langgraph.types import interrupt

    print("[human_score] 等待人类评分...")
    response = interrupt({
        "type": "result_score",
        "message": "请评分执行结果（1-5 分，>= 3 通过）",
        "report_body": state.get("report_body", "")[:500],
    })

    score = response.get("score", 0) if isinstance(response, dict) else 0
    feedback = response.get("feedback", "") if isinstance(response, dict) else ""
    print(f"[human_score] 评分: {score}/5")

    rework_count = state.get("rework_count", 0)
    rework_history = state.get("rework_history", [])

    if score < 3:
        reason = f"结果不满意（{score}/5）: {feedback}"
        return {
            "result_score": score,
            "phase": "exec_rework",
            "rework_count": rework_count + 1,
            "last_fail_reason": reason,
            "rework_history": rework_history + [reason],
        }

    print(f"[human_score] ✅ 完成（计划 {state.get('plan_score')}/5，结果 {score}/5，返工 {rework_count} 次）")
    return {"result_score": score, "phase": "done"}
