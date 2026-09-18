import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  type NativeRunnerDependencies,
} from "../../../app/api/producer/ai-edit/palmier-native-runner";
import { palmierAuthorityPath } from "../../../app/api/producer/ai-edit/palmier-native-prompt";
import type { ProducerReview } from "../../../app/api/producer/auto-edit/review-contract";
import { runTestPalmierNativeEdit as runPalmierNativeEdit } from "./palmier-native-test-fixture";

const PASS_REVIEW: ProducerReview = {
  schemaVersion: 1,
  stage: "plan",
  verdict: "pass",
  summary: "The scoped native edit is supported by the timeline evidence.",
  materialIssues: [],
  findings: [],
};

function authority() {
  return {
    schemaVersion: 1,
    authority: "palmier",
    origin: "palmier-manual",
    projectId: "project-1",
    timelineId: "timeline-parent",
    fingerprint: "a".repeat(64),
    readbackCoverage: { complete: true },
    timeline: {
      id: "timeline-parent",
      totalFrames: 300,
      tracks: [{ clips: [{ id: "clip-1" }] }],
    },
  };
}

function draft() {
  return {
    schemaVersion: 1,
    lanes: ["cuts"],
    operations: [{
      tool: "remove_words",
      args: { words: ["um"] },
      reason: "Remove the explicitly requested filler word.",
    }],
  };
}

function candidate(plan: Record<string, unknown>) {
  return {
    schemaVersion: 1,
    status: "edited",
    timelineId: "timeline-candidate",
    fingerprint: "b".repeat(64),
    base: {
      projectId: "project-1",
      timelineId: "timeline-parent",
      fingerprint: "a".repeat(64),
    },
    requestHash: plan.requestHash,
    lanes: plan.lanes,
    operations: [{ index: 1, tool: "remove_words" }],
    qc: { status: "pending", approved: false },
  };
}

function cliFixture(dir: string, calls: string[][]) {
  const runner: NonNullable<NativeRunnerDependencies["cli"]> = async (args) => {
    calls.push(args);
    if (args[1] === "--reconcile") {
      writeFileSync(palmierAuthorityPath(dir), JSON.stringify(authority()));
      return { ok: true, status: "reconciled", authority: authority() };
    }
    const plan = JSON.parse(readFileSync(args[2], "utf8")) as Record<string, unknown>;
    return { ok: true, status: "candidate-staged", candidate: candidate(plan) };
  };
  return runner;
}

async function codexHappyPath(dir: string): Promise<void> {
  const calls: string[][] = [];
  const prompts: Array<{ schema?: string; prompt: string }> = [];
  const codex: NonNullable<NativeRunnerDependencies["codex"]> = async (options) => {
    prompts.push({ schema: options.schema, prompt: options.prompt });
    return options.schema === "producer-review" ? PASS_REVIEW : draft();
  };
  const result = await runPalmierNativeEdit({
    dir, request: "Remove the filler word um", scope: { lanes: ["cuts"] },
  }, { provider: () => "codex", codex, cli: cliFixture(dir, calls) });
  assert.equal(result.timelineId, "timeline-candidate");
  assert.equal(result.operationCount, 1);
  assert.deepEqual(calls[0], [dir, "--reconcile"]);
  assert.equal(calls[1][0], dir);
  assert.deepEqual(calls[1].slice(1, 2), ["--execute"]);
  assert.equal(calls[1][3], "--gate-envelope");
  assert.match(calls[1][4], /palmier-native-gate/);
  assert.deepEqual(calls[1].slice(5), ["--name", "Sniper AI candidate"]);
  assert.equal(prompts.length, 2, "planner and fresh critic must be separate calls");
  for (const call of prompts) {
    assert.match(call.prompt, /SKILL\.md/);
    assert.match(call.prompt, /FAILURE_LEDGER\.md/);
    assert.match(call.prompt, /plan_lint\.py/);
    assert.match(call.prompt, /palmier\.timeline-authority\.json/);
  }
  assert.equal(prompts[0].schema, "palmier-mutation-plan");
  assert.equal(prompts[1].schema, "producer-review");
  assert.equal(calls[1][2].includes(".palmier-native-plan."), true);
  assert.throws(() => readFileSync(calls[1][2], "utf8"), /ENOENT/);
}

