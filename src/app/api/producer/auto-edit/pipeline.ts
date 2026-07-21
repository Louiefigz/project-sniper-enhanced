import { existsSync, statSync, type Stats } from "fs";
import path from "path";
import {
  bindAuthorityProof,
  planContentHash,
  requireFreshAuthority,
  verifiedAuthorityHash,
} from "@/lib/server/auto-edit-authority";
import { autoEditAuthoritySnapshot } from "@/lib/server/auto-edit-authority-snapshot";
import {
  checkpointReached,
  fileSha256,
  type AutoEditJob,
  type CheckpointUpdate,
} from "@/lib/server/auto-edit-job-store";
import {
  candidateFinalPath,
  copyAuditInputs,
  prepareQcRound,
  readApproval,
  seedQcRoundFromPriorCandidate,
} from "@/lib/server/auto-edit-quality-artifacts";
import {
  runAuthoring,
  type AuthoringSessionMode,
  type AuthoringStage,
} from "./authoring";
import { runAssemble, runBaseGuard } from "./chain";
import { runPlanningReviewLoop } from "./planning-loop";
import { runQualityReviewRound, type QualityLoopResult } from "./quality-loop";
import { MAX_QC_RENDER_ROUNDS } from "./round-policy";
import { AutoEditError, type Send } from "./stream";
import {
  currentPlanRefitReceipt,
  planRefitEvent,
} from "../../_lib/plan-refit-transaction";
import { restoreAutoEditDoctrine } from "@/lib/server/auto-edit-doctrine";
import { restoreAutoEditPipeline } from "@/lib/server/auto-edit-pipeline-authority";
import { runAuthorStage } from "./authoring-stage";
import { markAuthoringSessionEstablished } from "./authoring-session-state";
import { publishApprovedPalmierMirror, publishPalmierWorkingCheckpoint } from "./palmier-checkpoints";
import { brainModel, brainProvider, brainProviderLabel } from "../../_lib/ai-provider";
import { runPalmierPrimaryAutoEdit } from "./palmier-primary";
import { approvePrevisualCut, validatePrevisualCut, verifyApprovedCut } from "./cut-approval";
import { bindTemplateUsageForJob } from "./template-usage-stage";
import { runCutReviewLoop } from "./cut-review-loop";
import { verifyCutReviewApproval } from "./cut-review-approval";
import type { PipelineRuntime } from "./pipeline-types";
export type { PipelineIo, PipelineRuntime } from "./pipeline-types";

export interface PipelineDependencies {
  exists: typeof existsSync;
  hashFile: typeof fileSha256;
  author: (
    ctx: AutoEditJob["ctx"],
    send: Send,
    stage: AuthoringStage,
    sessionMode: AuthoringSessionMode,
  ) => ReturnType<typeof runAuthoring>;
  validateCut: typeof validatePrevisualCut;
  reviewCut: typeof runCutReviewLoop;
  verifyReviewCut: typeof verifyCutReviewApproval;
  approveCut: typeof approvePrevisualCut;
  verifyCut: typeof verifyApprovedCut;
  bindSession: typeof markAuthoringSessionEstablished;
  planning: typeof runPlanningReviewLoop;
  baseGuard: typeof runBaseGuard;
  assemble: typeof runAssemble;
  quality: typeof runQualityReviewRound;
  authority: typeof autoEditAuthoritySnapshot;
  checkpoint: typeof publishPalmierWorkingCheckpoint;
  approvedMirror: typeof publishApprovedPalmierMirror;
  palmierPrimary: typeof runPalmierPrimaryAutoEdit;
}

