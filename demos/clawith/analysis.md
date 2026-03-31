# Clawith Source Code Analysis

## 1. Hook System — How It Works

Clawith does NOT have a hook system in the Claude Code / OpenClaw sense (PreToolUse, PostToolUse, etc.). There are no user-configurable JavaScript hooks that intercept tool calls at the harness level.

Instead, Clawith has two enforcement mechanisms:

### 1.1 Autonomy Service (L1/L2/L3) — HARD enforcement

Located in `backend/app/services/autonomy_service.py`.

Every tool call goes through `execute_tool()` in `agent_tools.py`, which checks the agent's `autonomy_policy` dict before execution:

```python
_TOOL_AUTONOMY_MAP = {
    "write_file": "write_workspace_files",
    "delete_file": "delete_files",
    "send_feishu_message": "send_feishu_message",
    "execute_code": "execute_code",
    "web_search": "web_search",
}
```

Three levels:
- **L1**: Auto-execute, log only
- **L2**: Auto-execute, notify creator (Feishu + web notification)
- **L3**: BLOCK execution, create `ApprovalRequest` in DB, notify creator, wait for human approve/reject

Default policy per agent:
```python
{
    "read_files": "L1",
    "write_workspace_files": "L2",
    "send_feishu_message": "L2",
    "send_external_message": "L3",
    "modify_soul": "L3",
    "delete_files": "L3",
    "financial_operations": "L3",
}
```

When L3 blocks a tool, the LLM receives: `"⏳ This action requires approval..."` and the tool result is NOT executed. After human approval, `_execute_tool_direct()` runs the tool bypassing the autonomy check.

**Verdict: L3 is genuine hard enforcement.** The tool physically does not execute until approved.

### 1.2 Trigger/Aware Engine — Agent self-scheduling (NOT hooks)

Located in `backend/app/services/trigger_daemon.py` and `backend/app/models/trigger.py`.

This is NOT a hook system. It's a background daemon (15s tick) that evaluates agent-created triggers:
- `cron` — recurring schedule
- `once` — fire once at specific time
- `interval` — every N minutes
- `poll` — HTTP endpoint monitoring with change detection
- `on_message` — wake when specific agent/human replies
- `webhook` — receive external HTTP POST

When a trigger fires, it fabricates a system message and injects it into the agent's WebSocket/LLM flow. The agent then runs its normal tool-calling loop (up to 50 rounds).

**These are agent-initiated, not harness-level interception points.**

### 1.3 Hard Parameter Validation — Inline guards

In `websocket.py` `call_llm()`, there's a guard for tools requiring arguments:
```python
_TOOLS_REQUIRING_ARGS = {"write_file", "read_file", "delete_file", ...}
if not args and tool_name in _TOOLS_REQUIRING_ARGS:
    # Return error to LLM, don't execute
```

This is a hardcoded safety net, not a configurable hook.

## 2. Can Hooks BLOCK an Action?

| Mechanism | Can Block? | Configurable? | Scope |
|-----------|-----------|---------------|-------|
| Autonomy L3 | YES — hard block | Per-agent, per-action-type | Tool execution only |
| Autonomy L2 | NO — notify only | Per-agent | Tool execution only |
| Empty-args guard | YES — hard block | NO (hardcoded) | Specific tools |
| Tool-round limit | YES — stops loop | Per-agent (max_tool_rounds) | Entire conversation |
| Token quota | YES — refuses to start | Per-agent daily/monthly | Entire conversation |

**There is no PreToolUse/PostToolUse hook system.** You cannot run arbitrary code before/after each tool call. The only blocking mechanism is the L1/L2/L3 autonomy policy, which maps tool names to action types.

## 3. Multi-Agent Workspace Configuration

### Agent Identity
Each agent has a persistent workspace at `backend/agent_data/<agent-uuid>/`:
- `soul.md` — personality definition (template with `{{agent_name}}`, `{{role_description}}`)
- `memory/memory.md` — long-term memory
- `memory/reflections.md` — autonomous thinking journal
- `focus.md` — working memory / current task tracking
- `skills/` — skill definitions (markdown files, progressive disclosure)
- `workspace/` — working files
- `relationships.md` — relationship list
- `state.json` — runtime state

### Agent-to-Agent (A2A)
- Controlled by `AgentAgentRelationship` table — strict bidirectional relationship check
- Tools: `send_message_to_agent`, `send_file_to_agent`
- Without a relationship record, A2A communication is blocked
- No shared workspace — agents communicate via messages only