async function legacyGetsDoctrine(dir: string): Promise<void> {
  const prompts: string[] = [];
  const legacy: NonNullable<NativeRunnerDependencies["legacy"]> = async (invocation) => {
    const prompt = invocation.args[invocation.args.indexOf("-p") + 1];
    prompts.push(prompt);
    assert.match(invocation.args.join(" "), /--allowedTools Read,Glob,Grep/);
    assert.equal(invocation.args[invocation.args.indexOf("--model") + 1], "opus");
    return {
      message: JSON.stringify(prompts.length === 1 ? draft() : PASS_REVIEW),
      stderr: "",
      ms: 1,
    };
  };
  await runPalmierNativeEdit({
    dir, request: "Remove the filler word um", scope: { lanes: ["cuts"] },
  }, { provider: () => "legacy", legacy, cli: cliFixture(dir, []) });
  assert.equal(prompts.length, 2);
  assert.ok(prompts.every((prompt) => prompt.includes("FAILURE_LEDGER.md")));
}

async function rejectsScopeDrift(dir: string): Promise<void> {
  let criticCalls = 0;
  const codex: NonNullable<NativeRunnerDependencies["codex"]> = async () => ({
    ...draft(), lanes: ["graphics"],
  });
  await assert.rejects(runPalmierNativeEdit({
    dir, request: "Remove the filler word um", scope: { lanes: ["cuts"] },
  }, {
    provider: () => "codex",
    codex,
    cli: cliFixture(dir, []),
    critic: async () => { criticCalls += 1; return PASS_REVIEW; },
  }), /changed the controller-owned lane scope/);
  assert.equal(criticCalls, 0);
}

async function rejectsToolAndVerdictDrift(dir: string): Promise<void> {
  const codex: NonNullable<NativeRunnerDependencies["codex"]> = async () => ({
    ...draft(),
    operations: [{ tool: "add_texts", args: { entries: [] }, reason: "Adjacent churn" }],
  });
  await assert.rejects(runPalmierNativeEdit({
    dir, request: "Remove the filler word um", scope: { lanes: ["cuts"] },
  }, { provider: () => "codex", codex, cli: cliFixture(dir, []) }), /outside the controller-owned lane scope/);

  await assert.rejects(runPalmierNativeEdit({
    dir, request: "Remove the filler word um", scope: { lanes: ["cuts"] },
  }, {
    provider: () => "codex",
    codex: async () => ({
      ...draft(),
      operations: [{
        tool: "set_clip_properties",
        args: { clipIds: ["clip-1"], opacity: 0.5 },
        reason: "Wrong-lane property hidden inside an allowed tool.",
      }],
    }),
    cli: cliFixture(dir, []),
  }), /arguments are outside the controller-owned lane scope/);

  const badCli = cliFixture(dir, []);
  const cli: NonNullable<NativeRunnerDependencies["cli"]> = async (args, signal) => {
    const value = await badCli(args, signal);
    if (args[1] !== "--execute") return value;
    return { ...value, candidate: { ...(value.candidate as object), qc: { status: "approved", approved: true } } };
  };
  await assert.rejects(runPalmierNativeEdit({
    dir, request: "Remove the filler word um", scope: { lanes: ["cuts"] },
  }, {
    provider: () => "codex",
    codex: async (options) => options.schema === "producer-review" ? PASS_REVIEW : draft(),
    cli,
  }), /bypassed the required QC checkpoint/);
}

async function rejectsMismatchedReconcile(dir: string): Promise<void> {
  let modelCalls = 0;
  const cli: NonNullable<NativeRunnerDependencies["cli"]> = async () => {
    writeFileSync(palmierAuthorityPath(dir), JSON.stringify(authority()));
    return {
      ok: true,
      status: "reconciled",
      authority: { ...authority(), timelineId: "other-timeline" },
    };
  };
  await assert.rejects(runPalmierNativeEdit({
    dir, request: "Remove the filler word um", scope: { lanes: ["cuts"] },
  }, {
    provider: () => "codex",
    codex: async () => { modelCalls += 1; return draft(); },
    cli,
  }), /reconcile verdict does not match/);
  assert.equal(modelCalls, 0, "untrusted reconcile state must fail before a model sees it");
}

async function rejectsIncompleteReadbackBeforePlanning(dir: string): Promise<void> {
  let modelCalls = 0;
  const incomplete = { ...authority(), readbackCoverage: { complete: false } };
  const cli: NonNullable<NativeRunnerDependencies["cli"]> = async () => {
    writeFileSync(palmierAuthorityPath(dir), JSON.stringify(incomplete));
    return { ok: true, status: "reconciled", authority: incomplete };
  };
  await assert.rejects(runPalmierNativeEdit({
    dir, request: "Remove the filler word um", scope: { lanes: ["cuts"] },
  }, {
    provider: () => "codex",
    codex: async () => { modelCalls += 1; return draft(); },
    cli,
  }), /readback is incomplete/);
  assert.equal(modelCalls, 0, "incomplete Palmier authority must fail before planning");
}