const DEFAULT_DEPS: PipelineDependencies = {
  exists: existsSync,
  hashFile: fileSha256,
  author: (ctx, send, stage, sessionMode) => runAuthoring(
    ctx, send, {}, { stage, sessionMode },
  ),
  validateCut: validatePrevisualCut,
  reviewCut: runCutReviewLoop,
  verifyReviewCut: verifyCutReviewApproval,
  approveCut: approvePrevisualCut,
  verifyCut: verifyApprovedCut,
  bindSession: markAuthoringSessionEstablished,
  planning: runPlanningReviewLoop,
  baseGuard: runBaseGuard,
  assemble: runAssemble,
  quality: runQualityReviewRound,
  authority: autoEditAuthoritySnapshot,
  checkpoint: publishPalmierWorkingCheckpoint,
  approvedMirror: publishApprovedPalmierMirror,
  palmierPrimary: runPalmierPrimaryAutoEdit,
};

function advance(run: PipelineRuntime, update: CheckpointUpdate): void {
  run.job = run.io.advance(update);
}

function resumeEvent(run: PipelineRuntime, stage: string, message: string): void {
  run.io.send({ event: "resume", stage, checkpoint: run.job.checkpoint, message });
}

function validationReusable(run: PipelineRuntime, deps: PipelineDependencies): boolean {
  if (!checkpointReached(run.job.checkpoint, "validated")) return false;
  const authority = deps.authority(run.job.ctx);
  return authority.planHash === run.job.reviewedPlanHash
    && authority.digest === run.job.reviewedAuthorityDigest;
}

function validationStage(run: PipelineRuntime, deps: PipelineDependencies): void {
  if (validationReusable(run, deps)) {
    resumeEvent(run, "validating", "Reviewed plan authority is unchanged; render may continue.");
    return;
  }
  const { ctx } = run.job;
  const authority = deps.authority(ctx);
  const planHash = authority.planHash;
  const manifestHash = authority.manifestHash;
  if (!planHash || planHash !== run.job.reviewedPlanHash || !manifestHash
      || authority.digest !== run.job.reviewedAuthorityDigest) {
    throw new AutoEditError("render authority does not match the plan that passed bounded review");
  }
  advance(run, {
    checkpoint: "validating", phase: "validating",
    message: "Confirming reviewed plan, source manifest, and reference authority.",
  });
  advance(run, {
    checkpoint: "validated", phase: "rendering",
    message: "Reviewed plan authority is locked; rendering an isolated candidate.",
    planHash, manifestHash, authorityDigest: authority.digest,
    referenceProfileHash: ctx.referenceStudy ? deps.hashFile(ctx.referenceStudy.profilePath) : undefined,
  });
}

function candidateReusable(run: PipelineRuntime, deps: PipelineDependencies): boolean {
  const { ctx } = run.job;
  if (!checkpointReached(run.job.checkpoint, "rendered") || !run.job.candidatePath) return false;
  const candidate = run.job.candidatePath;
  const authority = deps.authority(ctx);
  return deps.exists(candidate)
    && authority.planHash === run.job.renderedPlanHash
    && authority.manifestHash === run.job.renderedManifestHash
    && authority.digest === run.job.renderedAuthorityDigest
    && verifiedAuthorityHash(candidate, planContentHash(ctx.planPath), deps, authority.digest)
      === run.job.candidateHash;
}

function approvedOutputReusable(run: PipelineRuntime, deps: PipelineDependencies): boolean {
  const { ctx } = run.job;
  const approval = readApproval(ctx.dir);
  const finalPath = path.join(ctx.dir, "final.mp4");
  if (!approval || !deps.exists(finalPath)) return false;
  const authority = deps.authority(ctx);
  return approval.planHash === authority.planHash
    && approval.manifestHash === authority.manifestHash
    && approval.authorityDigest === authority.digest
    && approval.finalHash === deps.hashFile(finalPath)
    && verifiedAuthorityHash(finalPath, planContentHash(ctx.planPath), deps, authority.digest)
      === approval.finalHash;
}

function candidateRound(job: AutoEditJob): number {
  if ((job.checkpoint === "rendering" || checkpointReached(job.checkpoint, "rendered"))
      && job.qcRound) return job.qcRound;
  return (job.qcRound ?? 0) + 1;
}

