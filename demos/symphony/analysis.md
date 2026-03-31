# Symphony Architecture Analysis

## 1. Architecture and Process Model

### OTP Supervision Tree

Symphony is an Elixir/OTP application with a flat `one_for_one` supervisor:

```
SymphonyElixir.Supervisor (one_for_one)
├── Phoenix.PubSub          — event bus for dashboard updates
├── Task.Supervisor          — spawns per-issue agent worker tasks
├── WorkflowStore            — watches/caches WORKFLOW.md
├── Orchestrator             — GenServer: poll loop, dispatch, reconciliation
├── HttpServer               — Phoenix endpoint (observability API)
└── StatusDashboard          — terminal UI renderer
```

The Orchestrator is the single authority for all scheduling state. It is a GenServer that owns:
- `running` map (issue_id -> running entry with pid, monitor ref, token counters)
- `claimed` set (prevents duplicate dispatch)
- `retry_attempts` map (issue_id -> backoff timer + metadata)
- `completed` set (bookkeeping only)

Agent work is spawned via `Task.Supervisor.start_child`, not as supervised children. Each task is monitored by the Orchestrator via `Process.monitor/1`. When a task exits (normal or crash), the Orchestrator receives `{:DOWN, ref, :process, pid, reason}` and handles state transitions.

### Task Lifecycle: Ready -> Running -> Completed

1. **Poll tick fires** — Orchestrator refreshes config, reconciles running issues against Linear, fetches candidate issues.
2. **Candidate selection** — Issues are sorted by priority (1-4 asc), created_at (oldest first), identifier (tiebreaker). Eligibility requires: active state, not claimed, not running, global + per-state slots available, not blocked (for Todo state).
3. **Revalidation** — Before dispatch, the issue is re-fetched from Linear to confirm it's still active (prevents stale-poll races).
4. **Dispatch** — `Task.Supervisor.start_child` spawns `AgentRunner.run/3`. The Orchestrator records pid, monitor ref, issue metadata, and token counters in `running`.
5. **Agent execution** — AgentRunner creates/reuses workspace, runs `before_run` hook, starts Codex app-server subprocess via stdio port, sends initialize/thread/turn protocol messages.
6. **Multi-turn loop** — After each turn completes, AgentRunner checks if the issue is still in an active Linear state. If yes and turn_number < max_turns (default 20), it sends continuation guidance to the same thread. This is the only multi-stage mechanism within a single task.
7. **Normal exit** — Orchestrator schedules a 1-second "continuation retry" to re-check if the issue is still active. If so, a new worker session is dispatched.
8. **Abnormal exit** — Orchestrator schedules exponential backoff retry: `min(10s * 2^(attempt-1), 5min)`.
9. **Terminal state** — If Linear issue moves to Done/Closed/Cancelled, reconciliation kills the running worker and cleans up the workspace.

### Linear/GitHub Integration

- **Linear**: First-class integration via GraphQL API. The `Linear.Client` module polls for candidate issues by project slug and active states, fetches issue states by ID for reconciliation, and supports pagination. The `Linear.Adapter` implements the `Tracker` behaviour and also provides `create_comment` and `update_issue_state` mutations.
- **Dynamic tool**: A `linear_graphql` tool is registered with the Codex app-server session, allowing the coding agent to execute arbitrary Linear GraphQL queries/mutations using Symphony's auth token.
- **GitHub**: No direct integration in Symphony itself. GitHub operations (PR creation, CI checks) are handled by the coding agent (Codex) through its own tooling, driven by the WORKFLOW.md prompt.
- **Tracker abstraction**: The `Tracker` behaviour with `fetch_candidate_issues/0`, `fetch_issues_by_states/1`, `fetch_issue_states_by_ids/1` callbacks makes it possible to swap Linear for another tracker. A `Tracker.Memory` adapter exists for testing.

## 2. Extensibility for Multi-Stage Workflows

### What Exists

Symphony has exactly one multi-stage mechanism: the **turn loop** inside `AgentRunner`. After each Codex turn completes, the runner checks if the issue is still active and, if so, sends continuation guidance to the same thread (up to `agent.max_turns`). This is a linear retry/continuation pattern, not a general-purpose stage pipeline.

### What's Missing for Chain-of-Responsibility

Symphony is designed as a **scheduler/runner**, not a workflow engine. The spec explicitly states this as a non-goal: "General-purpose workflow engine or distributed job scheduler."

Specific gaps:

1. **No stage model** — There is no concept of "stages" within a task. A task is one issue mapped to one agent run. The only progression is turn-by-turn within a single Codex session.
2. **No inter-task dependencies** — Symphony tracks `blocked_by` from Linear (blocking Todo dispatch), but has no internal DAG or pipeline concept.
3. **No state machine per task** — The orchestrator tracks claim states (Unclaimed/Claimed/Running/RetryQueued/Released), but these are operational states, not workflow stages.
4. **No plugin/middleware hooks for execution flow** — The hooks (`after_create`, `before_run`, `after_run`, `before_remove`) are workspace lifecycle hooks, not execution pipeline interceptors.

