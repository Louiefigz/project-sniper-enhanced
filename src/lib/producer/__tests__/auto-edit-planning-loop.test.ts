import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  runPlanningReviewLoop,
  type PlanningLoopDependencies,
  type PlanningLoopRuntime,
} from "../../../app/api/producer/auto-edit/planning-loop";
import type { GateBundleVerdict } from "../../../app/api/producer/auto-edit/planning-gates";
import type { ProducerReview } from "../../../app/api/producer/auto-edit/review-contract";
import type { AutoEditCtx, AutoEditScope } from "../../../app/api/producer/auto-edit/stream";
import {
  autoEditJobPath,
  fileSha256,
  startAutoEditJob,
} from "../../server/auto-edit-job-store";
import { diskCheckpointWriter, diskInvalidationWriter } from
  "../../../app/api/producer/auto-edit/pipeline-writers";
import { planningRoundDir } from "../../server/auto-edit-quality-artifacts";

const PASS_GATES: GateBundleVerdict = {
  ok: true, errors: [], warnings: [],
  gates: {
    operatorIntent: { gate: "operator_intent", ok: true, errors: [], warnings: [], exit: 0 },
    transcriptCut: { gate: "transcript_cut", ok: true, errors: [], warnings: [], exit: 0 },
    planLint: { gate: "plan_lint", ok: true, errors: [], warnings: [], exit: 0 },
    hookContract: { gate: "hook_contract", ok: true, errors: [], warnings: [], exit: 0 },
    templateUsage: { gate: "template_usage", ok: true, errors: [], warnings: [], exit: 0 },
    claimsContract: { gate: "claims_contract", ok: true, errors: [], warnings: [], exit: 0 },
    referenceLint: null,
  },
};

const FAIL_GATES: GateBundleVerdict = {
  ...PASS_GATES,
  ok: false,
  errors: [{ gate: "plan_lint", message: "cut 1 starts outside source duration" }],
  gates: {
    ...PASS_GATES.gates,
    planLint: {
      gate: "plan_lint", ok: false,
      errors: ["cut 1 starts outside source duration"], warnings: [], exit: 1,
    },
  },
};

function failGates(count: number): GateBundleVerdict {
  const messages = Array.from({ length: count }, (_, i) => `violation ${i + 1}`);
  return {
    ...PASS_GATES,
    ok: false,
    errors: messages.map((message) => ({ gate: "plan_lint" as const, message })),
    gates: {
      ...PASS_GATES.gates,
      planLint: { gate: "plan_lint", ok: false, errors: messages, warnings: [], exit: 1 },
    },
  };
}

function ctx(root: string, scope: AutoEditScope): AutoEditCtx {
  const dir = path.join(root, "producer");
  const source = path.join(root, "source");
  mkdirSync(dir, { recursive: true });
  mkdirSync(source, { recursive: true });
  const planPath = path.join(dir, "edit_plan.json");
  const manifestPath = path.join(source, "manifest.json");
  const transcriptPath = path.join(source, "source-1.transcript.json");
  writeFileSync(planPath, '{"planVersion":1,"target":{"mode":"short"}}');
  writeFileSync(transcriptPath, JSON.stringify({ transcript: [{
    start: 0, end: 5, text: "A complete test sentence.",
    words: [{ word: "A", start: 0, end: 0.3 }, { word: "complete", start: 0.4, end: 1 }],
  }] }));
  writeFileSync(manifestPath, JSON.stringify({
    sources: [{ id: "source-1", transcriptPath: path.basename(transcriptPath) }],
  }));
  return {
    dir, scope, planPath, manifestPath, transcriptsDir: source,
    intent: { mode: "short", lanes: {} },
    templateUsage: {
      schemaVersion: 1,
      path: path.join(dir, ".sniper-learning/runs/unbound/template-usage.json"),
      digest: "a".repeat(64),
    },
  };
}

