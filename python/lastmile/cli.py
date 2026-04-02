"""Last Mile CLI — AI-native 软件开发流水线"""

import asyncio
import uuid
import typer
from rich.console import Console
from typing import Optional

from lastmile import config as cfg
from lastmile.clawith import client
from lastmile.workflow.pipeline import pipeline
from lastmile import display

app = typer.Typer(help="Last Mile — AI-native 软件开发流水线 CLI")
console = Console()

# 存储活跃流水线（内存，进程重启丢失，后续可持久化）
_active_pipelines: dict[str, dict] = {}


def _run(coro):
    """同步包装异步调用"""
    return asyncio.run(coro)


async def _ensure_login():
    """确保已登录 Clawith"""
    c = cfg.load()
    if not c.email:
        console.print("[red]未初始化。请先运行: lastmile init[/red]")
        raise typer.Exit(1)
    await client.login(c.email, c.password)
    return c


# ── init ──

@app.command()
def init():
    """初始化配置（Clawith 连接 + Agent 绑定）"""
    c = cfg.load()

    console.print("[bold]Last Mile 初始化[/bold]\n")

    c.clawith_url = typer.prompt("Clawith URL", default=c.clawith_url or "http://localhost:8008")
    client.CLAWITH_URL = c.clawith_url
    client.CLAWITH_WS = c.clawith_url.replace("http", "ws")

    c.email = typer.prompt("邮箱", default=c.email)
    c.password = typer.prompt("密码", hide_input=True, default=c.password)

    # 验证登录
    try:
        _run(client.login(c.email, c.password))
        console.print("[green]✅ 登录成功[/green]")
    except Exception as e:
        console.print(f"[red]❌ 登录失败: {e}[/red]")
        raise typer.Exit(1)

    # 列出 Agent，让用户选择
    agents = _run(client.list_agents())
    display.print_agents(agents)

    agent_names = {a["name"].lower(): a["id"] for a in agents}

    c.planner_id = typer.prompt("Planner Agent ID",
        default=c.planner_id or agent_names.get("planner", ""))
    c.executor_id = typer.prompt("Executor Agent ID",
        default=c.executor_id or agent_names.get("executor", ""))
    c.fool_id = typer.prompt("Fool Agent ID (可选，回车跳过)",
        default=c.fool_id or agent_names.get("fool", ""))

    cfg.save(c)
    console.print(f"\n[green]✅ 配置已保存到 {cfg.CONFIG_PATH}[/green]")


# ── run ──

@app.command()
def run(
    requirement: str = typer.Argument(..., help="需求描述"),
    fool: bool = typer.Option(False, "--fool", help="启用 Fool 挑战"),
    max_reworks: int = typer.Option(3, "--max-reworks", help="最大返工次数"),
):
    """启动流水线"""
    _run(_run_pipeline(requirement, fool, max_reworks))


