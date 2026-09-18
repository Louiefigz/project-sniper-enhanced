import assert from "node:assert/strict";
import {
  mkdirSync,
  mkdtempSync,
  rmSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import { runAutoEditPipeline } from
  "../../../app/api/producer/auto-edit/pipeline";
import {
  fileSha256,
  startAutoEditJob,
} from "../../server/auto-edit-job-store";
import {
  AUTO_EDIT_PROMOTION_RECONCILIATION_FILE,
  candidateFinalPath,
} from
  "../../server/auto-edit-quality-artifacts";
import { writePlanRefitReceipt } from "../../../app/api/_lib/plan-refit-transaction";
import { cutTrackHash } from "../../../app/api/_lib/plan-refit-receipt";
import {
  checkpointApprovedJob,
  checkpointRenderingJob,
  dependencies,
  fixture,
  runtime,
  writeAuthority,
} from "./_auto-edit-pipeline-resume-fixture";

async function testFreshCandidate(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "fresh"));
  writePlanRefitReceipt(ctx.dir, {
    schemaVersion: 2,
    transactionState: "committed",
    source: "saved-plan",
    createdAt: new Date().toISOString(),
    inputPlanHash: fileSha256(ctx.planPath)!,
    planHash: fileSha256(ctx.planPath)!,
    sourceCutHash: cutTrackHash([]),
    targetCutHash: cutTrackHash([]),
    sourceCutTrack: [],
    targetCutTrack: [],
    remapped: 2,
    dropped: 1,
    changes: [{ track: "graphicsTrack", index: 0, action: "dropped" }],
  }, ctx.planPath);
  const job = startAutoEditJob({
    ctx, token: "fresh", snapshots: 0, bootstrapPlanHash: fileSha256(ctx.planPath),
  });
  const events: Record<string, unknown>[] = [];
  const counts = { author: 0, planning: 0, assemble: 0, quality: 0 };
  const run = runtime(job, events);
  const deps = dependencies(counts);
  const checkpointStages: string[] = [];
  let authorityInitialized = false;
  const quality = deps.quality!;
  deps.initializeAuthority = (input) => {
    assert.equal(input.candidatePath, run.job.candidatePath);
    assert.equal(input.expectedCandidateHash, run.job.candidateHash);
    assert.equal(input.expectedPlanHash, run.job.renderedPlanHash);
    assert.equal(input.expectedManifestHash, run.job.renderedManifestHash);
    authorityInitialized = true;
    return {
      status: "initialized" as const,
      revisionHash: "8".repeat(64),
    };
  };
  deps.quality = async (...args) => {
    assert.equal(authorityInitialized, true);
    return quality(...args);
  };
  deps.checkpoint = async (_ctx, spec) => {
    checkpointStages.push(spec.stage);
    return { status: "committed" as const };
  };
  await runAutoEditPipeline(run, deps);
  assert.deepEqual(counts, { author: 0, planning: 1, assemble: 1, quality: 1 });
  assert.deepEqual(checkpointStages, ["render"]);
  assert.ok(run.job.candidatePath?.includes(`${path.sep}.sniper-qc${path.sep}`));
  assert.equal(run.job.qcRound, 1);
  assert.ok(events.some((event) => event.event === "candidate_ready"));
  assert.ok(events.some((event) =>
    event.event === "producer_revision_authority"
      && event.revisionHash === "8".repeat(64)));
  assert.ok(events.some((event) => event.event === "plan_refit_receipt"
    && event.remapped === 2 && event.dropped === 1));
}

async function testMissingPlanReauthors(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "missing"));
  const job = startAutoEditJob({
    ctx, token: "missing", snapshots: 0, bootstrapPlanHash: fileSha256(ctx.planPath),
  });
  unlinkSync(ctx.planPath);
  const events: Record<string, unknown>[] = [];
  const counts = { author: 0, planning: 0, assemble: 0, quality: 0 };
  await runAutoEditPipeline(runtime(job, events), dependencies(counts));
  assert.equal(counts.author, 1);
  assert.ok(events.some((event) => event.reason === "cut_approval_missing"));
}

async function testBrokenCandidateFailsClosed(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "broken"));
  const job = startAutoEditJob({
    ctx, token: "broken", snapshots: 0, bootstrapPlanHash: fileSha256(ctx.planPath),
  });
  const counts = { author: 0, planning: 0, assemble: 0, quality: 0 };
  const deps = dependencies(counts);
  deps.assemble = async () => ({ code: 0, errTail: "" });
  await assert.rejects(
    runAutoEditPipeline(runtime(job, []), deps),
    /without writing fresh final\.mp4 authority proof/,
  );
  assert.equal(counts.quality, 0);
}

