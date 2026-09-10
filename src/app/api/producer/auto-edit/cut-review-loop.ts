import path from "node:path";
import { snapshotPlan } from "../../_lib/plan-snapshots";
import {
  autoEditAuthoritySnapshot,
  sameAutoEditAuthority,
} from "@/lib/server/auto-edit-authority-snapshot";
import { fileSha256, type AutoEditJob, type CheckpointUpdate } from
  "@/lib/server/auto-edit-job-store";
import { writeQualityJson } from "@/lib/server/auto-edit-quality-artifacts";
import {
  runProducerReview,
  runProducerRevision,
  type ProducerRevisionResult,
} from "./brain-review-runner";
import {
  persistCutReviewApproval,
  REQUIRED_CLEAN_CUT_REVIEWS,
  type CleanCutReviewArtifact,
  type CutReviewApprovalReceipt,
} from "./cut-review-approval";
import {
  validatePrevisualCut,
  validateSavedPlanCut,
} from "./cut-approval";
import {
  cutRoundDir,
  MAX_CUT_REVIEW_ROUNDS,
  runCutReviewBatch,
  type CutRoundResult,
} from "./cut-review-batch";
import { mergeProducerReviewBatch } from "./review-batch";
import { RevisionNoChangeError } from "./revision-staging";
import { AutoEditError, type Send } from "./stream";
import { assertExistingCutContext, hasGuidedBootstrap } from "@/lib/server/guided-project-bootstrap-contract";
import { assertBootstrapCurrent } from "@/lib/server/guided-project-bootstrap-guard";

export const cutReviewBootstrapGuards = { current: assertBootstrapCurrent };

export { MAX_CUT_REVIEW_ROUNDS } from "./cut-review-batch";

export interface CutReviewLoopRuntime {
  job: AutoEditJob;
  io: {
    send: Send;
    advance: (update: CheckpointUpdate) => AutoEditJob;
  };
}

export interface CutReviewLoopDependencies {
  gate: typeof validatePrevisualCut;
  review: typeof runProducerReview;
  revise: typeof runProducerRevision;
  authority: typeof autoEditAuthoritySnapshot;
  writeJson: typeof writeQualityJson;
  hash: typeof fileSha256;
  snapshot: typeof snapshotPlan;
  approve: typeof persistCutReviewApproval;
}

const DEFAULT_DEPS: CutReviewLoopDependencies = {
  gate: validatePrevisualCut,
  review: runProducerReview,
  revise: runProducerRevision,
  authority: autoEditAuthoritySnapshot,
  writeJson: writeQualityJson,
  hash: fileSha256,
  snapshot: snapshotPlan,
  approve: persistCutReviewApproval,
};

interface CutRevisionConflict {
  kind: "conflict";
  issueCodes: string[];
  reason: "writer_deferred" | "writer_no_render_change";
}

type CutRevisionOutcome = { kind: "changed" } | CutRevisionConflict;

function requiredHash(value: string | undefined, label: string): string {
  if (!value) throw new AutoEditError(`missing ${label}`);
  return value;
}

function conflictKey(result: CutRoundResult): string {
  const codes = result.review.materialIssues.map((issue) => issue.code).sort();
  return `${cutIdentity(result)}:${codes.join(",")}`;
}

function persistConflict(
  run: CutReviewLoopRuntime,
  round: number,
  conflict: CutRevisionConflict,
  deps: CutReviewLoopDependencies,
): void {
  const message = "Cut critic and revision evidence conflict; starting one fresh independent re-review of the unchanged deterministic cut.";
  deps.writeJson(path.join(cutRoundDir(run, round), "cut-revision-conflict.json"), {
    schemaVersion: 1, stage: "cut", round, ...conflict, message,
  });
  run.io.send({ event: "cut_revision_conflict", round, ...conflict, message });
}

async function reviseCut(
  run: CutReviewLoopRuntime,
  result: CutRoundResult,
  round: number,
  deps: CutReviewLoopDependencies,
): Promise<CutRevisionOutcome> {
  if (result.review.verdict === "block") {
    throw new AutoEditError(`cut critic blocked visual planning: ${result.review.materialIssues.map((x) => x.code).join(", ")}`);
  }
  const before = requiredHash(deps.hash(run.job.ctx.planPath), "pre-revision plan hash");
  deps.snapshot(run.job.ctx.planPath);
  run.io.send({ event: "cut_revision_started", round });
  let revision: ProducerRevisionResult;
  try {
    revision = await deps.revise(run.job.ctx, result.review, round);
  } catch (error) {
    if (!(error instanceof RevisionNoChangeError)) throw error;
    return {
      kind: "conflict",
      issueCodes: result.review.materialIssues.map((issue) => issue.code),
      reason: "writer_no_render_change",
    };
  }
  deps.writeJson(path.join(cutRoundDir(run, round), "cut-revision-receipt.json"), revision);
  if (revision.receipt.deferredIssueCodes.length) {
    return {
      kind: "conflict", issueCodes: revision.receipt.deferredIssueCodes,
      reason: "writer_deferred",
    };
  }
  const after = requiredHash(deps.hash(run.job.ctx.planPath), "revised plan hash");
  if (!revision.receipt.changedPlan || before === after) {
    throw new AutoEditError("cut revision addressed issues without changing edit_plan.json");
  }
  run.io.send({ event: "cut_revision_completed", round, provider: revision.provider });
  return { kind: "changed" };
}

