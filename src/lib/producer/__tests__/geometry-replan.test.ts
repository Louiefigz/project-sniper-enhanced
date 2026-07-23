/**
 * Geometry contract v3 A2 — the typed NoLegalRegion → re-plan worker route.
 *
 * Asserts the pure routing decision (one attempt budget, typed-signature
 * gating) AND the wired pipeline behavior: a render-time NoLegalRegion
 * routes ONCE back into the planning loop (revision + fresh gates/review on
 * the new authority) and a second geometry failure terminally fails the job
 * with the typed evidence in the message.
 */
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  decideGeometryFailure,
  noLegalRegionEvidence,
  type GeometryReplanState,
} from "../geometry-replan";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import type { PlanningLoopRuntime } from "../../../app/api/producer/auto-edit/planning-loop";
import {
  runAutoEditPipeline,
  type PipelineDependencies,
  type PipelineRuntime,
} from "../../../app/api/producer/auto-edit/pipeline";
import {
  diskCheckpointWriter,
  diskInvalidationWriter,
} from "../../../app/api/producer/auto-edit/pipeline-writers";
import {
  autoEditJobPath,
  fileSha256,
  startAutoEditJob,
  type AutoEditJob,
} from "../../server/auto-edit-job-store";
import { autoEditAuthoritySnapshot } from "../../server/auto-edit-authority-snapshot";

const EVIDENCE = '{"anchor":"headroom","contentDims":[900,600],"faceWidthFrac":0.6019}';
// The errTail fixture mirrors assemble.py's REAL stderr contract: its main()
// prints the typed {"error": ...} line to stderr as well as stdout, so the
// worker's stderr-only tail genuinely carries the NoLegalRegion token.
const GEOMETRY_TAIL = `{"stage":"graphics","status":"rendered"}\n{"error":"graphics failed: NoLegalRegion: ${EVIDENCE.replaceAll('"', '\\"')}"}`;

function testDecision(): void {
  const state: GeometryReplanState = { attempts: 0 };
  const first = decideGeometryFailure(state, `assemble exited 1. NoLegalRegion: ${EVIDENCE}`);
  assert.equal(first.action, "replan");
  assert.ok(first.action === "replan" && first.evidence.includes("faceWidthFrac"));
  const second = decideGeometryFailure(state, `assemble exited 1. NoLegalRegion: ${EVIDENCE}`);
  assert.equal(second.action, "fail");
  assert.ok(second.action === "fail" && /already attempted once/.test(second.message));
  assert.ok(second.action === "fail" && second.message.includes("NoLegalRegion"));
  const other = decideGeometryFailure({ attempts: 0 }, "assemble exited 1. YDIF dup ratio");
  assert.deepEqual(other, { action: "fail", message: "assemble exited 1. YDIF dup ratio" });
  assert.equal(noLegalRegionEvidence("plain failure"), null);
}

function fixture(root: string): AutoEditCtx {
  const dir = path.join(root, "producer");
  const source = path.join(root, "source");
  mkdirSync(dir, { recursive: true });
  mkdirSync(source, { recursive: true });
  const planPath = path.join(dir, "edit_plan.json");
  const manifestPath = path.join(source, "asset_manifest.json");
  writeFileSync(planPath, '{"planVersion":1,"target":{"mode":"short","scope":"light","lanes":{}},"cutTrack":[]}');
  writeFileSync(manifestPath, '{"sources":[]}');
  writeFileSync(path.join(dir, ".sniper-cut-approval.json"), "{}");
  return {
    dir, scope: "light", planPath, manifestPath, transcriptsDir: source,
    intent: { mode: "short", lanes: {} },
  };
}

function runtime(job: AutoEditJob, events: Record<string, unknown>[]): PipelineRuntime {
  const jobPath = autoEditJobPath(job.ctx.dir);
  return {
    job,
    io: {
      send: (event) => events.push(event),
      sendRaw: (line) => events.push({ raw: line }),
      advance: diskCheckpointWriter(jobPath, job.token),
      invalidate: diskInvalidationWriter(jobPath, job.token),
    },
  };
}