function runtime(context: AutoEditCtx, token: string): PlanningLoopRuntime {
  const job = startAutoEditJob({
    ctx: context, token, snapshots: 0, bootstrapPlanHash: fileSha256(context.planPath),
  });
  const jobPath = autoEditJobPath(context.dir);
  return {
    job,
    io: {
      send: () => {},
      advance: diskCheckpointWriter(jobPath, token),
      invalidate: diskInvalidationWriter(jobPath, token),
    },
  };
}

function review(verdict: "pass" | "revise", code = "PLAN_ISSUE"): ProducerReview {
  return {
    schemaVersion: 1, stage: "plan", verdict,
    summary: verdict === "pass" ? "clean" : "needs revision",
    materialIssues: verdict === "pass" ? [] : [{
      code, severity: "major", lane: "cuts", message: "bad decision",
      evidence: ["transcript beat"], requiredAction: "change the plan",
    }],
    findings: [],
  };
}

interface Counters {
  gates: number;
  reviews: number;
  revisions: number;
  gateFixes: number;
}

function deps(
  context: AutoEditCtx,
  queue: ProducerReview[],
  counts: Counters,
  noOp = false,
  gates: GateBundleVerdict[] = [],
): Partial<PlanningLoopDependencies> {
  return {
    approve: () => {},
    gate: async () => {
      counts.gates += 1;
      return gates.shift() ?? PASS_GATES;
    },
    review: async () => {
      counts.reviews += 1;
      return { provider: "codex", ms: 1, review: queue.shift() ?? review("pass") };
    },
    revise: async (_ctx, critique) => {
      counts.revisions += 1;
      if (!noOp) writeFileSync(context.planPath, JSON.stringify({
        planVersion: counts.revisions + 1,
        cutTrack: [{ sourceId: "source-1", start: 0, end: counts.revisions + 1 }],
      }));
      return {
        provider: "codex", ms: 1,
        receipt: {
          schemaVersion: 1, changedPlan: true,
          addressedIssueCodes: critique.materialIssues.map((issue) => issue.code),
          deferredIssueCodes: [], summary: "revised",
        },
      };
    },
    gateFix: async (_ctx, critique) => {
      counts.gateFixes += 1;
      writeFileSync(context.planPath, JSON.stringify({
        planVersion: 100 + counts.gateFixes,
        cutTrack: [{ sourceId: "source-1", start: 0, end: 100 + counts.gateFixes }],
      }));
      return {
        provider: "codex", ms: 1,
        receipt: {
          schemaVersion: 1, changedPlan: true,
          addressedIssueCodes: critique.materialIssues.map((issue) => issue.code),
          deferredIssueCodes: [], summary: "gate fixed",
        },
      };
    },
  };
}

async function testRequiredRounds(root: string): Promise<void> {
  const produced = ctx(path.join(root, "produced"), "produced");
  const producedCounts = { gates: 0, reviews: 0, revisions: 0, gateFixes: 0 };
  const producedRun = runtime(produced, "produced");
  const result = await runPlanningReviewLoop(
    producedRun, deps(produced, [review("pass"), review("pass")], producedCounts),
  );
  assert.equal(result.rounds, 2);
  assert.deepEqual(producedCounts, { gates: 1, reviews: 2, revisions: 0, gateFixes: 0 });
  assert.equal(producedRun.job.checkpoint, "plan_reviewed");

  const light = ctx(path.join(root, "light"), "light");
  const lightCounts = { gates: 0, reviews: 0, revisions: 0, gateFixes: 0 };
  const lightResult = await runPlanningReviewLoop(
    runtime(light, "light"), deps(light, [review("pass")], lightCounts),
  );
  assert.equal(lightResult.rounds, 1);
  assert.deepEqual(lightCounts, { gates: 1, reviews: 1, revisions: 0, gateFixes: 0 });
}

async function testRevisionAndRerun(root: string): Promise<void> {
  const context = ctx(path.join(root, "revision"), "produced");
  const counts = { gates: 0, reviews: 0, revisions: 0, gateFixes: 0 };
  const run = runtime(context, "revision");
  const result = await runPlanningReviewLoop(
    run,
    deps(context, [review("revise"), review("pass"), review("pass")], counts),
  );
  assert.equal(result.rounds, 4);
  assert.deepEqual(counts, { gates: 2, reviews: 4, revisions: 1, gateFixes: 0 });
  // A 2-wide critic batch is ONE round against the budget: one dirty cycle +
  // one clean cycle.
  assert.equal(run.job.planningCycles, 2);
}

