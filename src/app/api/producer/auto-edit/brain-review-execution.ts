import path from "node:path";
import { brainProvider, type BrainProvider } from "../../_lib/ai-provider";
import { runCodex } from "../../_lib/codex-cli";
import { buildClaudeBrainArgs, runLegacyBrainProcess } from "./brain-review-process";
import { buildPlanReviewPrompt } from "./plan-review-prompt";
import { buildCutReviewPrompt } from "./cut-review-prompt";
import { validateCutReviewPacketRef, type CutReviewPacketRef } from "./cut-review-packet";
import { validatePlanReviewPacketRef, type PlanReviewPacketRef } from "./plan-review-packet";
import { buildRenderedReviewPrompt, type RenderedReviewEvidence } from "./rendered-review-prompt";
import { parseProducerReview, type ProducerReview } from "./review-contract";
import type { VisualReviewLens } from "./round-policy";
import type { AutoEditCtx } from "./stream";
import { timedStage } from "@/lib/server/stage-timing";
import type { StageTimingMetadata } from "@/lib/server/stage-timing-context";
import {
  brainReadDirs, PRODUCER_CRITIC_REASONING, REVIEW_STAGE_DEADLINE_MS, REVIEW_TIMEOUT_MS,
  type BrainReviewDependencies, type CodexRunner, type LegacyRunner,
} from "./brain-review-settings";

export type ProducerReviewRequest =
  | { stage: "cut"; ctx: AutoEditCtx; round: number; packet: CutReviewPacketRef }
  | { stage: "plan"; ctx: AutoEditCtx; round: number; packet: PlanReviewPacketRef }
  | { stage: "rendered"; ctx: AutoEditCtx; round: number;
      lens?: VisualReviewLens; evidence: RenderedReviewEvidence };

export interface ProducerReviewResult {
  provider: BrainProvider;
  ms: number;
  review: ProducerReview;
}

function reviewReadDirs(request: ProducerReviewRequest): string[] {
  if (request.stage !== "rendered") return [];
  return brainReadDirs(request.ctx, [
    path.dirname(request.evidence.auditReportPath),
    ...request.evidence.framePaths.map(path.dirname),
    ...(request.evidence.finalPath ? [path.dirname(request.evidence.finalPath)] : []),
  ]);
}

function reviewPrompt(request: ProducerReviewRequest): string {
  if (request.stage === "rendered") {
    return buildRenderedReviewPrompt(request.ctx, request.evidence, request.round, request.lens);
  }
  if (request.stage === "cut") {
    const packet = validateCutReviewPacketRef(request.ctx, request.round, request.packet);
    return buildCutReviewPrompt(request.ctx, request.round, request.packet, packet);
  }
  const packet = validatePlanReviewPacketRef(request.ctx, request.round, request.packet);
  return buildPlanReviewPrompt(request.ctx, request.round, request.packet, packet);
}

function reviewCwd(request: ProducerReviewRequest): string {
  return request.stage === "rendered" ? request.ctx.dir : path.dirname(request.packet.path);
}

function reviewTimeoutMs(request: ProducerReviewRequest): number {
  return request.stage === "rendered" ? REVIEW_TIMEOUT_MS : REVIEW_STAGE_DEADLINE_MS;
}

function validateIsolatedRequest(request: ProducerReviewRequest): void {
  if (request.stage === "rendered") return;
  if (!request.ctx.doctrine) {
    throw new Error(`producer ${request.stage} review requires pinned critic doctrine`);
  }
  if (request.stage === "cut") {
    validateCutReviewPacketRef(request.ctx, request.round, request.packet);
  } else {
    validatePlanReviewPacketRef(request.ctx, request.round, request.packet);
  }
}


async function runCodexReview(request: ProducerReviewRequest, prompt: string, codex: CodexRunner) {
  return codex({
    prompt, sandbox: "read-only", timeoutMs: reviewTimeoutMs(request),
    reasoning: PRODUCER_CRITIC_REASONING, cwd: reviewCwd(request),
    schema: "producer-review", addDirs: reviewReadDirs(request),
    tools: request.stage === "rendered" ? "default" : "none",
  });
}

async function runLegacyReview(request: ProducerReviewRequest, prompt: string, legacy: LegacyRunner) {
  return legacy({
    args: buildClaudeBrainArgs(prompt, request.ctx,
      request.stage === "rendered" ? "review" : "isolated-review", reviewReadDirs(request)),
    cwd: reviewCwd(request), timeoutMs: reviewTimeoutMs(request),
  });
}

/** Scalars only: exact UTF-8 prompt size, not an estimated model token count. */
function reviewMetadata(request: ProducerReviewRequest, provider: BrainProvider): StageTimingMetadata {
  return { provider, effort: provider === "codex" ? PRODUCER_CRITIC_REASONING : "xhigh",
    round: request.round, deadlineMs: reviewTimeoutMs(request),
    ...(request.stage === "rendered"
      ? { lens: request.lens ?? "composition", evidenceImages: request.evidence.framePaths.length } : {}),
  };
}

async function executeReview(request: ProducerReviewRequest, provider: BrainProvider,
  dependencies: BrainReviewDependencies): Promise<ProducerReviewResult> {
  const metadata = reviewMetadata(request, provider), stage = `critic_${request.stage}`;
  const prompt = await timedStage(request.ctx.dir, `${stage}_prepare`, async () => {
    validateIsolatedRequest(request);
    return reviewPrompt(request);
  }, metadata);
  const input = { ...metadata, promptBytes: Buffer.byteLength(prompt, "utf8") };
  const result = await timedStage(request.ctx.dir, `${stage}_provider`, () =>
    provider === "codex"
      ? runCodexReview(request, prompt, dependencies.codex ?? runCodex)
      : runLegacyReview(request, prompt, dependencies.legacy ?? runLegacyBrainProcess), input);
  return timedStage(request.ctx.dir, `${stage}_result_check`, async () => {
    validateIsolatedRequest(request);
    return { provider, ms: result.ms, review: parseProducerReview(result.message, request.stage) };
  }, metadata);
}

/** Includes preflight failures; child spans distinguish preparation, provider and result checks. */
export function runProducerReview(request: ProducerReviewRequest,
  dependencies: BrainReviewDependencies = {}): Promise<ProducerReviewResult> {
  if (!Number.isInteger(request.round) || request.round < 1) {
    throw new Error("producer review round must be a positive integer");
  }
  const provider = (dependencies.provider ?? brainProvider)();
  return timedStage(request.ctx.dir, `critic_${request.stage}`,
    () => executeReview(request, provider, dependencies), reviewMetadata(request, provider));
}
