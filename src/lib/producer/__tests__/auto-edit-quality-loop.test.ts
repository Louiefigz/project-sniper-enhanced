import assert from "node:assert/strict";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  runQualityReviewRound,
  type QualityLoopDependencies,
  type QualityLoopRuntime,
} from "../../../app/api/producer/auto-edit/quality-loop";
import type { ProducerReview } from "../../../app/api/producer/auto-edit/review-contract";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import {
  advanceAutoEditJob,
  autoEditJobPath,
  fileSha256,
  startAutoEditJob,
} from "../../server/auto-edit-job-store";
import {
  approvalPath,
  candidateFinalPath,
  prepareQcRound,
} from "../../server/auto-edit-quality-artifacts";
import { diskCheckpointWriter, diskInvalidationWriter } from
  "../../../app/api/producer/auto-edit/pipeline-writers";
import { bindAuthorityProof, planContentHash } from "../../server/auto-edit-authority";
import { autoEditAuthoritySnapshot } from "../../server/auto-edit-authority-snapshot";
import { writePlanningReviewFixtures } from "./auto-edit-approval-fixture";

interface Fixture {
  ctx: AutoEditCtx;
  candidate: string;
  machine: string;
  frame: string;
}

function fixture(root: string, token: string, round = 1): Fixture {
  const dir = path.join(root, "producer");
  const source = path.join(root, "source");
  mkdirSync(dir, { recursive: true });
  mkdirSync(source, { recursive: true });
  const planPath = path.join(dir, "edit_plan.json");
  const manifestPath = path.join(source, "manifest.json");
  writeFileSync(planPath, '{"planVersion":1,"target":{"mode":"short"}}');
  writeFileSync(manifestPath, '{"sources":[]}');
  const ctx: AutoEditCtx = {
    dir, scope: "produced", planPath, manifestPath, transcriptsDir: source,
  };
  const candidateDir = prepareQcRound(dir, token, round);
  const candidate = candidateFinalPath(dir, token, round);
  const frame = path.join(candidateDir, "frame.jpg");
  const machine = path.join(candidateDir, "audit_report.json");
  writeFileSync(candidate, `candidate-${round}`);
  writeFileSync(`${candidate}.assembled.json`, JSON.stringify({
    planHash: planContentHash(planPath), authorityHash: fileSha256(candidate),
  }));
  writeFileSync(frame, "frame");
  writeFileSync(machine, JSON.stringify({ overall: "pass", frames: [{ path: frame }], checks: [] }));
  writeFileSync(path.join(candidateDir, "audit_report.md"), "# pass\n");
  return { ctx, candidate, machine, frame };
}

function runtime(fix: Fixture, token: string, round: number): QualityLoopRuntime {
  startAutoEditJob({
    ctx: fix.ctx, token, snapshots: 0, bootstrapPlanHash: fileSha256(fix.ctx.planPath),
  });
  const planHash = fileSha256(fix.ctx.planPath)!;
  const manifestHash = fileSha256(fix.ctx.manifestPath)!;
  const candidateHash = fileSha256(fix.candidate)!;
  const authority = autoEditAuthoritySnapshot(fix.ctx);
  bindAuthorityProof(fix.candidate, authority, { exists: existsSync, hashFile: fileSha256 });
  writePlanningReviewFixtures(fix.ctx, token, authority, 2);
  const jobPath = autoEditJobPath(fix.ctx.dir);
  advanceAutoEditJob(jobPath, token, {
    checkpoint: "rendered", phase: "quality_check", message: "candidate",
    planHash, reviewedPlanHash: planHash, manifestHash,
    authorityDigest: authority.digest, reviewedAuthorityDigest: authority.digest,
    renderedPlanHash: planHash, renderedManifestHash: manifestHash,
    renderedAuthorityDigest: authority.digest,
    planningRound: 2, planningRoundsRequired: 2,
    qcRound: round, qcRoundsMax: 3,
    candidatePath: fix.candidate, candidateHash,
  });
  return {
    job: (diskCheckpointWriter(jobPath, token))({
      checkpoint: "rendered", phase: "quality_check", message: "candidate",
    }),
    io: {
      send: () => {},
      advance: diskCheckpointWriter(jobPath, token),
      invalidate: diskInvalidationWriter(jobPath, token),
    },
  };
}

function review(verdict: "pass" | "revise" | "block", code = "VISUAL_BAD"): ProducerReview {
  return {
    schemaVersion: 1, stage: "rendered", verdict,
    summary: verdict === "pass" ? "clean" : "defect",
    materialIssues: verdict === "pass" ? [] : [{
      code, severity: "major", lane: "graphics", message: "bad pixels",
      evidence: ["frame.jpg"], requiredAction: "repair placement",
    }],
    findings: [],
  };
}

function passDeps(fix: Fixture, queue: ProducerReview[]): Partial<QualityLoopDependencies> {
  return {
    audit: async () => ({
      event: {
        event: "audit", overall: "pass", machine: fix.machine,
        report: path.join(path.dirname(fix.machine), "audit_report.md"),
      },
      failure: null,
    }),
    review: async () => ({ provider: "codex", ms: 1, review: queue.shift() ?? review("pass") }),
  };
}

