"""LangGraph 状态定义"""

from typing import Annotated
from langgraph.graph import add_messages


# 简单替换 reducer：后值覆盖前值
def replace(a, b):
    return b


# 追加 reducer：用于 reworkHistory
def append_list(a: list, b: list) -> list:
    return a + b


class PipelineState:
    """Last Mile 流水线状态（TypedDict 风格，LangGraph 用）"""
    pass


# LangGraph Annotation 风格定义
from langgraph.graph import StateGraph
from typing import TypedDict


class State(TypedDict):
    # 输入
    agent_id: str           # Clawith Planner Agent ID
    executor_id: str        # Clawith Executor Agent ID
    fool_id: str            # Clawith Fool Agent ID (可选)
    requirement: str        # 需求描述

    # 跟踪
    phase: str              # 当前阶段
    rework_count: int       # 返工次数
    max_reworks: int        # 最大返工次数

    # 记忆
    last_fail_reason: str   # 上次失败原因
    rework_history: list[str]  # 返工原因列表

    # 文档
    plan_body: str          # plan 文档内容
    report_body: str        # report 文档内容
    challenge_body: str     # Fool 挑战文档

    # 评分
    plan_score: int | None  # 计划评分
    result_score: int | None  # 结果评分

    # 会话
    plan_session_id: str    # Planner 会话 ID
    exec_session_id: str    # Executor 会话 ID