function cutIdentity(result: CutRoundResult): string {
  return [
    result.gate.planHash, result.gate.cutTrackDigest,
    result.gate.cutDecisionsDigest, result.gate.transcriptDigest,
  ].join(":");
}

function mergeCutResults(results: CutRoundResult[]): CutRoundResult {
  const first = results[0];
  if (!first) throw new AutoEditError("cut critic batch returned no reviews");
  if (results.some((result) => cutIdentity(result) !== cutIdentity(first)
      || result.authority.digest !== first.authority.digest)) {
    throw new AutoEditError("cut critic batch did not share one immutable authority");
  }
  return {
    ...first,
    review: mergeProducerReviewBatch(results.map((result) => result.review), "cut"),
  };
}

function cutReviewDependencies(
  run: CutReviewLoopRuntime,
  overrides: Partial<CutReviewLoopDependencies>,
): CutReviewLoopDependencies {
  const deps = { ...DEFAULT_DEPS, ...overrides };
  if (run.job.reviewSavedPlan && !overrides.gate) deps.gate = validateSavedPlanCut;
  return deps;
}

function approveCleanCut(
  run: CutReviewLoopRuntime,
  result: CutRoundResult,
  cleanReviews: CleanCutReviewArtifact[],
  deps: CutReviewLoopDependencies,
): CutReviewApprovalReceipt {
  if (!sameAutoEditAuthority(result.authority, deps.authority(run.job.ctx))) {
    throw new AutoEditError("cut authority changed before review approval was committed");
  }
  return deps.approve(
    run.job.ctx, result.gate, result.authority.digest,
    cleanReviews.slice(-REQUIRED_CLEAN_CUT_REVIEWS),
  );
}

async function resolveMaterialCutIssues(run: CutReviewLoopRuntime, result: CutRoundResult,
  state: { round: number; reReviewedConflicts: Set<string> }, deps: CutReviewLoopDependencies): Promise<void> {
  const { round, reReviewedConflicts } = state;
  if (round >= MAX_CUT_REVIEW_ROUNDS) {
    throw new AutoEditError(`cut review exhausted ${round} rounds: ${result.review.materialIssues.map((x) => x.code).join(", ")}`);
  }
  if (run.job.reviewSavedPlan || run.job.ctx.existingCutCandidate) {
    const codes = result.review.materialIssues.map((issue) => issue.code).join(", ");
    throw new AutoEditError(`saved-plan cut review found material issues; complete plan was not modified: ${codes}`);
  }
  const key = conflictKey(result);
  if (reReviewedConflicts.has(key)) {
    const codes = result.review.materialIssues.map((issue) => issue.code).join(", ");
    throw new AutoEditError(`cut critic/revision conflict repeated for unchanged deterministic cut: ${codes}`);
  }
  const revision = await reviseCut(run, result, round, deps);
  if (run.job.ctx.authoredCut) cutReviewBootstrapGuards.current(run.job);
  if (revision.kind === "conflict") {
    reReviewedConflicts.add(key);
    persistConflict(run, round, revision, deps);
  }
}

export async function runCutReviewLoop(run: CutReviewLoopRuntime,
  dependencies: Partial<CutReviewLoopDependencies> = {}): Promise<CutReviewApprovalReceipt> {
  assertExistingCutContext(run.job.ctx);
  if (hasGuidedBootstrap(run.job.ctx) && run.job.reviewSavedPlan) throw new AutoEditError("Guided cut bootstrap cannot select the saved-plan gate");
  const deps = cutReviewDependencies(run, dependencies);
  let cleanIdentity: string | undefined;
  let cleanReviews: CleanCutReviewArtifact[] = [];
  const reReviewedConflicts = new Set<string>();
  let round = 0;
  while (round < MAX_CUT_REVIEW_ROUNDS) {
    if (run.job.ctx.authoredCut) cutReviewBootstrapGuards.current(run.job);
    const firstRound = round + 1;
    const remainingClean = REQUIRED_CLEAN_CUT_REVIEWS - cleanReviews.length;
    const batchSize = Math.min(remainingClean, MAX_CUT_REVIEW_ROUNDS - round);
    run.job = run.io.advance({
      checkpoint: "authoring", phase: "authoring",
      message: `Transcript cut review ${firstRound}/${MAX_CUT_REVIEW_ROUNDS}; launching ${batchSize} independent critic(s) against the same deterministic cut.`,
    });
    const results = await runCutReviewBatch(run, firstRound, batchSize, deps);
    if (run.job.ctx.authoredCut) cutReviewBootstrapGuards.current(run.job);
    round += results.length;
    const result = mergeCutResults(results);
    if (result.review.materialIssues.length) {
      cleanIdentity = undefined;
      cleanReviews = [];
      await resolveMaterialCutIssues(run, result, { round, reReviewedConflicts }, deps);
      continue;
    }
    const identity = cutIdentity(result);
    const artifacts = results.map((item) => item.artifact);
    cleanReviews = cleanIdentity === identity ? [...cleanReviews, ...artifacts] : artifacts;
    cleanIdentity = identity;
    run.job = run.io.advance({
      checkpoint: "authoring", phase: "authoring",
      message: `Current transcript cut has ${cleanReviews.length}/${REQUIRED_CLEAN_CUT_REVIEWS} clean independent reviews.`,
    });
    if (cleanReviews.length < REQUIRED_CLEAN_CUT_REVIEWS) continue;
    return approveCleanCut(run, result, cleanReviews, deps);
  }
  throw new AutoEditError("cut review ended without an approved transcript spine");
}
