// Terminal branches of the QC round: promote an approved candidate or repair
// the plan and invalidate downstream checkpoints. Extracted verbatim from
// quality-loop.ts (structure-only split); the loop itself stays there.
import path from "path";
import type { AutoEditAuthoritySnapshot } from "@/lib/server/auto-edit-authority-snapshot";
import type { AutoEditJob } from "@/lib/server/auto-edit-job-store";
import type { HashedArtifactRef } from "@/lib/server/auto-edit-quality-artifacts";
import type {
  QualityLoopDependencies,
  QualityLoopResult,
  QualityLoopRuntime,
} from "./quality-loop";
import type { QualityLensReview } from "./quality-review-aggregate";
import type { ProducerReview } from "./review-contract";
import {
  artifactRef,
  collectPlanningReviewEvidence,
  type BoundRenderedEvidence,
} from "./review-evidence";
import { MAX_QC_RENDER_ROUNDS } from "./round-policy";
import { AutoEditError } from "./stream";

export function requiredCandidate(job: AutoEditJob): { path: string; round: number; dir: string } {
  if (!job.candidatePath || !job.qcRound) {
    throw new AutoEditError("quality review cannot start without a checkpointed candidate render");
  }
  return { path: job.candidatePath, round: job.qcRound, dir: path.dirname(job.candidatePath) };
}

export function approveCandidate(
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

export async function repairCandidate(
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
