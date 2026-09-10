import assert from "node:assert/strict";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
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
  promoteApprovedCandidate,
} from "../../server/auto-edit-quality-artifacts";
import { diskCheckpointWriter, diskInvalidationWriter } from
  "../../../app/api/producer/auto-edit/pipeline-writers";
import { bindAuthorityProof, planContentHash } from "../../server/auto-edit-authority";
import { autoEditAuthoritySnapshot } from "../../server/auto-edit-authority-snapshot";
import { writePlanningReviewFixtures } from "./auto-edit-approval-fixture";
import { audioAuditFixture } from "./audit-audio-fixture";

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
  writeFileSync(machine, JSON.stringify({
    ...audioAuditFixture(fileSha256(candidate)!), frames: [{ path: frame }],
  }));
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
    promote: promoteApprovedCandidate,
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
  assert.equal(reviewCalls, 0, "an exhausted deterministic failure cannot be approved or repaired, so no paid critic is needed");
  const route = JSON.parse(readFileSync(path.join(path.dirname(fix.candidate), "terminal-mechanical-routing.json"), "utf8"));
  assert.equal(route.renderedCritics, "not-run"); assert.equal(route.approved, false);
  assert.equal(route.candidateHash, fileSha256(fix.candidate));
  assert.equal(existsSync(path.join(fix.ctx.dir, "final.mp4")), false);
  assert.equal(existsSync(approvalPath(fix.ctx.dir)), false);
}

