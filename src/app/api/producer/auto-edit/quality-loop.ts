import path from "path";
import { snapshotPlan } from "../../_lib/plan-snapshots";
import { planContentHash } from "@/lib/server/auto-edit-authority";
import { autoEditAuthoritySnapshot, type AutoEditAuthoritySnapshot } from "@/lib/server/auto-edit-authority-snapshot";
import { fileSha256, type AutoEditJob, type CheckpointUpdate } from "@/lib/server/auto-edit-job-store";
import { promoteApprovedCandidate, type HashedArtifactRef, writeQualityJson } from "@/lib/server/auto-edit-quality-artifacts";
import {
  runProducerReview,
  runProducerRevision,
} from "./brain-review-runner";
import { runAuditBOutcome, type AuditBOutcome } from "./chain";
import {
  artifactRef,
  captureRenderedEvidence,
  collectPlanningReviewEvidence,
  qualitySummaryValue,
  type BoundRenderedEvidence,
} from "./review-evidence";
import {
  aggregateQualityReview,
  type QualityLensReview,
} from "./quality-review-aggregate";
import {
  MAX_QC_RENDER_ROUNDS,
  VISUAL_REVIEW_LENSES,
  type VisualReviewLens,
} from "./round-policy";
import type { ProducerReview } from "./review-contract";
import { AutoEditError, type Send } from "./stream";
import {
  persistAutoEditAuditOutcome,
  persistCriticObservations,
} from "@/lib/server/auto-edit-observations";
import { publishPalmierWorkingCheckpoint } from "./palmier-checkpoints";
export interface QualityLoopIo {
  send: Send;
  advance: (update: CheckpointUpdate) => AutoEditJob;
  invalidate: (update: CheckpointUpdate) => AutoEditJob;
}
export interface QualityLoopRuntime {
  job: AutoEditJob;
  io: QualityLoopIo;
}
export interface QualityLoopDependencies {
  audit: typeof runAuditBOutcome;
  review: typeof runProducerReview;
  revise: typeof runProducerRevision;
  hash: typeof fileSha256;
  contentHash: typeof planContentHash;
  snapshot: typeof snapshotPlan;
  promote: typeof promoteApprovedCandidate;
  writeJson: typeof writeQualityJson;
  authority: typeof autoEditAuthoritySnapshot;
  checkpoint: typeof publishPalmierWorkingCheckpoint;
}
export type QualityLoopResult =
  | { status: "approved"; finalHash: string }
  | { status: "repaired"; issueCodes: string[] };
const DEFAULT_DEPS: QualityLoopDependencies = {
  audit: runAuditBOutcome,
  review: runProducerReview,
  revise: runProducerRevision,
  hash: fileSha256,
  contentHash: planContentHash,
  snapshot: snapshotPlan,
  promote: promoteApprovedCandidate,
  writeJson: writeQualityJson,
  authority: autoEditAuthoritySnapshot,
  checkpoint: publishPalmierWorkingCheckpoint,
};
function requiredCandidate(job: AutoEditJob): { path: string; round: number; dir: string } {
  if (!job.candidatePath || !job.qcRound) {
    throw new AutoEditError("quality review cannot start without a checkpointed candidate render");
  }
  return { path: job.candidatePath, round: job.qcRound, dir: path.dirname(job.candidatePath) };
}