interface Counts { planning: number; assemble: number; revise: number }

function reviewed(run: PlanningLoopRuntime, counts: Counts) {
  counts.planning += 1;
  const planHash = fileSha256(run.job.ctx.planPath)!;
  const authority = autoEditAuthoritySnapshot(run.job.ctx);
  run.job = run.io.advance({
    checkpoint: "plan_reviewed", phase: "validating", message: "reviewed",
    planHash, reviewedPlanHash: planHash,
    manifestHash: fileSha256(run.job.ctx.manifestPath)!,
    authorityDigest: authority.digest, reviewedAuthorityDigest: authority.digest,
    planningRound: 1, planningRoundsRequired: 1,
  });
  return Promise.resolve({ rounds: 1, reviewPaths: [], reviewedPlanHash: planHash });
}

function dependencies(counts: Counts): Partial<PipelineDependencies> {
  return {
    approveCut: async () => ({} as never),
    reviewCut: async () => ({} as never),
    verifyReviewCut: () => ({} as never),
    verifyCut: async () => ({
      gate: "transcript_cut", ok: true, errors: [], warnings: [], exit: 0,
      metrics: { receipt: {
        stage: "planning_gate", planHash: "a".repeat(64),
        manifestHash: "b".repeat(64), transcriptDigest: "c".repeat(64),
        cutTrackDigest: "d".repeat(64), cutDecisionsDigest: "e".repeat(64),
      } },
    }),
    planning: (run) => reviewed(run, counts),
    revise: async (ctx, review, round) => {
      counts.revise += 1;
      assert.ok(Number.isInteger(round) && round >= 1);
      assert.equal(review.materialIssues[0]?.code, "GEOMETRY_NO_LEGAL_REGION");
      assert.ok(review.materialIssues[0]?.message.includes("faceWidthFrac"));
      writeFileSync(ctx.planPath, `{"planVersion":1,"target":{"mode":"short","scope":"light","lanes":{}},"cutTrack":[],"revised":${counts.revise}}`);
      return {
        provider: "legacy" as const, ms: 1,
        receipt: {
          schemaVersion: 1 as const, changedPlan: true,
          addressedIssueCodes: ["GEOMETRY_NO_LEGAL_REGION"],
          deferredIssueCodes: [], summary: "swapped the graphic form",
        },
      };
    },
    baseGuard: async () => {},
    checkpoint: async () => ({ status: "committed" as const }),
    approvedMirror: async () => {},
    palmierPrimary: async () => false,
    assemble: async () => {
      counts.assemble += 1;
      return { code: 1, errTail: GEOMETRY_TAIL };
    },
    quality: async () => {
      throw new Error("quality must not run — assemble never succeeded");
    },
  };
}

async function testRoutesOnceThenFailsTerminally(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "route"));
  const job = startAutoEditJob({
    ctx, token: "geometry", snapshots: 0, bootstrapPlanHash: fileSha256(ctx.planPath),
  });
  const events: Record<string, unknown>[] = [];
  const counts: Counts = { planning: 0, assemble: 0, revise: 0 };
  await assert.rejects(
    runAutoEditPipeline(runtime(job, events), dependencies(counts)),
    (error: Error) => /already attempted once/.test(error.message)
      && error.message.includes("NoLegalRegion")
      && error.message.includes("faceWidthFrac"),
  );
  // Routed exactly once: two render attempts, one revision, and the revised
  // plan went back through the NORMAL planning path (a fresh review of the
  // new authority — not a patch).
  assert.deepEqual(counts, { planning: 2, assemble: 2, revise: 1 });
  assert.ok(events.some((event) => event.event === "geometry_replan"));
  assert.ok(events.some((event) => event.event === "geometry_replan_completed"));
}

async function main(): Promise<void> {
  testDecision();
  const root = mkdtempSync(path.join(os.tmpdir(), "geometry-replan-"));
  try {
    await testRoutesOnceThenFailsTerminally(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
  console.log("geometry-replan tests passed");
}

void main().then(null, (error) => {
  console.error(error);
  process.exit(1);
});