async function testCapsAndNoOp(root: string): Promise<void> {
  // The cap counts revision CYCLES: 4 dirty 2-wide batches = 4 cycles, and the
  // 4th dirty cycle stops with the exhaustion verdict BEFORE paying a doomed
  // revision (3 revisions, not 4).
  const capped = ctx(path.join(root, "capped"), "produced");
  const capCounts = { gates: 0, reviews: 0, revisions: 0, gateFixes: 0 };
  await assert.rejects(
    runPlanningReviewLoop(
      runtime(capped, "capped"),
      deps(capped, Array.from({ length: 8 }, (_, i) => review("revise", `ISSUE_${i}`)), capCounts),
    ),
    /exhausted 4 rounds/,
  );
  assert.deepEqual(capCounts, { gates: 4, reviews: 8, revisions: 3, gateFixes: 0 });

  const noOp = ctx(path.join(root, "noop"), "produced");
  await assert.rejects(
    runPlanningReviewLoop(
      runtime(noOp, "noop"),
      deps(noOp, [review("revise")], { gates: 0, reviews: 0, revisions: 0, gateFixes: 0 }, true),
    ),
    /did not change edit_plan\.json/,
  );
}

async function testPacketPrecedesCritic(root: string): Promise<void> {
  const context = ctx(path.join(root, "packet-before-critic"), "light");
  const counts = { gates: 0, reviews: 0, revisions: 0, gateFixes: 0 };
  let packetPath = "";
  let gatesPath = "";
  const base = deps(context, [], counts);
  await assert.rejects(runPlanningReviewLoop(runtime(context, "packet-timeout"), {
    ...base,
    review: async (request) => {
      assert.equal(request.stage, "plan");
      if (request.stage !== "plan") throw new Error("unexpected rendered review");
      packetPath = request.packet.path;
      gatesPath = path.join(path.dirname(path.dirname(packetPath)), "planning-gates.json");
      assert.ok(existsSync(packetPath), "critic packet must exist before invocation");
      assert.ok(existsSync(gatesPath), "gate evidence must exist before invocation");
      const gates = JSON.parse(readFileSync(gatesPath, "utf8")) as { inputPacket?: { hash?: string } };
      assert.equal(gates.inputPacket?.hash, request.packet.hash);
      throw new Error("simulated critic timeout");
    },
  }), /simulated critic timeout/);
  assert.ok(existsSync(packetPath), "timeout must retain the critic packet");
  assert.ok(existsSync(gatesPath), "timeout must retain deterministic gate evidence");
  assert.ok(!existsSync(path.join(path.dirname(gatesPath), "plan-review.json")));
}

