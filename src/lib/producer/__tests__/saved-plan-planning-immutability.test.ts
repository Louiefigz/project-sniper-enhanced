import assert from "node:assert/strict";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  runPlanningReviewLoop,
  type PlanningLoopDependencies,
  type PlanningLoopRuntime,
} from "../../../app/api/producer/auto-edit/planning-loop";
import type { GateBundleVerdict } from
  "../../../app/api/producer/auto-edit/planning-gates";
import type { ProducerReview } from
  "../../../app/api/producer/auto-edit/review-contract";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import {
  fileSha256,
  startAutoEditJob,
  type CheckpointUpdate,
} from "../../server/auto-edit-job-store";

const PASS_GATES: GateBundleVerdict = {
  ok: true, errors: [], warnings: [],
  gates: {
    operatorIntent: { gate: "operator_intent", ok: true, errors: [], warnings: [], exit: 0 },
    transcriptCut: { gate: "transcript_cut", ok: true, errors: [], warnings: [], exit: 0 },
    planLint: { gate: "plan_lint", ok: true, errors: [], warnings: [], exit: 0 },
    hookContract: { gate: "hook_contract", ok: true, errors: [], warnings: [], exit: 0 },
    templateUsage: { gate: "template_usage", ok: true, errors: [], warnings: [], exit: 0 },
    claimsContract: { gate: "claims_contract", ok: true, errors: [], warnings: [], exit: 0 },
    compSize: { gate: "comp_size", ok: true, errors: [], warnings: [], exit: 0 },
    geometryFeasibility: {
      gate: "geometry_feasibility", ok: true, errors: [], warnings: [], exit: 0,
    },
    referenceLint: null,
  },
};

const FAIL_GATES: GateBundleVerdict = {
  ...PASS_GATES,
  ok: false,
  errors: [{ gate: "plan_lint", message: "runtime registry is unavailable" }],
  gates: {
    ...PASS_GATES.gates,
    planLint: {
      gate: "plan_lint", ok: false,
      errors: ["runtime registry is unavailable"], warnings: [], exit: 1,
    },
  },
};

interface Counts {
  review: number;
  revisionWriter: number;
  gateFixWriter: number;
  snapshot: number;
}

function fixture(root: string): AutoEditCtx {
  const dir = path.join(root, "producer");
  const source = path.join(root, "source");
  mkdirSync(dir, { recursive: true });
  mkdirSync(source, { recursive: true });
  const planPath = path.join(dir, "edit_plan.json");
  const manifestPath = path.join(source, "asset_manifest.json");
  const transcriptPath = path.join(source, "source-1.transcript.json");
  const intent = { mode: "short" as const, lanes: {} };
  writeFileSync(planPath, JSON.stringify({
    planVersion: 1, target: { mode: "short" },
    cutTrack: [{ sourceId: "source-1", start: 0, end: 2 }],
  }, null, 2) + "\n");
  writeFileSync(manifestPath, JSON.stringify({
    sources: [{ id: "source-1", transcriptPath: path.basename(transcriptPath) }],
  }));
  writeFileSync(transcriptPath, JSON.stringify({
    transcript: [{
      start: 0, end: 2, text: "Exact saved words.",
      words: [
        { word: "Exact", start: 0, end: 0.5 },
        { word: "saved", start: 0.6, end: 1.1 },
        { word: "words.", start: 1.2, end: 2 },
      ],
    }],
  }));
  writeFileSync(path.join(root, "project.json"), JSON.stringify({ intent }));
  return {
    dir, scope: "light", intent, planPath, manifestPath, transcriptsDir: source,
    templateUsage: {
      schemaVersion: 1,
      path: path.join(dir, ".sniper-learning/runs/unbound/template-usage.json"),
      digest: "a".repeat(64),
    },
  };
}

function runtime(
  ctx: AutoEditCtx,
  events: Array<Record<string, unknown>>,
): PlanningLoopRuntime {
  const hash = fileSha256(ctx.planPath)!;
  const holder = {} as PlanningLoopRuntime;
  holder.job = startAutoEditJob({
    ctx, token: `saved-${path.basename(path.dirname(ctx.dir))}`,
    snapshots: 0, bootstrapPlanHash: hash, reviewSavedPlan: true,
  });
  const update = (value: CheckpointUpdate) => {
    holder.job = { ...holder.job, ...value };
    return holder.job;
  };
  holder.io = { send: (event) => events.push(event), advance: update, invalidate: update };
  return holder;
}