async function testApprovedResumeSkipsCandidate(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "approved-resume"));
  const job = checkpointApprovedJob(ctx, "approved-resume");
  const counts = { author: 0, planning: 0, assemble: 0, quality: 0 };
  const events: Record<string, unknown>[] = [];
  await runAutoEditPipeline(runtime(job, events), dependencies(counts));
  assert.deepEqual(counts, { author: 0, planning: 1, assemble: 0, quality: 0 });
  assert.ok(events.some((event) => event.event === "outputs" && event.resumed === true));
}

async function testLegacyApprovalCannotBypassRevisionAuthority(
  root: string,
): Promise<void> {
  const ctx = fixture(path.join(root, "legacy-approved-resume"));
  const job = checkpointApprovedJob(ctx, "legacy-approved-resume");
  const counts = { author: 0, planning: 0, assemble: 0, quality: 0 };
  const deps = dependencies(counts);
  let graphChecked = false;
  deps.approvedRevisionReady = () => false;
  deps.renderGraphReady = () => {
    graphChecked = true;
    return true;
  };
  await runAutoEditPipeline(runtime(job, []), deps);
  assert.deepEqual(counts, {
    author: 0, planning: 1, assemble: 1, quality: 1,
  });
  assert.equal(
    graphChecked,
    false,
    "legacy approval must fail before graph-only resume can authorize reuse",
  );
}

async function testRenderingCrashRetriesSameRound(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "rendering-resume"));
  const token = "rendering-resume";
  const job = checkpointRenderingJob(ctx, token);
  const abandoned = candidateFinalPath(ctx.dir, token, 1);
  mkdirSync(path.dirname(abandoned), { recursive: true });
  writeAuthority(abandoned, ctx.planPath, "partial-before-checkpoint");
  const counts = { author: 0, planning: 0, assemble: 0, quality: 0 };
  const run = runtime(job, []);
  await runAutoEditPipeline(run, dependencies(counts));
  assert.deepEqual(counts, { author: 0, planning: 1, assemble: 1, quality: 1 });
  assert.equal(run.job.qcRound, 1, "a render interruption must not consume QC round 2");
  assert.equal(run.job.candidatePath, candidateFinalPath(ctx.dir, token, 1));
}

async function testPromotionReconciliationBlocksResume(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "promotion-reconciliation"));
  const job = startAutoEditJob({
    ctx, token: "promotion-reconciliation", snapshots: 0,
    bootstrapPlanHash: fileSha256(ctx.planPath),
  });
  writeFileSync(
    path.join(ctx.dir, AUTO_EDIT_PROMOTION_RECONCILIATION_FILE),
    '{"status":"reconciliation-required"}\n',
  );
  const counts = { author: 0, planning: 0, assemble: 0, quality: 0 };
  await assert.rejects(
    runAutoEditPipeline(runtime(job, []), dependencies(counts)),
    /QC promotion has unresolved/,
  );
  assert.deepEqual(counts, {
    author: 0, planning: 0, assemble: 0, quality: 0,
  });
}

async function testRenderCheckpointOverlapsQuality(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "overlap"));
  const job = startAutoEditJob({
    ctx, token: "overlap", snapshots: 0, bootstrapPlanHash: fileSha256(ctx.planPath),
  });
  const counts = { author: 0, planning: 0, assemble: 0, quality: 0 };
  const deps = dependencies(counts);
  const order: string[] = [];
  deps.checkpoint = async (_ctx, spec) => {
    order.push(`checkpoint:${spec.stage}`);
    // A macrotask outlives the microtask-only quality stub, so a regression to
    // the serial await would land checkpoint:settled before quality.
    await new Promise((resolve) => setTimeout(resolve, 20));
    order.push("checkpoint:settled");
    return { status: "committed" as const };
  };
  deps.quality = async (_run, loopDeps) => {
    counts.quality += 1;
    order.push("quality");
    // The read-only phase overlaps the publish; the mutation barrier the
    // pipeline injects must hold promote/revise until the publish settles.
    await loopDeps?.renderCheckpointSettled?.();
    order.push("quality:mutation-barrier");
    return { status: "approved" as const, finalHash: "approved-in-stub" };
  };
  deps.approvedMirror = async () => { order.push("mirror"); };
  await runAutoEditPipeline(runtime(job, []), deps);
  assert.deepEqual(order,
    ["checkpoint:render", "quality", "checkpoint:settled", "quality:mutation-barrier", "mirror"],
    "QC must start while the courtesy publish is in flight, its mutations must wait for the"
      + " publish to settle, and the round must not resolve before it settles");
}

