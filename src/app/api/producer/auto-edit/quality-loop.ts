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
  approveCandidate,
  repairCandidate,
  requiredCandidate,
} from "./quality-loop-outcomes";
import {
  artifactRef,
  captureRenderedEvidence,
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
  /**
   * Settles the pipeline's overlapped render→Palmier courtesy publish. That
   * subprocess reads edit_plan.json and the candidate file, so it must be
   * fully settled before QC's first mutation of either (promote moves the
   * candidate; revise rewrites the plan and then opens its own Palmier
   * publish). Rejects with the checkpoint's real failure so a doomed run
   * never promotes or revises first. Default: no overlap, nothing to await.
   */
  renderCheckpointSettled: () => Promise<void>;
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
  renderCheckpointSettled: () => Promise.resolve(),
};
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
  // Everything above only READS the render checkpoint's inputs and may safely
  // overlap it. Both paths below mutate them — approval promotes (moves) the
  // candidate, repair rewrites edit_plan.json and publishes its own Palmier
  // checkpoint — so the overlapped publish must be settled first.
  await deps.renderCheckpointSettled();
  if (!aggregate.materialIssues.length && evidence && qualitySummary) {
    return approveCandidate(run, reviews, authority, evidence, qualitySummary, deps);
  }
  return repairCandidate(run, aggregate, deps);
}
