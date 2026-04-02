"""LangGraph 节点实现 — 调 Clawith API"""

import uuid
from lastmile.clawith import client
from lastmile.workflow.gates import check_plan, check_report
from lastmile.workflow.state import State


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

    # 写 memory.md 注入历史
    if memory:
        try:
            existing = await client.read_file(agent_id, "memory/memory.md")
        except Exception:
            existing = ""
        await client.write_file(agent_id, "memory/memory.md",
            existing + f"\n\n## 返工记录 (第{rework_count}次)\n{memory}")

    # 发消息给 Agent，让它直接在回复中输出计划
    prompt = memory + (
        f"你现在处于【规划阶段】。\n\n"
        f"## 需求\n{requirement}\n\n"
        f"请直接输出执行计划，格式必须包含以下四个章节：\n"
        f"## 任务分析\n## 执行步骤\n## 风险评估\n## 预算估算\n\n"
        f"不要执行任何代码，只输出计划文档。"
    )

    session_id = state.get("plan_session_id") or str(uuid.uuid4())
    print(f"[plan_agent] 唤醒 Planner {agent_id}（返工 #{rework_count}）")

    reply = await client.send_message(agent_id, prompt, session_id)
    print(f"[plan_agent] 收到回复 ({len(reply)} 字)")

    # 不覆盖 workspace/plan.md — Agent 可能已通过 write_file 工具写入了
    # 只在 Agent 没用工具写的情况下，用回复内容写入
    try:
        existing_plan = await client.read_file(agent_id, "workspace/plan.md")
    except Exception:
        existing_plan = ""

    if not existing_plan or len(existing_plan) < 50:
        # Agent 没写或写得太短，用回复内容
        if reply and len(reply) > 50:
            await client.write_file(agent_id, "workspace/plan.md", reply)

    return {"phase": "checking_plan", "plan_session_id": session_id}


async def check_plan_gate(state: State) -> dict:
    """节点2: 读 plan，feature-forge 格式验证"""
    agent_id = state["agent_id"]
    rework_count = state.get("rework_count", 0)
    rework_history = state.get("rework_history", [])

    plan_body = ""
    try:
        plan_body = await client.read_file(agent_id, "workspace/plan.md")
    except Exception:
        pass

    if not plan_body:
        reason = "未检测到计划文档"
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

    print("[check_plan] ✅ 门控通过")
    return {"plan_body": plan_body, "phase": "plan_passed"}


async def fool_challenge(state: State) -> dict:
    """节点3: The Fool 辩论循环 — 挑战 plan，最多 3 轮收敛"""
    fool_id = state.get("fool_id", "")
    if not fool_id:
        print("[fool] 跳过（未配置）")
        return {"phase": "awaiting_approval"}

    agent_id = state["agent_id"]
    plan_body = state.get("plan_body", "")
    requirement = state.get("requirement", "")
    max_rounds = 3
    debate_log: list[dict] = []

    for round_num in range(1, max_rounds + 1):
        print(f"[fool] 第 {round_num}/{max_rounds} 轮辩论")

        # ── Fool 挑战 plan ──
        challenge_prompt = (
            f"你是【The Fool — 批判性思维挑战者】。第 {round_num} 轮。\n\n"
            f"## 原始需求\n{requirement}\n\n"
            f"## 当前计划\n{plan_body}\n\n"
            f"请从以下维度挑战这个计划：\n"
            f"1. **假设审查**：计划中有哪些未经验证的假设？\n"
            f"2. **风险盲区**：有哪些被忽略的风险或失败模式？\n"
            f"3. **执行漏洞**：执行步骤是否有遗漏或顺序不当？\n"
            f"4. **预算合理性**：预算估算是否合理？\n\n"
            f"要求：\n"
            f"- 每个质疑必须具体，不能泛泛而谈\n"
            f"- 指出问题的同时给出建设性建议\n"
            f"- 最后标注【核心争议点】— 你认为最关键的 1-3 个问题\n"
        )

        challenge = await client.send_message(fool_id, challenge_prompt)
        print(f"[fool] Fool 挑战 ({len(challenge)} 字)")

        # ── Planner 回应挑战 ──
        response_prompt = (
            f"你的计划被 The Fool 挑战了（第 {round_num} 轮）。\n\n"
            f"## Fool 的质疑\n{challenge[:2000]}\n\n"
            f"请逐条回应：\n"
            f"- 如果质疑合理 → 修改计划，说明改了什么\n"
            f"- 如果质疑不合理 → 反驳，给出理由\n\n"
            f"最后输出【更新后的完整计划】（保持四个章节格式）。\n"
            f"并标注【已解决的争议】和【仍有分歧的争议】。"
        )

        response = await client.send_message(agent_id, response_prompt,
                                              state.get("plan_session_id"))
        print(f"[fool] Planner 回应 ({len(response)} 字)")

        debate_log.append({
            "round": round_num,
            "challenge": challenge[:1000],
            "response": response[:1000],
        })

        # 更新 plan
        if response and len(response) > 100:
            plan_body = response
            await client.write_file(agent_id, "workspace/plan.md", response)

        # ── 收敛判断 ──
        # 如果 Planner 的回应中包含"仍有分歧"相关内容少于 100 字，认为已收敛
        if "仍有分歧" not in response or round_num == max_rounds:
            print(f"[fool] 辩论收敛（第 {round_num} 轮）")
            break

    # 保存挑战文档
    challenge_summary = "\n\n".join([
        f"## 第 {d['round']} 轮\n### Fool 质疑\n{d['challenge']}\n### Planner 回应\n{d['response']}"
        for d in debate_log
    ])
    await client.write_file(fool_id, "workspace/challenge.md", challenge_summary)

    print(f"[fool] ✅ 辩论完成（{len(debate_log)} 轮）")
    return {
        "challenge_body": challenge_summary,
        "plan_body": plan_body,
        "phase": "awaiting_approval",
    }


