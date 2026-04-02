"""Last Mile 流水线 — LangGraph 状态图 + Clawith 集成"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from lastmile.workflow.state import State
from lastmile.workflow.nodes import (
    plan_agent, check_plan_gate, fool_challenge,
    human_approval, execute_agent, check_report_gate, human_score,
)


# ── 路由函数 ──

def after_check_plan(state: State) -> str:
    if state.get("phase") == "plan_failed":
        if state.get("rework_count", 0) >= state.get("max_reworks", 5):
            return "fool_challenge"  # 达上限，强制进入审批
        return "plan_agent"  # 返工
    return "fool_challenge"


def after_human_approval(state: State) -> str:
    return "plan_agent" if state.get("phase") == "plan_rejected" else "execute_agent"


def after_check_report(state: State) -> str:
    if state.get("phase") == "report_failed":
        if state.get("rework_count", 0) >= state.get("max_reworks", 5):
            return "human_score"
        return "execute_agent"
    return "human_score"


def after_human_score(state: State) -> str:
    return "execute_agent" if state.get("phase") == "exec_rework" else END


# ── 构建图 ──

checkpointer = MemorySaver()

builder = (
    StateGraph(State)
    .add_node("plan_agent", plan_agent)
    .add_node("check_plan", check_plan_gate)
    .add_node("fool_challenge", fool_challenge)
    .add_node("human_approval", human_approval)
    .add_node("execute_agent", execute_agent)
    .add_node("check_report", check_report_gate)
    .add_node("human_score", human_score)
    # 边
    .add_edge(START, "plan_agent")
    .add_edge("plan_agent", "check_plan")
    .add_conditional_edges("check_plan", after_check_plan)
    .add_edge("fool_challenge", "human_approval")
    .add_conditional_edges("human_approval", after_human_approval)
    .add_edge("execute_agent", "check_report")
    .add_conditional_edges("check_report", after_check_report)
    .add_conditional_edges("human_score", after_human_score)
)

pipeline = builder.compile(checkpointer=checkpointer)