### Agent Configuration (DB)
- `Agent` model: `agent_type` (native/openclaw), `autonomy_policy`, `primary_model_id`, `heartbeat_enabled`, `max_tool_rounds`, token quotas
- `AgentTemplate`: predefined configurations with `soul_template`, `default_skills`, `default_autonomy_policy`

## 4. SOUL/MEMORY System in Code

### Context Assembly (`agent_context.py`)
`build_agent_context()` assembles the system prompt from:
1. Static parts: role, soul.md, skills index, relationships, company info, tool instructions
2. Dynamic parts: memory.md, focus.md, active triggers, current time, current user

Skills use progressive disclosure — only name+description go into the system prompt. The agent must call `read_file` to load full skill instructions.

### Memory Persistence
- `memory/memory.md` — agent writes via `write_file` tool
- `memory/MEMORY_INDEX.md` — index of memory topics
- `memory/curiosity_journal.md` — heartbeat discoveries
- `memory/reflections.md` — autonomous thinking journal

All memory is file-based. The agent reads/writes these files using standard file tools. There is no structured memory API — it's all markdown files that get injected into the system prompt (truncated at 2000-3000 chars).

## 5. Can We Enforce "Plan Before Execute"?

### What Clawith CAN do:
1. **L3 autonomy on write/execute tools** — block `write_file`, `execute_code`, `delete_file` until human approves. But this is per-tool-call approval, not "submit a plan first."
2. **Skill instructions** — a skill.md file can instruct the agent to "write a plan to focus.md before executing." But this is prompt-based (soft enforcement). The agent CAN ignore it.
3. **Soul.md instructions** — same as skills, prompt-level only.

### What Clawith CANNOT do:
1. **No PreToolUse hooks** — cannot intercept tool calls with custom logic
2. **No workflow state machine** — no concept of "phase 1 must complete before phase 2"
3. **No plan-then-execute gate** — no mechanism to require a plan artifact before allowing code execution
4. **No conditional tool availability** — cannot hide tools until a condition is met (e.g., plan approved)
5. **No inter-step validation** — cannot run a validator between workflow steps

### Workaround for 2-step workflow:

The closest approximation using Clawith's mechanisms:

**Step 1 — Planning Agent (L1 autonomy, read-only tools)**
- Create an agent with `autonomy_policy` that sets ALL write/execute tools to L3
- Agent can only read files, search web, and write to its own focus.md
- Agent writes plan to focus.md, then uses `send_message_to_agent` to notify the execution agent

**Step 2 — Execution Agent (L2 autonomy, full tools)**
- Receives plan via A2A message
- Has `on_message` trigger to wake when planning agent sends
- Executes the plan with full tool access

**Limitations of this workaround:**
- No guarantee the planning agent actually produces a valid plan
- No structured validation of the plan before execution starts
- The execution agent might ignore the plan
- Requires 2 separate agents with A2A relationship
- L3 approval is per-tool-call, not per-plan — human would need to approve every single write

## 6. Key Limitations for Our Use Case

| Requirement | Clawith Support | Gap |
|-------------|----------------|-----|
| Hard tool-call interception (PreToolUse) | NO | No hook system at all |
| Workflow state machine | NO | No phases, no gates |
| Plan-before-execute enforcement | SOFT only (prompt) | No structural enforcement |
| Conditional tool visibility | NO | All tools always visible |
| Multi-agent orchestration | YES (A2A) | But no workflow coordination |
| Persistent agent identity | YES | soul.md + memory.md |
| Human approval gates | YES (L3) | Per-tool-call only, not per-phase |
| Agent self-scheduling | YES (triggers) | Rich: cron/poll/webhook/on_message |
| Token/cost control | YES | Daily/monthly quotas |

### Bottom Line

Clawith is an **agent collaboration platform**, not a **workflow orchestration engine**. Its strengths are persistent agent identity, A2A communication, and the Aware trigger system. Its autonomy L3 provides genuine hard blocking of dangerous operations.

However, it has **no hook system** and **no workflow state machine**. Enforcing "agent must submit plan before executing code" requires either:
1. Prompt-level instructions (soft, can be ignored)
2. Two-agent architecture with L3 gates (heavy, per-tool-call approval)
3. Custom code modifications to `execute_tool()` in `agent_tools.py` to add a plan-check gate

For Last Mile's needs, Clawith would need significant custom development to support structured multi-step workflows with hard enforcement between phases.
