"""Rich 终端输出"""

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown

console = Console()


def print_phase(name: str, status: str = ""):
    icons = {"passed": "[green]✅", "failed": "[red]⚠️", "waiting": "[yellow]⏸",
             "running": "[blue]⏳", "done": "[green]🎉"}
    icon = icons.get(status, "[white]▶")
    console.print(f"{icon} {name}[/]")


def print_plan(body: str):
    console.print(Panel(Markdown(body[:2000]), title="📋 执行计划", border_style="blue"))


def print_report(body: str):
    console.print(Panel(Markdown(body[:2000]), title="📝 工作报告", border_style="green"))


def print_challenge(body: str):
    console.print(Panel(Markdown(body[:3000]), title="🤔 Fool 辩论记录", border_style="yellow",
                        subtitle="人类只需裁决争议点"))


def print_agents(agents: list[dict]):
    t = Table(title="Agent 列表")
    t.add_column("名称", style="cyan")
    t.add_column("ID", style="dim")
    t.add_column("模型", style="green")
    t.add_column("状态", style="yellow")
    for a in agents:
        model = a.get("primary_model_id") or "-"
        t.add_row(a["name"], a["id"][:8], model[:8] if model != "-" else "-", a.get("status", "idle"))
    console.print(t)


def print_status(data: dict):
    t = Table(title=f"流水线 {data['thread_id']}")
    t.add_column("字段", style="cyan")
    t.add_column("值")
    t.add_row("阶段", data.get("phase", "unknown"))
    t.add_row("返工次数", str(data.get("rework_count", 0)))
    t.add_row("等待审批", "是" if data.get("interrupted") else "否")
    console.print(t)


def ask_score() -> tuple[int, str]:
    """交互式打分"""
    console.print("\n[bold yellow]请审批/评分:[/bold yellow]")
    while True:
        score_str = console.input("[yellow]评分 (1-5): [/yellow]")
        try:
            score = int(score_str)
            if 1 <= score <= 5:
                break
            console.print("[red]请输入 1-5 之间的数字[/red]")
        except ValueError:
            console.print("[red]请输入数字[/red]")
    feedback = console.input("[yellow]反馈 (可选，回车跳过): [/yellow]").strip()
    return score, feedback