async function testGateFailureRoutesToBoundedFixer(root: string): Promise<void> {
  const context = ctx(path.join(root, "gate-fast-path"), "produced");
  const counts = { gates: 0, reviews: 0, revisions: 0, gateFixes: 0 };
  const run = runtime(context, "gate-fast-path");
  const events: Array<Record<string, unknown>> = [];
  run.io.send = (event) => events.push(event);
  const dependencies = deps(
    context, [review("pass"), review("pass")], counts, false,
    [FAIL_GATES, PASS_GATES, PASS_GATES],
  );
  const originalGateFix = dependencies.gateFix!;
  let evidenceExistedBeforeFix = false;
  dependencies.gateFix = async (fixCtx, critique, round) => {
    const dir = planningRoundDir(context.dir, run.job.artifactToken ?? run.job.token, round);
    const gatesPath = path.join(dir, "planning-gates.json");
    const reviewPath = path.join(dir, "plan-review.json");
    const machine = JSON.parse(readFileSync(reviewPath, "utf8")) as {
      reviewSource?: string; inputPacket?: { hash?: string }; review?: ProducerReview;
    };
    const gates = JSON.parse(readFileSync(gatesPath, "utf8")) as {
      inputPacket?: { hash?: string };
    };
    assert.equal(machine.reviewSource, "deterministic-gates");
    assert.equal(machine.inputPacket?.hash, gates.inputPacket?.hash);
    assert.deepEqual(machine.review, critique);
    evidenceExistedBeforeFix = true;
    return originalGateFix(fixCtx, critique, round);
  };
  const result = await runPlanningReviewLoop(run, dependencies);
  // Gate-failure round 1 is fixed by the bounded fixer without spawning the
  // full revision writer or charging the cycle budget; rounds 2-3 are the
  // clean critic batch.
  assert.equal(result.rounds, 3);
  assert.deepEqual(counts, { gates: 2, reviews: 2, revisions: 0, gateFixes: 1 });
  assert.ok(evidenceExistedBeforeFix);
  assert.equal(run.job.planningCycles, 1);
  assert.equal(events.filter((event) => event.event === "planning_review_started").length, 2);
  assert.equal(events.filter((event) => event.event === "planning_gate_revision_required").length, 1);
  assert.equal(events.filter((event) => event.event === "gate_fix_started").length, 1);
  assert.equal(events.filter((event) => event.event === "gate_fix_completed").length, 1);
}

async function testGateFixerCapFallsThroughToFullPath(root: string): Promise<void> {
  const context = ctx(path.join(root, "gate-fix-cap"), "produced");
  const counts = { gates: 0, reviews: 0, revisions: 0, gateFixes: 0 };
  const run = runtime(context, "gate-fix-cap");
  const events: Array<Record<string, unknown>> = [];
  run.io.send = (event) => events.push(event);
  const result = await runPlanningReviewLoop(run, deps(
    context, [review("pass"), review("pass")], counts, false,
    [FAIL_GATES, FAIL_GATES, FAIL_GATES, PASS_GATES, PASS_GATES],
  ));
  // Attempt 1 is free; the second identical-size gate failure trips the
  // no-progress guard and pays the full revision writer; the third failure
  // starts a fresh fixer chain (attempt 2) before the clean batch converges.
  assert.deepEqual(counts, { gates: 4, reviews: 2, revisions: 1, gateFixes: 2 });
  assert.equal(result.rounds, 5);
  assert.equal(run.job.planningCycles, 2);
  assert.equal(events.filter((event) => event.event === "gate_fix_started").length, 2);
  assert.equal(events.filter((event) => event.event === "revision_started").length, 1);
}

async function testGateFixNoProgressFallsThrough(root: string): Promise<void> {
  const context = ctx(path.join(root, "gate-fix-no-progress"), "produced");
  const counts = { gates: 0, reviews: 0, revisions: 0, gateFixes: 0 };
  const run = runtime(context, "gate-fix-no-progress");
  const events: Array<Record<string, unknown>> = [];
  run.io.send = (event) => events.push(event);
  const result = await runPlanningReviewLoop(run, deps(
    context, [review("pass"), review("pass")], counts, false,
    [failGates(2), failGates(3), PASS_GATES],
  ));
  // The first fixer spawn left MORE gate errors than it started with (2 -> 3):
  // the no-progress guard denies a second consecutive spawn and charges the
  // grown critique to the full revision writer instead.
  assert.deepEqual(counts, { gates: 3, reviews: 2, revisions: 1, gateFixes: 1 });
  assert.equal(result.rounds, 4);
  assert.equal(events.filter((event) => event.event === "gate_fix_started").length, 1);
  assert.equal(events.filter((event) => event.event === "revision_started").length, 1);
}