async function testTemporalWarningCannotBeOutvoted(root: string): Promise<void> {
  const fix = fixture(path.join(root, "temporal-warning"), "temporal-warning", 3);
  writeFileSync(fix.machine, JSON.stringify({
    ...audioAuditFixture(fileSha256(fix.candidate)!),
    frames: [{ path: fix.frame }],
    checks: [...audioAuditFixture().checks, {
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
  dependencies.review = async () => { throw new Error("last-round material temporal failure must stop before critics"); };
  await assert.rejects(
    runQualityReviewRound(run, dependencies),
    /QC_AUDIT_WARN_MOTION_PACING/,
  );
  assert.equal(existsSync(path.join(fix.ctx.dir, "final.mp4")), false);
  assert.equal(existsSync(approvalPath(fix.ctx.dir)), false);
}

async function testEarlierDeterministicFailureStillGetsFullReview(root: string): Promise<void> {
  const fix = fixture(path.join(root, "earlier-audit-failure"), "earlier-audit-failure", 2);
  const run = runtime(fix, "earlier-audit-failure", 2), deps = passDeps(fix, []);
  deps.audit = async () => ({ event: { event: "audit", overall: "fail", machine: fix.machine,
    report: path.join(path.dirname(fix.machine), "audit_report.md") }, failure: "TEST repairable temporal failure" });
  let reviews = 0;
  deps.review = async () => { reviews += 1; return { provider: "codex", ms: 1, review: review("pass") }; };
  deps.revise = async () => { throw new Error("TEST reached ordinary repair after both critics"); };
  await assert.rejects(runQualityReviewRound(run, deps), /ordinary repair after both critics/);
  assert.equal(reviews, 2);
  assert.equal(existsSync(path.join(path.dirname(fix.candidate), "terminal-mechanical-routing.json")), false);
  assert.equal(existsSync(approvalPath(fix.ctx.dir)), false);
}

async function testCleanLastRoundStillRequiresBothCritics(root: string): Promise<void> {
  const fix = fixture(path.join(root, "clean-last-round"), "clean-last-round", 3);
  const run = runtime(fix, "clean-last-round", 3), deps = passDeps(fix, []);
  let reviews = 0;
  deps.review = async () => { reviews += 1; return { provider: "codex", ms: 1, review: review("pass") }; };
  assert.equal((await runQualityReviewRound(run, deps)).status, "approved");
  assert.equal(reviews, 2, "being the last round never substitutes for the required visual reviewers");
  assert.equal(existsSync(path.join(path.dirname(fix.candidate), "terminal-mechanical-routing.json")), false);
}

async function testExhaustedMechanicalWaitsWithoutMutatingMaster(root: string): Promise<void> {
  const fix = fixture(path.join(root, "exhausted-barrier"), "exhausted-barrier", 3);
  const run = runtime(fix, "exhausted-barrier", 3), deps = passDeps(fix, []);
  const final = path.join(fix.ctx.dir, "final.mp4"), approval = approvalPath(fix.ctx.dir);
  writeFileSync(final, "previous master"); writeFileSync(approval, "previous exact approval");
  const before = [fileSha256(final), fileSha256(approval), fileSha256(fix.ctx.planPath), fileSha256(fix.candidate)];
  deps.audit = async () => ({ event: { event: "audit", overall: "fail", machine: fix.machine,
    report: path.join(path.dirname(fix.machine), "audit_report.md") }, failure: "TEST deterministic defect" });
  deps.review = async () => { throw new Error("must not launch exhausted-round critics"); };
  deps.revise = async () => { throw new Error("must not revise an exhausted round"); };
  deps.promote = () => { throw new Error("must not promote failed media"); };
  deps.renderCheckpointSettled = async () => { throw new Error("TEST exact checkpoint failure"); };
  await assert.rejects(runQualityReviewRound(run, deps), /exact checkpoint failure/);
  assert.deepEqual([fileSha256(final), fileSha256(approval), fileSha256(fix.ctx.planPath), fileSha256(fix.candidate)], before);
  assert.equal(existsSync(path.join(path.dirname(fix.candidate), "terminal-mechanical-routing.json")), false);
  let settled = false;
  deps.renderCheckpointSettled = async () => { settled = true; };
  await assert.rejects(runQualityReviewRound(run, deps), /candidate cannot be approved/);
  assert.equal(settled, true);
  assert.deepEqual([fileSha256(final), fileSha256(approval), fileSha256(fix.ctx.planPath), fileSha256(fix.candidate)], before);
  assert.equal(JSON.parse(readFileSync(path.join(path.dirname(fix.candidate), "terminal-mechanical-routing.json"), "utf8")).approved, false);
}

async function testMechanicalAudioStopsBeforeCritics(root: string): Promise<void> {
  for (const variant of ["peak", "stale", "hash", "decode", "missing-row"]) {
    const fix = fixture(path.join(root, `audio-${variant}`), `audio-${variant}`);
    const value = audioAuditFixture(fileSha256(fix.candidate)!);
    if (variant === "peak") {
      Object.assign(value.audioDelivery, { truePeakDbtp: -0.6,
        truePeakExcessDb: -0.6 + 1.5, truePeakWithinCeiling: false, qualified: false });
      value.checks.find((row) => row.name === "loudness_true_peak")!.status = "fail";
    }
    if (variant === "decode") {
      Object.assign(value.audioDelivery, { audioDecodeExitCode: 1, audioDecodeSucceeded: false,
        audioDecodeError: "synthetic decode error", integratedLufs: null, truePeakDbtp: null,
        lufsResidual: null, truePeakExcessDb: null, lufsWithinTolerance: false,
        truePeakWithinCeiling: false, qualified: false });
      value.checks.slice(0, 3).forEach((row) => { row.status = "fail"; });
    }
    if (variant === "stale") value.audioDeliveryPolicyVersion = 1;
    if (variant === "hash") value.finalSha256 = "0".repeat(64);
    if (variant === "missing-row") value.checks.pop();
    writeFileSync(fix.machine, JSON.stringify(value));
    const final = path.join(fix.ctx.dir, "final.mp4");
    writeFileSync(final, "previous approved media stays intact");
    writeFileSync(approvalPath(fix.ctx.dir), "previous approval stays intact");
    const before = fileSha256(final);
    const approvalBefore = fileSha256(approvalPath(fix.ctx.dir));
    const run = runtime(fix, `audio-${variant}`, 1);
    const events: Array<Record<string, unknown>> = [];
    run.io.send = (event) => { events.push(event); };
    const deps = passDeps(fix, []);
    let settled = false;
    deps.renderCheckpointSettled = async () => { settled = true; };
    deps.review = async () => { throw new Error("creative critic must not run"); };
    deps.revise = async () => { throw new Error("creative repair must not run"); };
    deps.promote = () => { throw new Error("unqualified candidate must not promote"); };
    await assert.rejects(runQualityReviewRound(run, deps), /QC_AUDIO_DELIVERY/);
    assert.equal(settled, true);
    assert.equal(fileSha256(final), before);
    assert.equal(fileSha256(approvalPath(fix.ctx.dir)), approvalBefore);
    assert.ok(existsSync(fix.candidate));
    assert.ok(events.some((event) => event.event === "quality_blocked"));
    assert.ok(!events.some((event) => ["candidate_approved", "candidate_promoted"].includes(String(event.event))));
  }
}

async function testMutationsWaitForRenderCheckpoint(root: string): Promise<void> {
  // Approval path: promote (which MOVES the candidate the overlapped render
  // checkpoint may still be hashing) must wait for the publish to settle.
  const fix = fixture(path.join(root, "barrier-approve"), "barrier-approve");
  const run = runtime(fix, "barrier-approve", 1);
  const dependencies = passDeps(fix, [review("pass"), review("pass")]);
  let settled = false;
  dependencies.renderCheckpointSettled = async () => {
    await new Promise((resolve) => setTimeout(resolve, 10));
    settled = true;
  };
  dependencies.promote = (candidate, producerDir, record) => {
    assert.equal(settled, true, "promote must not move the candidate before the publish settles");
    promoteApprovedCandidate(candidate, producerDir, record);
  };
  const result = await runQualityReviewRound(run, dependencies);
  assert.equal(result.status, "approved");
  assert.ok(existsSync(path.join(fix.ctx.dir, "final.mp4")));

  // Repair path: a real checkpoint rejection surfaced by the barrier fails the
  // round BEFORE revise rewrites edit_plan.json (matching the old serial
  // order, where a rejected checkpoint preceded any QC mutation).
  const fix2 = fixture(path.join(root, "barrier-repair"), "barrier-repair");
  const run2 = runtime(fix2, "barrier-repair", 1);
  const rejecting = passDeps(fix2, [review("revise"), review("pass")]);
  let revised = false;
  rejecting.revise = async () => {
    revised = true;
    throw new Error("unreachable");
  };
  rejecting.renderCheckpointSettled = () =>
    Promise.reject(new Error("palmier checkpoint runner crashed"));
  await assert.rejects(
    runQualityReviewRound(run2, rejecting),
    /palmier checkpoint runner crashed/,
  );
  assert.equal(revised, false, "a rejected checkpoint must precede any plan rewrite");
  assert.equal(existsSync(path.join(fix2.ctx.dir, "final.mp4")), false);
}

async function main(): Promise<void> {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-quality-loop-"));
  try {
    await testApproval(root);
    await testRepair(root);
    await testMutationsWaitForRenderCheckpoint(root);
    await testCapAndMissingEvidence(root);
    await testAuditFailureCannotBeOutvoted(root);
    await testTemporalWarningCannotBeOutvoted(root);
    await testEarlierDeterministicFailureStillGetsFullReview(root);
    await testCleanLastRoundStillRequiresBothCritics(root);
    await testExhaustedMechanicalWaitsWithoutMutatingMaster(root);
    await testMechanicalAudioStopsBeforeCritics(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
  console.log("auto-edit-quality-loop.test.ts: all assertions passed");
}

void main();