function previousProof(candidate: string): Pick<Stats, "ino" | "mtimeMs"> | null {
  const proof = `${candidate}.assembled.json`;
  return existsSync(proof) ? statSync(proof) : null;
}

async function renderCandidate(
  run: PipelineRuntime,
  deps: PipelineDependencies,
  candidate: string,
  round: number,
): Promise<void> {
  const { ctx } = run.job;
  const capturedAuthority = deps.authority(ctx);
  const capturedPlanHash = capturedAuthority.planHash ?? undefined;
  const capturedManifestHash = capturedAuthority.manifestHash ?? undefined;
  const proof = previousProof(candidate);
  await deps.baseGuard(ctx.dir, run.io.sendRaw);
  const result = await deps.assemble(ctx.dir, ctx.manifestPath, run.io.sendRaw, candidate);
  if (result.code !== 0) {
    throw new AutoEditError(`assemble exited ${result.code}. ${result.errTail.slice(-400)}`);
  }
  if (deps.authority(ctx).digest !== capturedAuthority.digest) {
    throw new AutoEditError("render input, intent, reference, renderer, or QC authority changed while assemble was running");
  }
  copyAuditInputs(ctx.dir, path.dirname(candidate));
  let candidateHash: string;
  try {
    candidateHash = requireFreshAuthority(candidate, planContentHash(ctx.planPath), proof, deps);
    bindAuthorityProof(candidate, capturedAuthority, deps);
  } catch (error) {
    throw new AutoEditError((error as Error).message);
  }
  advance(run, {
    checkpoint: "rendered", phase: "quality_check",
    message: `Candidate ${round} rendered; deterministic and visual QC remain.`,
    renderedPlanHash: capturedPlanHash, renderedManifestHash: capturedManifestHash,
    authorityDigest: capturedAuthority.digest,
    renderedAuthorityDigest: capturedAuthority.digest,
    qcRound: round, qcRoundsMax: MAX_QC_RENDER_ROUNDS,
    candidatePath: candidate, candidateHash,
  });
  run.io.send({ event: "candidate_ready", qcRound: round, qcRoundsMax: MAX_QC_RENDER_ROUNDS });
}

/**
 * The approved mirror still fails loudly (palmier_checkpoint_failed), but by
 * the time it runs the deliverable final.mp4 already exists and the outputs
 * event has fired — so a mirror failure fails the PUSH step, never the job.
 */
async function publishApprovedMirror(
  run: PipelineRuntime,
  deps: PipelineDependencies,
): Promise<void> {
  try {
    await deps.approvedMirror(run.job.ctx, run.io.send);
  } catch (error) {
    run.io.send({
      event: "palmier_mirror_failed", stage: "qc-approved", status: "failed",
      message: (error as Error).message,
    });
  }
}

/**
 * The render→Palmier courtesy checkpoint overlaps only QC's READ-ONLY phase
 * (Audit B + the visual critics). The checkpoint subprocess reads
 * edit_plan.json and the candidate file, and QC's approval path MOVES that
 * candidate (promote) while its repair path REWRITES the plan (revise) and
 * opens its own Palmier publish — so the quality loop's
 * renderCheckpointSettled barrier settles this publish before its first
 * mutation. Failure semantics match the old serial await: courtesy outcomes
 * (committed/warned/deferred) stay non-fatal, a real checkpoint rejection
 * still fails the run and wins over a QC error, and the round never resolves
 * while the publish is still in flight.
 */