async function runLensReview(
  run: QualityLoopRuntime,
  lens: VisualReviewLens,
  evidence: BoundRenderedEvidence,
  authority: AutoEditAuthoritySnapshot,
  deps: QualityLoopDependencies,
): Promise<QualityLensReview> {
  const round = run.job.qcRound!;
  run.io.send({
    event: "rendered_review_started", lens, qcRound: round,
    qcRoundsMax: MAX_QC_RENDER_ROUNDS,
  });
  const result = await deps.review({
    stage: "rendered", ctx: run.job.ctx, round, lens, evidence: evidence.prompt,
  });
  if (deps.authority(run.job.ctx).digest !== authority.digest) {
    throw new AutoEditError("input or pipeline authority changed while a rendered critic was running");
  }
  const reviewPath = deps.writeJson(path.join(path.dirname(run.job.candidatePath!), `${lens}-review.json`), {
    schemaVersion: 1,
    stage: "rendered",
    round,
    lens,
    inputAuthority: authority,
    evidence: evidence.authority,
    provider: result.provider,
    ms: result.ms,
    review: result.review,
  });
  persistCriticObservations({
    ctx: run.job.ctx, artifactPath: reviewPath, review: result.review,
    namespace: `rendered-a${run.job.attempts}-r${round}-${lens}`,
  });
  run.io.send({
    event: "rendered_review_completed", lens, qcRound: round,
    qcRoundsMax: MAX_QC_RENDER_ROUNDS, verdict: result.review.verdict,
    materialIssueCount: result.review.materialIssues.length, provider: result.provider,
    ms: result.ms,
  });
  return { lens, result, path: reviewPath };
}
async function visualReviews(
  run: QualityLoopRuntime,
  evidence: BoundRenderedEvidence | null,
  authority: AutoEditAuthoritySnapshot,
  deps: QualityLoopDependencies,
): Promise<QualityLensReview[]> {
  if (!evidence) return [];
  return Promise.all(VISUAL_REVIEW_LENSES.map((lens) =>
    runLensReview(run, lens, evidence, authority, deps)));
}
function persistSummary(
  run: QualityLoopRuntime,
  audit: AuditBOutcome,
  review: ProducerReview,
  reviews: QualityLensReview[],
  authority: AutoEditAuthoritySnapshot,
  evidence: BoundRenderedEvidence,
  deps: QualityLoopDependencies,
): HashedArtifactRef {
  const refs = reviews.map((item) => artifactRef(item.path));
  const destination = path.join(path.dirname(run.job.candidatePath!), "quality-summary.json");
  deps.writeJson(destination, qualitySummaryValue(
    run.job, authority, evidence.authority, audit, review, refs,
  ));
  return artifactRef(destination);
}
function approveCandidate(
  run: QualityLoopRuntime,
  reviews: QualityLensReview[],
  authority: AutoEditAuthoritySnapshot,
  evidence: BoundRenderedEvidence,
  qualitySummary: HashedArtifactRef,
  deps: QualityLoopDependencies,
): QualityLoopResult {
  const candidate = requiredCandidate(run.job);
  const finalHash = deps.hash(candidate.path);
  if (!finalHash || finalHash !== run.job.candidateHash) {
    throw new AutoEditError("candidate changed after render; refusing QC approval and promotion");
  }
  const currentAuthority = deps.authority(run.job.ctx);
  const planHash = currentAuthority.planHash;
  const manifestHash = currentAuthority.manifestHash;
  if (!planHash || !manifestHash || planHash !== run.job.renderedPlanHash
      || manifestHash !== run.job.renderedManifestHash
      || currentAuthority.digest !== authority.digest
      || authority.digest !== run.job.renderedAuthorityDigest) {
    throw new AutoEditError("input or pipeline authority changed during candidate QC");
  }
  if (evidence.authority.candidateHash !== finalHash
      || evidence.authority.assembledProofHash !== deps.hash(`${candidate.path}.assembled.json`)) {
    throw new AutoEditError("candidate or its assembly proof changed during visual QC");
  }
  const planningReviews = collectPlanningReviewEvidence(run.job, authority);
  run.io.send({
    event: "candidate_checks_passed",
    qcRound: candidate.round,
    qcRoundsMax: MAX_QC_RENDER_ROUNDS,
  });
  deps.promote(candidate.path, run.job.ctx.dir, {
    schemaVersion: 2,
    qualityPolicyVersion: 1,
    authorityDigest: authority.digest,
    planHash,
    manifestHash,
    finalHash,
    candidateHash: finalHash,
    assembledProofHash: evidence.authority.assembledProofHash,
    qcRound: candidate.round, approvedAt: new Date().toISOString(),
    planningRoundsRequired: run.job.planningRoundsRequired!,
    planningReviews,
    renderedReviews: reviews.map((item) => ({ lens: item.lens, ...artifactRef(item.path) })),
    audit: evidence.authority,
    qualitySummary,
  });
  run.job = run.io.advance({
    checkpoint: "quality_check", phase: "quality_check",
    message: `Candidate ${candidate.round} passed all deterministic and visual QC.`,
    finalHash, unresolvedFindingIds: [],
  });
  run.io.send({
    event: "candidate_approved",
    qcRound: candidate.round,
    qcRoundsMax: MAX_QC_RENDER_ROUNDS,
  });
  run.io.send({ event: "outputs", outDir: run.job.ctx.dir, approved: true });
  run.io.send({ event: "candidate_promoted", qcRound: candidate.round, qcRoundsMax: MAX_QC_RENDER_ROUNDS });
  return { status: "approved", finalHash };
}
async function repairCandidate(
  run: QualityLoopRuntime,
  review: ProducerReview,
  deps: QualityLoopDependencies,
): Promise<QualityLoopResult> {
  const round = run.job.qcRound!;
  const issueCodes = review.materialIssues.map((issue) => issue.code);
  if (review.verdict === "block") {
    run.io.send({
      event: "quality_blocked", stage: "quality", round,
      unresolvedFindingIds: issueCodes, materialIssueCount: issueCodes.length,
    });
    throw new AutoEditError(`candidate has non-plan-repairable defects: ${issueCodes.join(", ")}`);
  }
  if (round >= MAX_QC_RENDER_ROUNDS) {
    run.io.send({
      event: "max_rounds_exhausted", stage: "quality", round,
      unresolvedFindingIds: issueCodes, materialIssueCount: issueCodes.length,
    });
    throw new AutoEditError(`candidate cannot be approved: ${issueCodes.join(", ")}`);
  }
  run.job = run.io.advance({
    checkpoint: "repairing", phase: "repairing",
    message: `Repairing ${issueCodes.length} material finding(s) from candidate ${round}.`,
    unresolvedFindingIds: issueCodes,
  });
  run.io.send({
    event: "repair_started", qcRound: round, qcRoundsMax: MAX_QC_RENDER_ROUNDS,
    materialIssueCount: issueCodes.length,
  });
  const inputAuthority = deps.authority(run.job.ctx);
  const before = deps.contentHash(run.job.ctx.planPath);
  deps.snapshot(run.job.ctx.planPath);
  const revision = await deps.revise(run.job.ctx, review, round);
  deps.writeJson(path.join(path.dirname(run.job.candidatePath!), "repair-receipt.json"), {
    schemaVersion: 1,
    stage: "repair",
    inputAuthority,
    revision,
  });
  const after = deps.contentHash(run.job.ctx.planPath);
  if (revision.receipt.deferredIssueCodes.length) {
    throw new AutoEditError(`QC repair deferred system issues: ${revision.receipt.deferredIssueCodes.join(", ")}`);
  }
  if (!before || !after || !revision.receipt.changedPlan || before === after) {
    throw new AutoEditError("QC repair did not produce a different edit plan; refusing a duplicate render");
  }
  await deps.checkpoint(run.job.ctx, { stage: "revision", round }, run.io.send);
  run.io.send({ event: "repair_completed", qcRound: round, qcRoundsMax: MAX_QC_RENDER_ROUNDS });
  run.job = run.io.invalidate({
    checkpoint: "plan_authored", phase: "planning_review",
    message: "QC repair changed the plan; rerunning every planning review and gate before rendering again.",
    planHash: after,
    authorityDigest: deps.authority(run.job.ctx).digest,
    planningRound: 0, planningCycles: 0, qcRound: round, unresolvedFindingIds: [],
  });
  return { status: "repaired", issueCodes };
}

