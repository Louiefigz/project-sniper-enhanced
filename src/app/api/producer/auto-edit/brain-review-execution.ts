import path from "node:path";
import { brainProvider, type BrainProvider } from "../../_lib/ai-provider";
import { runCodex } from "../../_lib/codex-cli";
import type { ProviderJailScope } from "../../_lib/provider-media-jail";
import { buildClaudeBrainArgs, runLegacyBrainProcess } from "./brain-review-process";
import { buildPlanReviewPrompt } from "./plan-review-prompt";
import { buildCutReviewPrompt } from "./cut-review-prompt";
import { validateCutReviewPacketRef, type CutReviewPacketRef } from "./cut-review-packet";
import { validatePlanReviewPacketRef, type PlanReviewPacketRef } from "./plan-review-packet";
import { buildRenderedReviewPrompt, type RenderedReviewAttachments,
  type RenderedReviewEvidence } from "./rendered-review-prompt";
import { renderedReviewAttachments } from "./rendered-review-attachments";
import { attachmentPaths, claudeRenderedArgs, claudeRenderedInput } from "./rendered-review-invocation";
import { parseProducerReview, type ProducerReview } from "./review-contract";
import type { VisualReviewLens } from "./round-policy";
import type { AutoEditCtx } from "./stream";
import { timedStage } from "@/lib/server/stage-timing";
import type { StageTimingMetadata } from "@/lib/server/stage-timing-context";
import {
  PRODUCER_CRITIC_REASONING, REVIEW_STAGE_DEADLINE_MS, REVIEW_TIMEOUT_MS,
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

interface PreparedReview {
  prompt: string;
  /** Rendered only: still images attached to the tool-less critic. */
  attachments?: RenderedReviewAttachments;
}

/** Rendered critics run in the audit folder with only still-image attachments. */
async function prepareReview(request: ProducerReviewRequest): Promise<PreparedReview> {
  if (request.stage === "rendered") {
    const attachments = await renderedReviewAttachments(request.evidence.framePaths,
      path.dirname(request.evidence.auditReportPath), request.ctx.referenceStudy?.representativeFrames ?? []);
    return { attachments,
      prompt: buildRenderedReviewPrompt(request.ctx, request.evidence, request.round, request.lens ?? "composition", attachments) };
  }
  if (request.stage === "cut") {
    const packet = validateCutReviewPacketRef(request.ctx, request.round, request.packet);
    return { prompt: buildCutReviewPrompt(request.ctx, request.round, request.packet, packet) };
  }
  const packet = validatePlanReviewPacketRef(request.ctx, request.round, request.packet);
  return { prompt: buildPlanReviewPrompt(request.ctx, request.round, request.packet, packet) };
}

function reviewCwd(request: ProducerReviewRequest): string {
  return request.stage === "rendered" ? path.dirname(request.evidence.auditReportPath) : path.dirname(request.packet.path);
}

function reviewTimeoutMs(request: ProducerReviewRequest): number {
  return request.stage === "rendered" ? REVIEW_TIMEOUT_MS : REVIEW_STAGE_DEADLINE_MS;
}

function validateIsolatedRequest(request: ProducerReviewRequest): void {
  if (!request.ctx.doctrine) {
    throw new Error(`producer ${request.stage} review requires pinned critic doctrine`);
  }
  if (request.stage === "cut") {
    validateCutReviewPacketRef(request.ctx, request.round, request.packet);
  } else if (request.stage === "plan") {
    validatePlanReviewPacketRef(request.ctx, request.round, request.packet);
  }
}


/** The producer folder is hidden from a rendered critic except the folder holding its frames. */
function jailScope(request: ProducerReviewRequest): ProviderJailScope {
  return { project: request.ctx.dir, review: reviewCwd(request) };
}

/** Every critic is tool-less; rendered critics also run under the OS media boundary. */
async function runCodexReview(request: ProducerReviewRequest, prepared: PreparedReview, codex: CodexRunner) {
  return codex({
    prompt: prepared.prompt, sandbox: "read-only", timeoutMs: reviewTimeoutMs(request),
    reasoning: PRODUCER_CRITIC_REASONING, cwd: reviewCwd(request),
    schema: "producer-review", addDirs: [], tools: "none",
    ...(prepared.attachments ? { imagePaths: attachmentPaths(prepared.attachments), jail: jailScope(request) } : {}),
  });
}

async function runLegacyReview(request: ProducerReviewRequest, prepared: PreparedReview, legacy: LegacyRunner) {
  const common = { cwd: reviewCwd(request), timeoutMs: reviewTimeoutMs(request) };
  if (prepared.attachments) {
    return legacy({ ...common, args: claudeRenderedArgs(request.ctx), jail: jailScope(request),
      stdin: claudeRenderedInput(prepared.prompt, prepared.attachments) });
  }
  return legacy({ ...common, args: buildClaudeBrainArgs(prepared.prompt, request.ctx, "isolated-review", []) });
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
  const prepared = await timedStage(request.ctx.dir, `${stage}_prepare`, async () => {
    validateIsolatedRequest(request);
    return prepareReview(request);
  }, metadata);
  const input = { ...metadata, promptBytes: Buffer.byteLength(prepared.prompt, "utf8"),
    ...(prepared.attachments ? { attachedImages: attachmentPaths(prepared.attachments).length } : {}) };
  const result = await timedStage(request.ctx.dir, `${stage}_provider`, () =>
    provider === "codex"
      ? runCodexReview(request, prepared, dependencies.codex ?? runCodex)
      : runLegacyReview(request, prepared, dependencies.legacy ?? runLegacyBrainProcess), input);
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