async function qualityRoundWithRenderCheckpoint(
  run: PipelineRuntime,
  deps: PipelineDependencies,
): Promise<QualityLoopResult> {
  const renderCheckpoint = {
    stage: "render" as const, round: run.job.qcRound ?? 0,
    ...(run.job.candidatePath ? { mediaPath: run.job.candidatePath } : {}),
  };
  const checkpointFailure = deps.checkpoint(run.job.ctx, renderCheckpoint, run.io.send)
    .then(() => null, (error: unknown) => ({ error }));
  const renderCheckpointSettled = async (): Promise<void> => {
    const failure = await checkpointFailure;
    if (failure) throw failure.error;
  };
  const round = await deps.quality(run, { renderCheckpointSettled }).then(
    (result) => ({ result }),
    (error: unknown) => ({ error }),
  );
  const failure = await checkpointFailure;
  if (failure) throw failure.error;
  if (!("result" in round)) throw round.error;
  return round.result;
}

async function renderStage(run: PipelineRuntime, deps: PipelineDependencies): Promise<boolean> {
  const { ctx } = run.job;
  if (approvedOutputReusable(run, deps)) {
    const approval = readApproval(ctx.dir)!;
    advance(run, {
      checkpoint: "quality_check", phase: "quality_check",
      message: "Recovered the already-approved final video.", finalHash: approval.finalHash,
    });
    run.io.send({ event: "outputs", outDir: ctx.dir, approved: true, resumed: true });
    return true;
  }
  if (candidateReusable(run, deps)) {
    resumeEvent(run, "rendering", "The isolated candidate is intact; continuing with QC.");
    return false;
  }
  const round = candidateRound(run.job);
  if (round > MAX_QC_RENDER_ROUNDS) {
    run.io.send({ event: "max_rounds_exhausted", stage: "quality", round: round - 1 });
    throw new AutoEditError(`quality review exhausted ${MAX_QC_RENDER_ROUNDS} candidate renders`);
  }
  const artifactToken = run.job.artifactToken ?? run.job.token;
  const candidate = candidateFinalPath(ctx.dir, artifactToken, round);
  prepareQcRound(ctx.dir, artifactToken, round);
  seedQcRoundFromPriorCandidate(ctx.dir, artifactToken, round);
  advance(run, {
    checkpoint: "rendering", phase: "rendering",
    message: `Rendering isolated candidate ${round}/${MAX_QC_RENDER_ROUNDS}.`,
    qcRound: round, qcRoundsMax: MAX_QC_RENDER_ROUNDS,
  });
  run.io.send({ event: "phase", phase: "assemble", qcRound: round });
  await renderCandidate(run, deps, candidate, round);
  return false;
}

export async function runAutoEditPipeline(
  run: PipelineRuntime,
  dependencies: Partial<PipelineDependencies> = {},
): Promise<void> {
  const deps = { ...DEFAULT_DEPS, ...dependencies };
  if (run.job.ctx.doctrine) restoreAutoEditDoctrine(run.job.ctx.doctrine);
  if (run.job.ctx.pipeline) restoreAutoEditPipeline(run.job.ctx.pipeline);
  const provider = brainProvider();
  run.io.send({
    event: "start", phase: run.job.phase, scope: run.job.ctx.scope,
    manifestPath: run.job.ctx.manifestPath, planSnapshots: run.job.snapshots,
    resumeFrom: run.job.checkpoint, provider,
    model: brainModel(provider), brain: brainProviderLabel(provider), workbench: "Palmier",
  });
  const refit = currentPlanRefitReceipt(run.job.ctx.dir, run.job.ctx.planPath);
  if (refit) run.io.send(planRefitEvent(refit, "reused"));
  if (await deps.palmierPrimary(run)) return;
  const usage = bindTemplateUsageForJob(run.job);
  run.job = usage.job;
  const { history } = usage;
  run.io.send({
    event: "template_usage_history", projectCount: history.projectCount,
    overusedKinds: history.overusedKinds, digest: history.digest,
  });
  await runAuthorStage(run, deps);
  while (true) {
    await deps.planning(run);
    validationStage(run, deps);
    if (await renderStage(run, deps)) {
      await publishApprovedMirror(run, deps);
      return;
    }
    const result = await qualityRoundWithRenderCheckpoint(run, deps);
    if (result.status === "approved") {
      await publishApprovedMirror(run, deps);
      return;
    }
  }
}