export async function runQualityReviewRound(
  run: QualityLoopRuntime,
  dependencies: Partial<QualityLoopDependencies> = {},
): Promise<QualityLoopResult> {
  const deps = { ...DEFAULT_DEPS, ...dependencies };
  const candidate = requiredCandidate(run.job);
  run.job = run.io.advance({
    checkpoint: "quality_check", phase: "quality_check",
    message: `Running deterministic and visual QC for candidate ${candidate.round}/${MAX_QC_RENDER_ROUNDS}.`,
    qcRound: candidate.round, qcRoundsMax: MAX_QC_RENDER_ROUNDS,
  });
  const authority = deps.authority(run.job.ctx);
  if (authority.digest !== run.job.renderedAuthorityDigest) {
    throw new AutoEditError("candidate QC authority does not match the reviewed render authority");
  }
  const audit = await deps.audit(candidate.dir);
  persistAutoEditAuditOutcome({
    ctx: run.job.ctx, candidateDir: candidate.dir, round: candidate.round,
    attempt: run.job.attempts, audit,
  });
  run.io.send(audit.event);
  if (deps.authority(run.job.ctx).digest !== authority.digest) {
    throw new AutoEditError("input or pipeline authority changed while deterministic QC was running");
  }
  const evidence = captureRenderedEvidence(candidate.path, candidate.dir, audit);
  const reviews = await visualReviews(run, evidence, authority, deps);
  const aggregate = aggregateQualityReview(audit, evidence?.prompt ?? null, reviews);
  const qualitySummary = evidence
    ? persistSummary(run, audit, aggregate, reviews, authority, evidence, deps)
    : null;
  if (!aggregate.materialIssues.length && evidence && qualitySummary) {
    return approveCandidate(run, reviews, authority, evidence, qualitySummary, deps);
  }
  return repairCandidate(run, aggregate, deps);
}
