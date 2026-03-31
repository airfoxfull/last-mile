/**
 * Hatchet Demo: Plan → Approve → Execute workflow
 *
 * Demonstrates:
 * 1. DAG step ordering via `parents` (step2 can't run before step1)
 * 2. Human approval gate via `durableTask` + `ctx.waitForEvent`
 * 3. External process integration (spawning Claude CLI)
 *
 * SDK: @hatchet-dev/typescript-sdk ^1.19.0
 *
 * Architecture:
 *   [plan] ──parents──▶ [approve (durable, waits for event)] ──parents──▶ [execute]
 *
 * To resume the approval gate from outside:
 *   hatchet.events.push('approval:response', { approved: true })
 */

import { HatchetClient } from '@hatchet-dev/typescript-sdk/v1';
import { execSync } from 'child_process';

// --- Client ---
const hatchet = HatchetClient.init();

// --- Types ---
type WorkflowInput = {
  task: string;
  repo: string;
};

type WorkflowOutput = {
  plan: { plan: string; estimatedSteps: number };
  approve: { approved: boolean; approvedBy: string };
  execute: { result: string; exitCode: number };
};

// --- Workflow ---
export const planApproveExecute = hatchet.workflow<WorkflowInput, WorkflowOutput>({
  name: 'plan-approve-execute',
});

// Step 1: Plan — generate an implementation plan
const plan = planApproveExecute.task({
  name: 'plan',
  fn: async (input) => {
    console.log(`[plan] Generating plan for: ${input.task}`);

    // In production this would call an LLM or Claude CLI
    // Example: execSync(`claude -p "Plan: ${input.task}" --output-format json`)
    const planText = `1. Analyze ${input.repo}\n2. Implement ${input.task}\n3. Write tests\n4. Submit PR`;

    return {
      plan: planText,
      estimatedSteps: 4,
    };
  },
});

// Step 2: Approve — durable task that pauses until a human sends an event
// This is the human-in-the-loop gate. The worker suspends (no resources consumed)
// until `hatchet.events.push('approval:response', { approved: true })` is called.
const approve = planApproveExecute.durableTask({
  name: 'approve',
  parents: [plan],
  executionTimeout: '24h', // allow up to 24h for human review
  fn: async (_input, ctx) => {
    console.log('[approve] Waiting for human approval...');

    // Pause execution until the 'approval:response' event arrives.
    // The CEL filter ensures we only resume on approved=true events.
    // If the event payload has approved=false, the filter won't match
    // and the task keeps waiting (or times out).
    const event = await ctx.waitForEvent(
      'approval:response',
      "input.approved == true"
    );

    console.log('[approve] Approval received:', event);

    return {
      approved: true,
      approvedBy: (event as Record<string, string>)?.approvedBy ?? 'unknown',
    };
  },
});

// Step 3: Execute — runs only after approval, calls Claude CLI
planApproveExecute.task({
  name: 'execute',
  parents: [approve],
  fn: async (input, ctx) => {
    const approvalResult = await ctx.parentOutput(approve);
    console.log(`[execute] Approved by: ${approvalResult.approvedBy}`);
    console.log(`[execute] Running task: ${input.task}`);

    // Call Claude CLI as an external process
    let result: string;
    let exitCode: number;

    try {
      result = execSync(
        `claude -p "Execute this plan in ${input.repo}: ${input.task}" --output-format text`,
        { encoding: 'utf-8', timeout: 300_000 }
      ).trim();
      exitCode = 0;
    } catch (err: any) {
      result = err.stderr?.toString() ?? err.message;
      exitCode = err.status ?? 1;
    }

    return { result, exitCode };
  },
});

// --- Worker (run with: npx ts-node demo-workflow.ts) ---
async function main() {
  const worker = await hatchet.worker('demo-worker', {
    workflows: [planApproveExecute],
  });

  await worker.start();
}

if (require.main === module) {
  main();
}