### How to Add Multi-Stage

To add chain-of-responsibility, you would need to:

- Define a stage model (e.g., in WORKFLOW.md front matter or a separate pipeline config)
- Add a `StageRunner` that wraps `AgentRunner` and manages stage transitions
- Track stage state in the Orchestrator's running entries
- Use Linear issue state transitions as stage gates (e.g., "In Progress" -> "Human Review" -> "In Progress" -> "Done")

The cleanest approach would be to model stages as Linear state transitions and let the Orchestrator's existing reconciliation loop detect state changes. This avoids adding a parallel state machine.

## 3. Human-in-the-Loop Feasibility

### Current Approval Handling

Symphony already has approval infrastructure in the Codex app-server client:

- **Auto-approve mode**: When `approval_policy` is `"never"`, all command execution, file change, and patch approvals are auto-approved for the session.
- **Approval-required mode**: When auto-approve is off, approval requests cause the run to fail with `{:error, {:approval_required, payload}}`. There is no mechanism to route these to a human and resume.
- **User input requests**: Handled by either auto-answering with "Approve this Session" or replying with "This is a non-interactive session." No human routing.

### Adding a "Wait for Human Approval" Step

There are two viable approaches:

**Approach A: Linear-state-driven (recommended)**

Use Linear issue states as the approval gate:
1. Agent completes its work and moves the issue to "Human Review" state.
2. Symphony's reconciliation detects the non-active state and stops the worker (no workspace cleanup since "Human Review" is not terminal).
3. Human reviews in Linear, moves issue back to "In Progress".
4. Next poll tick picks up the issue as a candidate again and dispatches a new agent run with continuation context.

This requires zero code changes to Symphony. The WORKFLOW.md prompt instructs the agent to transition to "Human Review" when ready, and `active_states` is configured to include the states where work should happen. The gap: there's no notification mechanism — the human must watch Linear.

**Approach B: Orchestrator-level pause state**

Add a `paused` map to Orchestrator state:
1. Agent or hook signals "needs approval" (e.g., via a dynamic tool or special exit code).
2. Orchestrator moves the issue from `running` to `paused` with approval metadata.
3. Expose paused issues via the HTTP observability API.
4. Human approves via API call or dashboard action.
5. Orchestrator moves issue back to dispatch queue.

This requires moderate changes: new Orchestrator state, new API endpoints, new dashboard UI. But it keeps the approval loop inside Symphony rather than depending on Linear state transitions.

**Recommendation**: Start with Approach A. It's zero-code and leverages the existing reconciliation loop. Add Approach B only if you need sub-task approval granularity or faster feedback loops.

## 4. Key Limitations for Our Use Case

### Architecture Constraints

1. **Single-node only** — All state is in-memory in one GenServer. No distributed coordination, no persistence. Restart loses all running/retry state (recovered from Linear on next poll, but in-flight work is lost).

2. **One agent type** — Symphony assumes all issues are handled by the same Codex agent with the same WORKFLOW.md prompt. There's no concept of routing different issue types to different agent configurations.

3. **Linear-coupled** — While the Tracker behaviour is abstractable, the entire domain model (issue states, project slugs, GraphQL queries) is Linear-shaped. Adapting to GitHub Issues or Jira would require significant normalization work.

4. **No persistent task history** — Completed issues are tracked only as a MapSet of IDs. No execution logs, no audit trail, no cost attribution per task beyond aggregate token counters.

5. **Codex-specific protocol** — The app-server client speaks a Codex-specific JSON-RPC protocol over stdio. Integrating a different coding agent (Claude, Cursor, etc.) would require reimplementing the entire `AppServer` module.

6. **No pipeline/DAG support** — As discussed above, there's no way to define multi-step workflows, conditional branching, or parallel sub-tasks within a single issue.

### Operational Concerns

7. **Workspace isolation is filesystem-only** — No containers, no VMs. The coding agent runs with the host user's permissions. Path safety checks prevent escape from workspace root, but there's no process-level sandboxing beyond what Codex provides.

8. **Polling-based, not event-driven** — Default 30-second poll interval means up to 30 seconds of latency between a Linear state change and Symphony's reaction. Webhooks are not supported.

9. **No cost controls** — Token counters are tracked but there are no budget limits, spend alerts, or per-issue cost caps. The only throttle is `max_concurrent_agents`.

10. **Hook-based extensibility is limited** — Hooks run shell commands with a timeout. They can't influence dispatch decisions, modify prompts, or interact with the Orchestrator state. They're workspace lifecycle events, not workflow extension points.

### What Works Well

- Clean separation of concerns (Orchestrator/AgentRunner/Workspace/Tracker)
- Robust reconciliation loop with stall detection
- Hot-reloadable WORKFLOW.md configuration
- The Tracker behaviour pattern is the right abstraction for adding new issue trackers
- Turn-based continuation within a single agent session is well-implemented
- Token tracking and rate limit awareness at the orchestrator level