async function deterministicGateStopsBeforeCriticAndMutation(dir: string): Promise<void> {
  const cliCalls: string[][] = [];
  let gateCalls = 0;
  let criticCalls = 0;
  await assert.rejects(runPalmierNativeEdit({
    dir, request: "Remove the filler word um", scope: { lanes: ["cuts"] },
  }, {
    provider: () => "codex",
    codex: async () => draft(),
    cli: cliFixture(dir, cliCalls),
    gate: async (input) => {
      gateCalls += 1;
      const plan = JSON.parse(readFileSync(input.planPath, "utf8")) as Record<string, unknown>;
      assert.equal(input.request, "Remove the filler word um");
      assert.deepEqual(input.expectedLanes, ["cuts"]);
      assert.equal(plan.requestHash, "a03f4cc9d50a55c9494c4a4044a89fcec63e692ec46999fd88fb6563b1153ec2");
      throw new Error("native deterministic gate rejected a destructive delta");
    },
    critic: async () => { criticCalls += 1; return PASS_REVIEW; },
  }), /native deterministic gate rejected/);
  assert.equal(gateCalls, 1);
  assert.equal(criticCalls, 0, "the fresh critic must run only after deterministic validation");
  assert.deepEqual(cliCalls, [[dir, "--reconcile"]],
    "a rejected pre-critic gate must not call the Palmier mutation executor");
}

async function twoCleanReviewsAreVisibleBeforeMutation(dir: string): Promise<void> {
  const cliCalls: string[][] = [];
  const events: Array<Record<string, unknown>> = [];
  const reviewedDrafts: string[] = [];
  let gates = 0;
  await runPalmierNativeEdit({
    dir,
    workflow: "initial-auto-edit",
    request: "Remove the filler word um",
    scope: { lanes: ["cuts"] },
  }, {
    provider: () => "codex",
    codex: async () => draft(),
    cli: cliFixture(dir, cliCalls),
    gate: async () => { gates += 1; },
    critic: async (_input, plan) => {
      reviewedDrafts.push(JSON.stringify(plan));
      return PASS_REVIEW;
    },
  }, {
    planReviewsRequired: 2,
    onEvent: (event) => events.push(event),
  });

  assert.equal(gates, 1);
  assert.equal(reviewedDrafts.length, 2);
  assert.equal(reviewedDrafts[0], reviewedDrafts[1],
    "both clean critics must inspect the exact same native draft");
  assert.deepEqual(cliCalls.map((call) => call[1]), ["--reconcile", "--execute"]);
  assert.deepEqual(events.filter((event) => event.event === "palmier_native_progress")
    .map((event) => event.status).filter((status) => [
      "deterministic_gate_passed", "plan_review_started", "plan_review_passed",
    ].includes(String(status))), [
    "deterministic_gate_passed",
    "plan_review_started",
    "plan_review_passed",
    "plan_review_started",
    "plan_review_passed",
  ]);
}

async function realGateRejectsCreativePopBeforeMutation(dir: string): Promise<void> {
  const cliCalls: string[][] = [];
  let criticCalls = 0;
  await assert.rejects(runPalmierNativeEdit({
    dir, request: "Fade the speaker in smoothly", scope: { lanes: ["motion"] },
  }, {
    provider: () => "codex",
    codex: async () => ({
      schemaVersion: 1,
      lanes: ["motion"],
      operations: [{
        tool: "set_keyframes",
        args: { clipId: "clip-1", property: "opacity", keyframes: [[0, 0], [1, 1]] },
        reason: "Fade in the speaker",
      }],
    }),
    cli: cliFixture(dir, cliCalls),
    critic: async () => { criticCalls += 1; return PASS_REVIEW; },
  }), /changes materially in fewer than 3 frames/);
  assert.equal(criticCalls, 0);
  assert.deepEqual(cliCalls, [[dir, "--reconcile"]]);
}

async function main(): Promise<void> {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-palmier-native-ts-"));
  try {
    await codexHappyPath(root);
    await legacyGetsDoctrine(root);
    await rejectsScopeDrift(root);
    await rejectsToolAndVerdictDrift(root);
    await rejectsMismatchedReconcile(root);
    await rejectsIncompleteReadbackBeforePlanning(root);
    await deterministicGateStopsBeforeCriticAndMutation(root);
    await twoCleanReviewsAreVisibleBeforeMutation(root);
    await realGateRejectsCreativePopBeforeMutation(root);
    console.log("palmier-native-runner.test.ts: all assertions passed");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

void main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