async function testApproval(root: string): Promise<void> {
  const fix = fixture(path.join(root, "approval"), "approval");
  const run = runtime(fix, "approval", 1);
  const result = await runQualityReviewRound(run, passDeps(fix, [review("pass"), review("pass")]));
  assert.equal(result.status, "approved");
  assert.ok(existsSync(path.join(fix.ctx.dir, "final.mp4")));
  assert.ok(existsSync(approvalPath(fix.ctx.dir)));
  assert.equal(run.job.finalHash, fileSha256(path.join(fix.ctx.dir, "final.mp4")));
}

async function testRepair(root: string): Promise<void> {
  const fix = fixture(path.join(root, "repair"), "repair");
  const run = runtime(fix, "repair", 1);
  const dependencies = passDeps(fix, [review("revise", "COMPOSITION_BAD"), review("pass")]);
  dependencies.revise = async (_ctx, critique) => {
    writeFileSync(fix.ctx.planPath, '{"planVersion":2,"repaired":true}');
    return {
      provider: "codex", ms: 1,
      receipt: {
        schemaVersion: 1, changedPlan: true,
        addressedIssueCodes: critique.materialIssues.map((issue) => issue.code),
        deferredIssueCodes: [], summary: "fixed",
      },
    };
  };
  const result = await runQualityReviewRound(run, dependencies);
  assert.equal(result.status, "repaired");
  assert.equal(run.job.checkpoint, "plan_authored");
  assert.equal(run.job.planningRound, 0);
  assert.equal(existsSync(path.join(fix.ctx.dir, "final.mp4")), false);
}

async function testCapAndMissingEvidence(root: string): Promise<void> {
  const capped = fixture(path.join(root, "cap"), "cap", 3);
  const capRun = runtime(capped, "cap", 3);
  await assert.rejects(
    runQualityReviewRound(capRun, passDeps(capped, [review("revise"), review("pass")])),
    /candidate cannot be approved/,
  );
  assert.equal(existsSync(path.join(capped.ctx.dir, "final.mp4")), false);

  const missing = fixture(path.join(root, "missing-evidence"), "missing");
  rmSync(missing.machine, { force: true });
  rmSync(missing.frame, { force: true });
  const missingDeps = passDeps(missing, []);
  let reviewCalls = 0;
  missingDeps.review = async () => {
    reviewCalls += 1;
    return { provider: "codex", ms: 1, review: review("pass") };
  };
  await assert.rejects(
    runQualityReviewRound(runtime(missing, "missing", 1), missingDeps),
    /non-plan-repairable defects/,
  );
  assert.equal(reviewCalls, 0);
}

async function testAuditFailureCannotBeOutvoted(root: string): Promise<void> {
  const fix = fixture(path.join(root, "audit-failure"), "audit-failure", 3);
  const run = runtime(fix, "audit-failure", 3);
  let reviewCalls = 0;
  const dependencies = passDeps(fix, [review("pass"), review("pass")]);
  dependencies.audit = async () => ({
    event: {
      event: "audit",
      overall: "fail",
      machine: fix.machine,
      report: path.join(path.dirname(fix.machine), "audit_report.md"),
    },
    failure: "motion_pacing: declared motion was frozen in the rendered candidate",
  });
  dependencies.review = async () => {
    reviewCalls += 1;
    return { provider: "codex", ms: 1, review: review("pass") };
  };
  await assert.rejects(
    runQualityReviewRound(run, dependencies),
    /candidate cannot be approved/,
  );
  assert.equal(reviewCalls, 2, "static critics still cannot override deterministic temporal QC");
  assert.equal(existsSync(path.join(fix.ctx.dir, "final.mp4")), false);
  assert.equal(existsSync(approvalPath(fix.ctx.dir)), false);
}

async function testTemporalWarningCannotBeOutvoted(root: string): Promise<void> {
  const fix = fixture(path.join(root, "temporal-warning"), "temporal-warning", 3);
  writeFileSync(fix.machine, JSON.stringify({
    frames: [{ path: fix.frame }],
    checks: [{
      name: "motion_pacing",
      status: "warn",
      measured: "1 of 5 declared cuts manifested",
      detail: "scene-detect fell well short of the plan cut count",
    }],
  }));
  const run = runtime(fix, "temporal-warning", 3);
  const dependencies = passDeps(fix, [review("pass"), review("pass")]);
  dependencies.audit = async () => ({
    event: {
      event: "audit",
      overall: "warn",
      machine: fix.machine,
      report: path.join(path.dirname(fix.machine), "audit_report.md"),
    },
    failure: null,
  });
  await assert.rejects(
    runQualityReviewRound(run, dependencies),
    /QC_AUDIT_WARN_MOTION_PACING/,
  );
  assert.equal(existsSync(path.join(fix.ctx.dir, "final.mp4")), false);
  assert.equal(existsSync(approvalPath(fix.ctx.dir)), false);
}

async function main(): Promise<void> {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-quality-loop-"));
  try {
    await testApproval(root);
    await testRepair(root);
    await testCapAndMissingEvidence(root);
    await testAuditFailureCannotBeOutvoted(root);
    await testTemporalWarningCannotBeOutvoted(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
  console.log("auto-edit-quality-loop.test.ts: all assertions passed");
}

void main();
