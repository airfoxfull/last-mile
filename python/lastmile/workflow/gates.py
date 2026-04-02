"""门控检查函数"""

from dataclasses import dataclass


@dataclass
class GateResult:
    ok: bool
    missing: list[str]


def check_plan(body: str) -> GateResult:
    """门1: feature-forge 格式检查 — plan 必须包含 4 个必需章节"""
    need = ["## 任务分析", "## 执行步骤", "## 风险评估", "## 预算估算"]
    missing = [h for h in need if h not in body]
    if len(body) < 50:
        missing.append("内容过短")
    return GateResult(ok=len(missing) == 0, missing=missing)


def check_report(body: str) -> GateResult:
    """门3: code-reviewer 格式检查 — report 必须包含完成情况和变更文件"""
    need = ["## 完成情况", "## 变更文件"]
    missing = [h for h in need if h not in body]
    if len(body) < 30:
        missing.append("内容过短")
    return GateResult(ok=len(missing) == 0, missing=missing)