async function testCheckpointRejectionStaysFatalAfterQuality(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "checkpoint-reject"));
  const job = startAutoEditJob({
    ctx, token: "checkpoint-reject", snapshots: 0, bootstrapPlanHash: fileSha256(ctx.planPath),
  });
  const counts = { author: 0, planning: 0, assemble: 0, quality: 0 };
  const deps = dependencies(counts);
  deps.checkpoint = async () => {
    await new Promise((resolve) => setTimeout(resolve, 5));
    throw new Error("palmier checkpoint runner crashed");
  };
  await assert.rejects(
    runAutoEditPipeline(runtime(job, []), deps),
    /palmier checkpoint runner crashed/,
  );
  assert.equal(counts.quality, 1, "the in-flight QC round is awaited, never abandoned");
}

async function testQualityFailurePropagatesAfterCheckpointSettles(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "quality-reject"));
  const job = startAutoEditJob({
    ctx, token: "quality-reject", snapshots: 0, bootstrapPlanHash: fileSha256(ctx.planPath),
  });
  const counts = { author: 0, planning: 0, assemble: 0, quality: 0 };
  const deps = dependencies(counts);
  let checkpointSettled = false;
  deps.checkpoint = async () => {
    await new Promise((resolve) => setTimeout(resolve, 5));
    checkpointSettled = true;
    return { status: "committed" as const };
  };
  deps.quality = async () => {
    counts.quality += 1;
    throw new Error("candidate has non-plan-repairable defects");
  };
  await assert.rejects(
    runAutoEditPipeline(runtime(job, []), deps),
    /non-plan-repairable defects/,
  );
  assert.equal(checkpointSettled, true, "the courtesy publish is never left in flight");
}

async function testDoubleFailureCheckpointRejectionWins(root: string): Promise<void> {
  const ctx = fixture(path.join(root, "double-reject"));
  const job = startAutoEditJob({
    ctx, token: "double-reject", snapshots: 0, bootstrapPlanHash: fileSha256(ctx.planPath),
  });
  const counts = { author: 0, planning: 0, assemble: 0, quality: 0 };
  const deps = dependencies(counts);
  const unhandled: unknown[] = [];
  const trap = (reason: unknown): void => { unhandled.push(reason); };
  process.on("unhandledRejection", trap);
  let checkpointSettled = false;
  let qualitySettled = false;
  // QC fails FIRST (5ms) and the checkpoint fails later (20ms): the
  // checkpoint rejection must still win (pipeline.ts awaits checkpointFailure
  // before inspecting the QC round), and the QC error must be observed.
  deps.checkpoint = async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
    checkpointSettled = true;
    throw new Error("palmier checkpoint runner crashed");
  };
  deps.quality = async () => {
    counts.quality += 1;
    await new Promise((resolve) => setTimeout(resolve, 5));
    qualitySettled = true;
    throw new Error("candidate has non-plan-repairable defects");
  };
  try {
    const outcome = await runAutoEditPipeline(runtime(job, []), deps).then(
      () => null,
      (error: unknown) => {
        assert.equal(checkpointSettled, true,
          "the round must not resolve before the courtesy publish settles");
        assert.equal(qualitySettled, true,
          "the round must not resolve before the in-flight QC round settles");
        return error as Error;
      },
    );
    assert.ok(outcome, "a double failure must reject the pipeline");
    assert.match(outcome.message, /palmier checkpoint runner crashed/,
      "the checkpoint rejection wins over the QC rejection");
    // Give any leaked QC rejection a full macrotask turn to surface.
    await new Promise((resolve) => setTimeout(resolve, 30));
    assert.deepEqual(unhandled, [],
      "the losing QC rejection is observed, never an unhandledRejection");
  } finally {
    process.removeListener("unhandledRejection", trap);
  }
  assert.equal(counts.quality, 1);
}

async function main(): Promise<void> {
  const root = mkdtempSync(path.join(os.tmpdir(), "sniper-pipeline-v2-"));
  try {
    await testFreshCandidate(root);
    await testMissingPlanReauthors(root);
    await testBrokenCandidateFailsClosed(root);
    await testApprovedResumeSkipsCandidate(root);
    await testLegacyApprovalCannotBypassRevisionAuthority(root);
    await testRenderingCrashRetriesSameRound(root);
    await testPromotionReconciliationBlocksResume(root);
    await testRenderCheckpointOverlapsQuality(root);
    await testCheckpointRejectionStaysFatalAfterQuality(root);
    await testQualityFailurePropagatesAfterCheckpointSettles(root);
    await testDoubleFailureCheckpointRejectionWins(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
  console.log("auto-edit-pipeline-resume.test.ts: all assertions passed");
}

void main();
