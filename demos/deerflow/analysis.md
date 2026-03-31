# DeerFlow 2.0 Architecture Analysis

## Key Finding: No Multi-Node StateGraph

DeerFlow 2.0 is a **ground-up rewrite** that abandoned the v1 multi-agent StateGraph
(Coordinator -> Planner -> Coder -> Analyzer). It now uses a **single-agent harness**
architecture built on `langchain.agents.create_agent`, which internally produces a
`CompiledStateGraph` with only two nodes: `agent` (LLM) and `tools` (tool execution).

There is no explicit `StateGraph().add_node().add_edge()` user code in v2.
The graph is created by LangChain's `create_agent()` primitive.

## Graph Structure

```
langgraph.json
  └── graphs.lead_agent = "deerflow.agents:make_lead_agent"

make_lead_agent(config: RunnableConfig)
  └── create_agent(model, tools, middleware, system_prompt, state_schema=ThreadState)
        └── CompiledStateGraph with 2 nodes:
              [agent] ←→ [tools]
                 ↓
               [END]
```

The "workflow" is the standard LangGraph ReAct loop: LLM decides -> tool calls ->
results fed back -> LLM decides again -> until no more tool calls -> END.

## Workflow Enforcement Mechanism

DeerFlow does NOT enforce step ordering via graph edges. Instead it uses a
**middleware chain** (14 middlewares in fixed order):

```
0-2. ThreadData → Uploads → Sandbox     (before_agent, sequential)
3.   DanglingToolCallMiddleware          (always)
4.   GuardrailMiddleware                 (optional, tool-call gating)
5.   ToolErrorHandlingMiddleware         (always)
6.   SummarizationMiddleware             (optional)
7.   TodoMiddleware                      (plan_mode only)
8.   TitleMiddleware                     (auto-title)
9.   MemoryMiddleware                    (persistent memory)
10.  ViewImageMiddleware                  (vision)
11.  SubagentLimitMiddleware              (caps parallel subagents)
12.  LoopDetectionMiddleware              (always)
13.  ClarificationMiddleware              (always last)
```

Execution model:
- `before_agent` runs forward [0..N], once per turn
- `before_model` runs forward [0..N], each LLM call
- `after_model` runs reverse [N..0], each LLM call
- `after_agent` runs reverse [N..0], once per turn

Hard ordering constraints:
- ThreadData must precede Sandbox (sandbox needs thread directory)
- ClarificationMiddleware must be last (after_model reverse = first to intercept)

## Human-in-the-Loop Capability

Three mechanisms exist:

### 1. ClarificationMiddleware (primary HITL)
When the LLM calls `ask_clarification` tool, the middleware intercepts it,
formats the question, and returns `Command(goto=END)` which terminates the
current run. The frontend displays the question; the user's reply starts a
new run on the same thread (checkpointer preserves state).

### 2. GuardrailMiddleware (tool-call gating)
Evaluates each tool call against a `GuardrailProvider` before execution.
Denied calls return an error ToolMessage. This is policy-based, not
interactive — no user prompt.

### 3. Runtime interrupt_before / interrupt_after
The Gateway API accepts `interrupt_before` and `interrupt_after` parameters
on run creation. The worker sets `agent.interrupt_before_nodes` /
`agent.interrupt_after_nodes` on the compiled graph. This is standard
LangGraph interrupt support, but the only nodes are `agent` and `tools`,
so it can only pause before/after the entire agent or tool node.

## Agent Connections

```
DeerFlowClient / Gateway API
  └── make_lead_agent (lead agent)
        ├── tools: bash, web_search, file ops, MCP tools, ...
        ├── task_tool → SubagentExecutor
        │     └── create_agent (subagent: general-purpose or bash)
        │           └── filtered tool subset (no nesting, no clarification)
        └── ask_clarification → ClarificationMiddleware → END (HITL)
```

- Lead agent delegates via `task_tool` which spawns subagents in a ThreadPoolExecutor
- Subagents are independent `create_agent` instances with a shorter middleware chain
- Subagents cannot nest (task_tool is in their disallowed_tools list)
- Max 3 concurrent subagents (configurable)

## Implementing a 2-Step Workflow with Approval Gate

Since DeerFlow 2.0 has no multi-node graph to insert custom nodes into,
a "plan then approve then execute" workflow requires one of these approaches:

### Option A: Middleware-based (recommended for DeerFlow)
```python
from deerflow.agents.features import Prev
from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware

@Prev(ClarificationMiddleware)
class ApprovalGateMiddleware(AgentMiddleware):
    """Intercept specific tool calls and require approval."""
    def wrap_tool_call(self, request, handler):
        if request.tool_call["name"] in GATED_TOOLS:
            # Return Command(goto=END) with approval prompt
            # User reply resumes the thread
            return Command(update={...}, goto=END)
        return handler(request)

client = DeerFlowClient(extra_middleware=[ApprovalGateMiddleware()])
```

### Option B: External orchestration
Use `interrupt_before=["tools"]` on run creation to pause before every
tool execution. The frontend/caller inspects the pending tool calls,
shows them for approval, then resumes the run. This is coarse-grained
(pauses on ALL tool calls, not selective).

### Option C: Skill-based workflow
Encode the 2-step workflow in a SKILL.md that instructs the agent to:
1. Generate a plan and call `ask_clarification` to present it
2. Wait for user approval
3. Execute the approved plan
This relies on prompt engineering, not graph enforcement.

## Key Limitations for Our Use Case

1. **No graph-level workflow enforcement.** The ReAct loop is the only
   execution pattern. You cannot define "Step A must complete before Step B"
   as graph edges. Ordering depends on prompt engineering or middleware.

2. **Middleware operates within a single agent turn.** Middleware hooks
   (before_model, after_model, wrap_tool_call) fire during one run.
   Cross-turn orchestration (plan in turn 1, approve, execute in turn 2)
   requires external coordination via the checkpointer + new runs.

3. **Subagents are fire-and-forget.** The lead agent spawns subagents via
   task_tool and polls for results. There is no structured handoff protocol
   or approval gate between parent and child agents.

4. **ClarificationMiddleware is the only built-in HITL.** It terminates
   the run entirely. There is no "pause and resume" within a single run
   (the LangGraph interrupt_before/after exists but is not wired into the
   frontend flow by default).

5. **No Coordinator/Planner/Coder/Analyzer roles.** DeerFlow 2.0 is a
   single "super agent" that uses tools and subagents. Role separation
   must be implemented via skills, system prompts, or external orchestration.

6. **Extensibility is via middleware, not graph nodes.** The `@Next/@Prev`
   decorators and `RuntimeFeatures` dataclass provide clean extension points,
   but they operate at the middleware level, not the workflow graph level.