async function testGateFixRunCapFallsThrough(root: string): Promise<void> {
  const context = ctx(path.join(root, "gate-fix-run-cap"), "produced");
  const counts = { gates: 0, reviews: 0, revisions: 0, gateFixes: 0 };
  const run = runtime(context, "gate-fix-run-cap");
  const events: Array<Record<string, unknown>> = [];
  run.io.send = (event) => events.push(event);
  const result = await runPlanningReviewLoop(run, deps(
    context, [review("pass"), review("pass")], counts, false,
    [failGates(5), failGates(4), failGates(3), failGates(2), failGates(1), PASS_GATES],
  ));
  // Every failure shrinks the error set, so the no-progress guard stays open —
  // but five consecutive gate failures buy exactly MAX_GATE_FIX_TOTAL=3 fixer
  // spawns across the run (attempts 1-2, per-cycle cap -> revision, attempt 3,
  // run cap -> revision, clean batch). The fourth spawn is never funded.
  assert.deepEqual(counts, { gates: 6, reviews: 2, revisions: 2, gateFixes: 3 });
  assert.equal(result.rounds, 7);
  assert.equal(events.filter((event) => event.event === "gate_fix_started").length, 3);
  assert.equal(events.filter((event) => event.event === "revision_started").length, 2);
}

async function testFailedFixerFallsThroughImmediately(root: string): Promise<void> {
  const context = ctx(path.join(root, "gate-fix-broken"), "produced");
  const counts = { gates: 0, reviews: 0, revisions: 0, gateFixes: 0 };
  const run = runtime(context, "gate-fix-broken");
  const events: Array<Record<string, unknown>> = [];
  run.io.send = (event) => events.push(event);
  const dependencies = deps(
    context, [review("pass"), review("pass")], counts, false,
    [FAIL_GATES, PASS_GATES, PASS_GATES],
  );
  dependencies.gateFix = async () => {
    counts.gateFixes += 1;
    throw new Error("fixer spawn broke");
  };
  const result = await runPlanningReviewLoop(run, dependencies);
  // A broken fixer never blocks the run: the same gate failure is charged to
  // the existing full revision path in the same iteration.
  assert.deepEqual(counts, { gates: 2, reviews: 2, revisions: 1, gateFixes: 1 });
  assert.equal(result.rounds, 3);
  assert.equal(events.filter((event) => event.event === "gate_fix_failed").length, 1);
  assert.equal(events.filter((event) => event.event === "revision_started").length, 1);
}

async function testOnlyFirstCriticCleanPlanPublishes(root: string): Promise<void> {
  const context = ctx(path.join(root, "publish-after-clean"), "produced");
  const counts = { gates: 0, reviews: 0, revisions: 0, gateFixes: 0 };
  const checkpoints: Array<{ stage: string; round: number }> = [];
  const dependencies = deps(
    context, [review("pass"), review("pass")], counts, false,
    [FAIL_GATES, PASS_GATES, PASS_GATES],
  );
  let cleanRoundsAtPublish = -1;
  dependencies.checkpoint = async (_ctx, spec) => {
    checkpoints.push(spec);
    // The clean round must already be committed to the journal BEFORE the
    // courtesy publish runs — the publish consumes state, never gates it.
    const journal = JSON.parse(readFileSync(autoEditJobPath(context.dir), "utf8")) as {
      planningCleanRounds?: number;
    };
    cleanRoundsAtPublish = journal.planningCleanRounds ?? 0;
    return { status: "committed" as const };
  };
  await runPlanningReviewLoop(
    runtime(context, "publish-after-clean"), dependencies,
  );
  assert.deepEqual(checkpoints, [{ stage: "revision", round: 2 }]);
  assert.equal(cleanRoundsAtPublish, 1);
}

async function main(): Promise<void> {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-planning-loop-"));
  try {
    await testRequiredRounds(root);
    await testRevisionAndRerun(root);
    await testCapsAndNoOp(root);
    await testPacketPrecedesCritic(root);
    await testGateFailureRoutesToBoundedFixer(root);
    await testGateFixerCapFallsThroughToFullPath(root);
    await testGateFixNoProgressFallsThrough(root);
    await testGateFixRunCapFallsThrough(root);
    await testFailedFixerFallsThroughImmediately(root);
    await testOnlyFirstCriticCleanPlanPublishes(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
  console.log("auto-edit-planning-loop.test.ts: all assertions passed");
}

void main();