async def _run_pipeline(requirement: str, use_fool: bool, max_reworks: int):
    c = await _ensure_login()

    thread_id = f"pipeline-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}

    console.print(f"\n[bold]🚀 启动流水线[/bold]")
    console.print(f"  需求: {requirement}")
    console.print(f"  Thread: {thread_id}")
    console.print(f"  Planner: {c.planner_id[:8]}  Executor: {c.executor_id[:8]}")
    if use_fool and c.fool_id:
        console.print(f"  Fool: {c.fool_id[:8]}")
    console.print()

    initial = {
        "agent_id": c.planner_id,
        "executor_id": c.executor_id,
        "fool_id": c.fool_id if use_fool else "",
        "requirement": requirement,
        "phase": "planning",
        "rework_count": 0,
        "max_reworks": max_reworks,
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

    # 运行直到 interrupt
    await _stream_until_interrupt(config, initial)

    # 循环：每次 interrupt 交互式打分，然后 resume
    while True:
        state = await pipeline.aget_state(config)
        phase = state.values.get("phase", "")

        if not state.next:
            # 流水线完成
            console.print(f"\n[bold green]🎉 流水线完成[/bold green]")
            console.print(f"  计划评分: {state.values.get('plan_score')}/5")
            console.print(f"  结果评分: {state.values.get('result_score')}/5")
            console.print(f"  返工次数: {state.values.get('rework_count')}")
            break

        # 显示当前内容
        if phase == "awaiting_approval" and state.values.get("plan_body"):
            display.print_plan(state.values["plan_body"])
            if state.values.get("challenge_body"):
                display.print_challenge(state.values["challenge_body"])
        elif phase == "report_passed" and state.values.get("report_body"):
            display.print_report(state.values["report_body"])

        # 交互式打分
        score, feedback = display.ask_score()

        # Resume
        from langgraph.types import Command
        await _stream_until_interrupt(
            config,
            Command(resume={"score": score, "feedback": feedback}),
        )


async def _stream_until_interrupt(config, input_data):
    """运行图直到 interrupt 或完成"""
    async for chunk in pipeline.astream(input_data, config, stream_mode="updates"):
        if isinstance(chunk, dict):
            for node, update in chunk.items():
                if isinstance(update, dict):
                    phase = update.get("phase", "")
                    if "failed" in phase:
                        display.print_phase(f"{node}: {phase}", "failed")
                    elif "passed" in phase or phase == "done":
                        display.print_phase(f"{node}: {phase}", "passed")
                    elif "awaiting" in phase or "report_passed" in phase:
                        display.print_phase(f"{node}: {phase}", "waiting")
                    else:
                        display.print_phase(f"{node}: {phase}", "running")
        elif isinstance(chunk, tuple) and len(chunk) == 2:
            node, update = chunk
            if isinstance(update, dict):
                display.print_phase(f"{node}: {update.get('phase', '')}", "running")


# ── approve ──

@app.command()
def approve(
    thread_id: str = typer.Argument(..., help="流水线 Thread ID"),
    score: int = typer.Option(..., "--score", "-s", help="评分 1-5"),
    feedback: str = typer.Option("", "--feedback", "-f", help="反馈"),
):
    """审批/评分流水线"""
    _run(_approve_pipeline(thread_id, score, feedback))


async def _approve_pipeline(thread_id: str, score: int, feedback: str):
    await _ensure_login()
    config = {"configurable": {"thread_id": thread_id}}

    state = await pipeline.aget_state(config)
    if not state.next:
        console.print("[red]流水线未在等待审批[/red]")
        raise typer.Exit(1)

    console.print(f"[yellow]恢复流水线 {thread_id}，评分 {score}/5[/yellow]")

    from langgraph.types import Command
    await _stream_until_interrupt(
        config,
        Command(resume={"score": score, "feedback": feedback}),
    )

    state = await pipeline.aget_state(config)
    if not state.next:
        console.print(f"[green]✅ 流水线完成[/green]")
    else:
        console.print(f"[yellow]⏸ 流水线等待下一次审批（阶段: {state.values.get('phase')}）[/yellow]")


# ── status ──

@app.command()
def status(thread_id: str = typer.Argument(None, help="Thread ID（不填列出所有）")):
    """查看流水线状态"""
    _run(_show_status(thread_id))


async def _show_status(thread_id: Optional[str]):
    await _ensure_login()

    if not thread_id:
        console.print("[dim]提示: lastmile status <thread_id> 查看详情[/dim]")
        return

    config = {"configurable": {"thread_id": thread_id}}
    state = await pipeline.aget_state(config)

    display.print_status({
        "thread_id": thread_id,
        "phase": state.values.get("phase", "unknown"),
        "rework_count": state.values.get("rework_count", 0),
        "interrupted": bool(state.next),
    })

    if state.values.get("plan_body"):
        display.print_plan(state.values["plan_body"])
    if state.values.get("report_body"):
        display.print_report(state.values["report_body"])


# ── agents ──

@app.command()
def agents(
    name: str = typer.Argument(None, help="Agent 名称（不填列出所有）"),
    memory: bool = typer.Option(False, "--memory", help="显示 memory.md"),
    plan: bool = typer.Option(False, "--plan", help="显示最新 plan"),
):
    """查看 Agent"""
    _run(_show_agents(name, memory, plan))


async def _show_agents(name: Optional[str], show_memory: bool, show_plan: bool):
    await _ensure_login()
    all_agents = await client.list_agents()

    if not name:
        display.print_agents(all_agents)
        return

    agent = next((a for a in all_agents if a["name"].lower() == name.lower()), None)
    if not agent:
        console.print(f"[red]未找到 Agent: {name}[/red]")
        return

    console.print(f"\n[bold]{agent['name']}[/bold] ({agent['id'][:8]})")
    console.print(f"  角色: {agent.get('role_description', '-')}")
    console.print(f"  状态: {agent.get('status', 'idle')}")

    if show_memory:
        try:
            mem = await client.read_file(agent["id"], "memory/memory.md")
            console.print(Panel(mem[:2000], title="memory.md", border_style="cyan"))
        except Exception:
            console.print("[dim]无 memory.md[/dim]")

    if show_plan:
        try:
            p = await client.read_file(agent["id"], "workspace/plan.md")
            display.print_plan(p)
        except Exception:
            console.print("[dim]无 plan.md[/dim]")


if __name__ == "__main__":
    app()