function dependencies(
  gates: GateBundleVerdict,
  review: ProducerReview,
  counts: Counts,
): Partial<PlanningLoopDependencies> {
  return {
    gate: async () => gates,
    review: async () => {
      counts.review += 1;
      return { provider: "codex", ms: 1, review };
    },
    revise: async () => {
      counts.revisionWriter += 1;
      throw new Error("saved-plan revision writer must not run");
    },
    gateFix: async () => {
      counts.gateFixWriter += 1;
      throw new Error("saved-plan gate-fix writer must not run");
    },
    snapshot: () => {
      counts.snapshot += 1;
      throw new Error("saved-plan planning must not snapshot for a writer");
    },
    approve: () => {},
  };
}

async function assertImmutableFailure(
  root: string,
  gates: GateBundleVerdict,
  review: ProducerReview,
): Promise<{ events: Array<Record<string, unknown>>; counts: Counts }> {
  const ctx = fixture(root);
  const before = readFileSync(ctx.planPath);
  const beforeHash = fileSha256(ctx.planPath);
  const events: Array<Record<string, unknown>> = [];
  const counts = { review: 0, revisionWriter: 0, gateFixWriter: 0, snapshot: 0 };
  await assert.rejects(
    runPlanningReviewLoop(runtime(ctx, events), dependencies(gates, review, counts)),
    /saved-plan planning review found material issues; complete plan was not modified/,
  );
  assert.deepEqual(readFileSync(ctx.planPath), before);
  assert.equal(fileSha256(ctx.planPath), beforeHash);
  assert.equal(events.some((event) => [
    "planning_gate_revision_required", "gate_fix_started", "revision_started",
  ].includes(String(event.event))), false);
  assert.deepEqual(
    { revisionWriter: counts.revisionWriter, gateFixWriter: counts.gateFixWriter,
      snapshot: counts.snapshot },
    { revisionWriter: 0, gateFixWriter: 0, snapshot: 0 },
  );
  return { events, counts };
}

async function main(): Promise<void> {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-saved-plan-planning-"));
  try {
    const machine = await assertImmutableFailure(
      path.join(root, "machine"), FAIL_GATES,
      { schemaVersion: 1, stage: "plan", verdict: "pass",
        summary: "critic never runs", materialIssues: [], findings: [] },
    );
    assert.equal(machine.counts.review, 0);
    assert.ok(machine.events.some((event) =>
      event.event === "saved_plan_planning_gate_failed"));

    const critic = await assertImmutableFailure(
      path.join(root, "critic"), PASS_GATES,
      { schemaVersion: 1, stage: "plan", verdict: "revise",
        summary: "needs work", findings: [], materialIssues: [{
          code: "PLAN_STYLE", severity: "major", lane: "graphics",
          message: "change it", evidence: ["review"], requiredAction: "revise",
        }] },
    );
    assert.equal(critic.counts.review, 1);

    const changed = fixture(path.join(root, "changed-before-review"));
    const changedEvents: Array<Record<string, unknown>> = [];
    const changedRun = runtime(changed, changedEvents);
    writeFileSync(changed.planPath, `${readFileSync(changed.planPath, "utf8")} `);
    const changedCounts = {
      review: 0, revisionWriter: 0, gateFixWriter: 0, snapshot: 0,
    };
    await assert.rejects(
      runPlanningReviewLoop(changedRun, dependencies(
        PASS_GATES,
        { schemaVersion: 1, stage: "plan", verdict: "pass",
          summary: "must not run", materialIssues: [], findings: [] },
        changedCounts,
      )),
      /complete saved plan changed before planning review; no writer was launched/,
    );
    assert.deepEqual(changedCounts, {
      review: 0, revisionWriter: 0, gateFixWriter: 0, snapshot: 0,
    });
    assert.deepEqual(changedEvents, []);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
  console.log("saved-plan-planning-immutability.test.ts: all assertions passed");
}

void main();