async def human_approval(state: State) -> dict:
    """节点4: interrupt() 等人类打分

    人类看到的是：经过 Fool 辩论打磨的计划 + 争议摘要。
    人类只需裁决争议点，不需要审查整个计划。
    """
    from langgraph.types import interrupt

    plan_preview = state.get("plan_body", "")[:500]
    challenge = state.get("challenge_body", "")

    print("[human_approval] ⏸ 等待人类审批...")
    if challenge:
        print(f"  [提示] 计划已经过 Fool 辩论打磨，请重点关注争议点")

    response = interrupt({
        "type": "plan_approval",
        "message": "请审批计划（1-5 分，>= 3 通过）",
        "plan_preview": plan_preview,
        "has_debate": bool(challenge),
        "debate_summary": challenge[:500] if challenge else "",
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
    plan_body = state.get("plan_body", "")
    plan_score = state.get("plan_score", 0)

    prompt = (
        f"你现在处于【执行阶段】。计划已批准（{plan_score}/5）。\n\n"
        f"## 已批准的计划\n{plan_body}\n\n"
        f"请按计划执行，完成后直接输出工作报告。\n"
        f"报告必须包含：## 完成情况 和 ## 变更文件"
    )

    session_id = state.get("exec_session_id") or str(uuid.uuid4())
    print(f"[execute_agent] 唤醒 Executor {executor_id}")
    reply = await client.send_message(executor_id, prompt, session_id)
    print(f"[execute_agent] 收到回复 ({len(reply)} 字)")

    # 不覆盖 — Agent 可能已通过工具写入
    try:
        existing_report = await client.read_file(executor_id, "workspace/report.md")
    except Exception:
        existing_report = ""

    if not existing_report or len(existing_report) < 30:
        if reply and len(reply) > 30:
            await client.write_file(executor_id, "workspace/report.md", reply)

    return {"phase": "checking_report", "exec_session_id": session_id}


async def check_report_gate(state: State) -> dict:
    """节点6: 读 report，格式验证"""
    executor_id = state["executor_id"]
    rework_count = state.get("rework_count", 0)
    rework_history = state.get("rework_history", [])

    report_body = ""
    try:
        report_body = await client.read_file(executor_id, "workspace/report.md")
    except Exception:
        pass

    if not report_body:
        reason = "未检测到工作报告"
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
        return {
            "report_body": report_body,
            "phase": "report_failed",
            "rework_count": rework_count + 1,
            "last_fail_reason": reason,
            "rework_history": rework_history + [reason],
        }

    print("[check_report] ✅ 门控通过")
    return {"report_body": report_body, "phase": "report_passed"}


async def human_score(state: State) -> dict:
    """节点7: interrupt() 等人类评分"""
    from langgraph.types import interrupt

    report_preview = state.get("report_body", "")[:500]
    plan_score = state.get("plan_score", 0)

    print("[human_score] ⏸ 等待人类评分...")
    print(f"  报告预览: {report_preview[:100]}...")

    response = interrupt({
        "type": "result_score",
        "message": "请评分执行结果（1-5 分，>= 3 通过）",
        "report_preview": report_preview,
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

    print(f"[human_score] ✅ 完成（计划 {plan_score}/5，结果 {score}/5，返工 {rework_count} 次）")
    return {"result_score": score, "phase": "done"}
