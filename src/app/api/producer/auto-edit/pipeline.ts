import { existsSync, statSync, type Stats } from "fs";
import path from "path";
import {
  bindAuthorityProof,
  planContentHash,
  requireFreshAuthority,
  verifiedAuthorityHash,
} from "@/lib/server/auto-edit-authority";
import {
  checkpointReached,
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
import { routeGeometryFailure } from "./geometry-replan-stage";
import {
  NO_LEGAL_REGION_TOKEN,
  noLegalRegionEvidence,
  type GeometryReplanState,
} from "@/lib/producer/geometry-replan";
import {
  publishApprovedMirror,
  qualityRoundWithRenderCheckpoint,
} from "./pipeline-palmier-publish";
import { MAX_QC_RENDER_ROUNDS } from "./round-policy";
import { AutoEditError } from "./stream";
import {
  currentPlanRefitReceipt,
  planRefitEvent,
} from "../../_lib/plan-refit-transaction";
import { restoreAutoEditDoctrine } from "@/lib/server/auto-edit-doctrine";
import { restoreAutoEditPipeline } from "@/lib/server/auto-edit-pipeline-authority";
import { timedStage } from "@/lib/server/stage-timing";
import { runAuthorStage } from "./authoring-stage";
import { brainModel, brainProvider, brainProviderLabel } from "../../_lib/ai-provider";
import { bindTemplateUsageForJob } from "./template-usage-stage";
import {
  DEFAULT_PIPELINE_DEPENDENCIES,
  type PipelineDependencies,
} from "./pipeline-dependencies";
import type { PipelineOutcome, PipelineRuntime } from "./pipeline-types";
import { bindAutoEditDeliveryController } from "./delivery-controller";
import { assertGuidedDelivery } from "./guided-cut-boundary";
export type { PipelineIo, PipelineRuntime } from "./pipeline-types";
export type { PipelineDependencies } from "./pipeline-dependencies";
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
    && deps.approvedRevisionReady(
      ctx.dir, ctx.planPath, ctx.manifestPath, approval.finalHash)
    && deps.renderGraphReady(
      ctx.dir, ctx.planPath, ctx.manifestPath, approval.finalHash)
    && verifiedAuthorityHash(finalPath, planContentHash(ctx.planPath), deps, authority.digest)
      === approval.finalHash;
}

function candidateRound(job: AutoEditJob): number {
  if ((job.checkpoint === "rendering" || checkpointReached(job.checkpoint, "rendered"))
      && job.qcRound) return job.qcRound;
  return (job.qcRound ?? 0) + 1;
}

function initializeRenderedAuthority(
  run: PipelineRuntime,
  deps: PipelineDependencies,
): void {
  const { ctx } = run.job;
  const candidatePath = run.job.candidatePath;
  const expectedCandidateHash = run.job.candidateHash;
  const expectedPlanHash = run.job.renderedPlanHash;
  const expectedManifestHash = run.job.renderedManifestHash;
  if (!candidatePath || !expectedCandidateHash
      || !expectedPlanHash || !expectedManifestHash) {
    throw new AutoEditError(
      "rendered checkpoint lacks producer authority initialization facts");
  }
  const outcome = deps.initializeAuthority({
    producerDir: ctx.dir,
    planPath: ctx.planPath,
    manifestPath: ctx.manifestPath,
    candidatePath,
    expectedCandidateHash,
    expectedPlanHash,
    expectedManifestHash,
  });
  run.io.send({
    event: "producer_revision_authority",
    status: outcome.status,
    revisionHash: outcome.revisionHash,
  });
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
    // A typed NoLegalRegion payload must survive tail truncation intact —
    // the geometry re-plan route keys on it (contract v3 A2).
    const geometry = noLegalRegionEvidence(result.errTail);
    if (geometry !== null) {
      throw new AutoEditError(`assemble exited ${result.code}. ${NO_LEGAL_REGION_TOKEN}: ${geometry}`);
    }
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
  await timedStage(ctx.dir, "render_round", () => renderCandidate(run, deps, candidate, round));
  return false;
}

export async function runAutoEditPipeline(run: PipelineRuntime,
  dependencies: Partial<PipelineDependencies> = {}): Promise<PipelineOutcome> {
  assertGuidedDelivery(run.job);
  const delivery = bindAutoEditDeliveryController(run, { ...DEFAULT_PIPELINE_DEPENDENCIES, ...dependencies });
  const deps = delivery.dependencies;
  deps.reconciliationReady(run.job.ctx.dir);
  if (run.job.ctx.doctrine) restoreAutoEditDoctrine(run.job.ctx.doctrine);
  if (run.job.ctx.pipeline) restoreAutoEditPipeline(run.job.ctx.pipeline);
  const provider = brainProvider();
  run.io.send({
    event: "start", phase: run.job.phase, scope: run.job.ctx.scope,
    manifestPath: run.job.ctx.manifestPath, planSnapshots: run.job.snapshots, provider,
    resumeFrom: run.job.checkpoint,
    model: brainModel(provider), brain: brainProviderLabel(provider),
    workbench: delivery.policy === "mp4-only" ? "MP4" : "Palmier" });
  const refit = currentPlanRefitReceipt(run.job.ctx.dir, run.job.ctx.planPath);
  if (refit) run.io.send(planRefitEvent(refit, "reused"));
  if (await deps.palmierPrimary(run)) {
    delivery.finish();
    return { status: "completed" };
  }
  const usage = bindTemplateUsageForJob(run.job);
  run.job = usage.job;
  const { history } = usage;
  run.io.send({ event: "template_usage_history", projectCount: history.projectCount,
    overusedKinds: history.overusedKinds, digest: history.digest });
  const authored = await timedStage(run.job.ctx.dir, "authoring", () => runAuthorStage(run, deps));
  if (authored.status === "awaiting_cut_approval") return authored;
  const geometry: GeometryReplanState = { attempts: 0 };
  while (true) {
    await deps.planning(run, { checkpoint: deps.checkpoint });
    validationStage(run, deps);
    try {
      if (await renderStage(run, deps)) {
        await publishApprovedMirror(run, deps);
        delivery.finish();
        return { status: "completed" };
      }
      initializeRenderedAuthority(run, deps);
      const result = await timedStage(
        run.job.ctx.dir, "qc_round", () => qualityRoundWithRenderCheckpoint(run, deps),
      );
      if (result.status === "approved") {
        await publishApprovedMirror(run, deps);
        delivery.finish();
        return { status: "completed" };
      }
    } catch (error) {
      await routeGeometryFailure(run, deps, geometry, error);
    }
  }
}
