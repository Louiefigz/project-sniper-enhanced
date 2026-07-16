import path from "path";
import {
  brainProvider,
  type BrainProvider,
} from "../../_lib/ai-provider";
import { runCodex } from "../../_lib/codex-cli";
import {
  buildClaudeBrainArgs,
  runLegacyBrainProcess,
  uniqueBrainDirs,
  type BrainProcessResult,
  type LegacyBrainInvocation,
} from "./brain-review-process";
import { REPO_ROOT } from "./authoring-prompt";
import { buildPlanReviewPrompt } from "./plan-review-prompt";
import { buildCutReviewPrompt } from "./cut-review-prompt";
import {
  validateCutReviewPacketRef,
  type CutReviewPacketRef,
} from "./cut-review-packet";
import {
  validatePlanReviewPacketRef,
  type PlanReviewPacketRef,
} from "./plan-review-packet";
import { buildRenderedReviewPrompt, type RenderedReviewEvidence } from "./rendered-review-prompt";
import {
  parseProducerReview,
  parseRevisionReceipt,
  validateProducerReview,
  validateRevisionReceipt,
  type ProducerReview,
  type ProducerRevisionReceipt,
} from "./review-contract";
import { buildGateFixPrompt, buildRevisionPrompt } from "./revision-prompt";
import {
  assertCutOnlyRevision,
  assertRevisionPlanUnchanged,
  prepareRevisionStaging,
  promoteRevisionPlan,
} from "./revision-staging";
import { producerRevisionJsonSchema } from "./review-json-schemas";
import type { VisualReviewLens } from "./round-policy";
import type { AutoEditCtx } from "./stream";

// These are hard KILL ceilings: a critic/revision that overruns doesn't just
// slow down — it rethrows and ABORTS the whole job (discarding 15-40 min of
// in-flight work). Critics + the revision writer run on the Opus editing
// default at --effort xhigh (brain-review-process.ts), NOT medium, so a critic
// inspecting a >30-min-authored plan legitimately needs real headroom. The
// caps therefore sit ABOVE the measured maximum, not at it: rendered/QC vision
// lens critics 25 min (measured runs reach ~20), isolated plan/cut critics and
// revision writers 20 min. Critics run concurrently, so the headroom costs
// wall-clock only on a critic that genuinely needs it — cheap insurance
// against a catastrophic whole-job abort. The gate fixer is mechanical: 6 min.
// Full-length longform (10+ min of footage) can legitimately need more: a
// revision writer repairing a salvaged full-video plan blew the 20-min ceiling
// on real C0679 (2026-07-15) and aborted the job. Raise the knobs in
// .env.local (integer minutes; restart Next — workers inherit env at spawn):
//   SNIPER_REVIEW_TIMEOUT_MIN       — vision-lens critics   (default 25)
//   SNIPER_REVIEW_STAGE_TIMEOUT_MIN — plan/cut critics + revision writers (default 20)
function timeoutMinutes(envKey: string, fallbackMin: number): number {
  const raw = process.env[envKey]?.trim();
  if (!raw) return fallbackMin;
  const parsed = Number(raw);
  if (!Number.isInteger(parsed) || parsed < 5 || parsed > 240) {
    throw new Error(`${envKey} must be an integer 5..240 (minutes)`);
  }
  return parsed;
}
const REVIEW_TIMEOUT_MS = timeoutMinutes("SNIPER_REVIEW_TIMEOUT_MIN", 25) * 60 * 1000;
const REVIEW_STAGE_DEADLINE_MS =
  timeoutMinutes("SNIPER_REVIEW_STAGE_TIMEOUT_MIN", 20) * 60 * 1000;
const GATE_FIX_TIMEOUT_MS = 6 * 60 * 1000;
// Reviews are bounded, schema-constrained decisions. The app-wide default may
// remain ultra for open-ended authoring, but even high effort repeatedly
// spends most of this stage's deadline before returning its small contract —
// pin medium (parity with authoring's explicit pins). Revisions use the same
// bounded effort and still pass through an independent critic afterward.
const PRODUCER_CRITIC_REASONING = "medium" as const;
const GATE_FIX_REASONING = "low" as const;

export {
  buildClaudeBrainArgs,
  parseClaudeResultStream,
  runLegacyBrainProcess,
} from "./brain-review-process";
export type {
  BrainProcessResult,
  LegacyBrainInvocation,
} from "./brain-review-process";

export type ProducerReviewRequest =
  | { stage: "cut"; ctx: AutoEditCtx; round: number; packet: CutReviewPacketRef }
  | { stage: "plan"; ctx: AutoEditCtx; round: number; packet: PlanReviewPacketRef }
  | {
    stage: "rendered";
    ctx: AutoEditCtx;
    round: number;
    lens?: VisualReviewLens;
    evidence: RenderedReviewEvidence;
  };

export interface ProducerReviewResult {
  provider: BrainProvider;
  ms: number;
  review: ProducerReview;
}
export interface ProducerRevisionResult {
  provider: BrainProvider;
  ms: number;
  receipt: ProducerRevisionReceipt;
}
type CodexRunner = typeof runCodex;
type LegacyRunner = (invocation: LegacyBrainInvocation) => Promise<BrainProcessResult>;

export interface BrainReviewDependencies {
  provider?: () => BrainProvider;
  codex?: CodexRunner;
  legacy?: LegacyRunner;
}

function referenceDirs(ctx: AutoEditCtx): string[] {
  const study = ctx.referenceStudy;
  return study ? [
    path.dirname(study.profilePath),
    path.dirname(study.deepStudyPath),
    ...study.representativeFrames.map(path.dirname),
  ] : [];
}

function authorityDirs(ctx: AutoEditCtx): string[] {
  return [...(ctx.doctrine ? [path.dirname(ctx.doctrine.snapshotPath)] : []),
    ...(ctx.pipeline ? [ctx.pipeline.snapshotRoot] : []),
    ...(ctx.templateUsage ? [path.dirname(ctx.templateUsage.path)] : [])];
}

function evidenceDirs(request: ProducerReviewRequest): string[] {
  if (request.stage !== "rendered") return [];
  return [
    path.dirname(request.evidence.auditReportPath),
    ...request.evidence.framePaths.map(path.dirname),
    ...(request.evidence.finalPath ? [path.dirname(request.evidence.finalPath)] : []),
  ];
}

function reviewReadDirs(request: ProducerReviewRequest): string[] {
  if (request.stage === "plan" || request.stage === "cut") return [];
  return uniqueBrainDirs([
    REPO_ROOT,
    request.ctx.dir,
    request.ctx.transcriptsDir,
    ...authorityDirs(request.ctx),
    ...referenceDirs(request.ctx),
    ...evidenceDirs(request),
  ]);
}

function revisionReadDirs(ctx: AutoEditCtx): string[] {
  return uniqueBrainDirs([
    REPO_ROOT, ctx.dir, ctx.transcriptsDir, ...authorityDirs(ctx), ...referenceDirs(ctx),
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

async function runCodexReview(
  request: ProducerReviewRequest,
  codex: CodexRunner,
): Promise<ProducerReviewResult> {
  const result = await codex({
    prompt: reviewPrompt(request),
    sandbox: "read-only",
    timeoutMs: reviewTimeoutMs(request),
    reasoning: PRODUCER_CRITIC_REASONING,
    cwd: reviewCwd(request),
    schema: "producer-review",
    addDirs: reviewReadDirs(request),
    tools: request.stage === "rendered" ? "default" : "none",
  });
  validateIsolatedRequest(request);
  return {
    provider: "codex",
    ms: result.ms,
    review: parseProducerReview(result.message, request.stage),
  };
}

async function runLegacyReview(
  request: ProducerReviewRequest,
  legacy: LegacyRunner,
): Promise<ProducerReviewResult> {
  const result = await legacy({
    args: buildClaudeBrainArgs(
      reviewPrompt(request), request.ctx,
      request.stage === "rendered" ? "review" : "isolated-review",
      reviewReadDirs(request),
    ),
    cwd: reviewCwd(request),
    timeoutMs: reviewTimeoutMs(request),
  });
  validateIsolatedRequest(request);
  return {
    provider: "legacy",
    ms: result.ms,
    review: parseProducerReview(result.message, request.stage),
  };
}

export function runProducerReview(
  request: ProducerReviewRequest,
  dependencies: BrainReviewDependencies = {},
): Promise<ProducerReviewResult> {
  if (!Number.isInteger(request.round) || request.round < 1) {
    throw new Error("producer review round must be a positive integer");
  }
  validateIsolatedRequest(request);
  const provider = (dependencies.provider ?? brainProvider)();
  if (provider === "codex") return runCodexReview(request, dependencies.codex ?? runCodex);
  return runLegacyReview(request, dependencies.legacy ?? runLegacyBrainProcess);
}

type RevisionMode = "revision" | "gate-fix";

interface RevisionSpawnSpec {
  mode: RevisionMode;
  prompt: string;
  timeoutMs: number;
  reasoning: typeof PRODUCER_CRITIC_REASONING | typeof GATE_FIX_REASONING;
  readDirs: string[];
}

/** The gate fixer reads ONLY the staged plan + manifest/transcripts — never
 * the doctrine/reference dirs a full revision re-reads from scratch. */
function gateFixReadDirs(ctx: AutoEditCtx): string[] {
  return uniqueBrainDirs([ctx.dir, ctx.transcriptsDir]);
}

function revisionSpawnSpec(
  ctx: AutoEditCtx,
  review: ProducerReview,
  round: number,
  mode: RevisionMode,
): RevisionSpawnSpec {
  if (mode === "gate-fix") {
    return {
      mode,
      prompt: buildGateFixPrompt(ctx, review, round),
      timeoutMs: GATE_FIX_TIMEOUT_MS,
      reasoning: GATE_FIX_REASONING,
      readDirs: gateFixReadDirs(ctx),
    };
  }
  return {
    mode,
    prompt: buildRevisionPrompt(ctx, review, round),
    timeoutMs: REVIEW_STAGE_DEADLINE_MS,
    reasoning: PRODUCER_CRITIC_REASONING,
    readDirs: revisionReadDirs(ctx),
  };
}

async function runCodexRevision(
  ctx: AutoEditCtx,
  review: ProducerReview,
  spec: RevisionSpawnSpec,
  codex: CodexRunner,
): Promise<ProducerRevisionResult> {
  const result = await codex({
    prompt: spec.prompt,
    sandbox: "workspace-write",
    timeoutMs: spec.timeoutMs,
    reasoning: spec.reasoning,
    cwd: ctx.dir,
    schema: "producer-revision",
    addDirs: spec.readDirs,
  });
  const receipt = validateRevisionReceipt(parseRevisionReceipt(result.message), review);
  return { provider: "codex", ms: result.ms, receipt };
}

async function runLegacyRevision(
  ctx: AutoEditCtx,
  review: ProducerReview,
  spec: RevisionSpawnSpec,
  legacy: LegacyRunner,
): Promise<ProducerRevisionResult> {
  const issueCodes = review.materialIssues.map((issue) => issue.code);
  const invoke = (invocationCtx: AutoEditCtx) => legacy({
    args: buildClaudeBrainArgs(
      spec.prompt, invocationCtx, spec.mode, spec.readDirs,
      producerRevisionJsonSchema(issueCodes),
    ),
    cwd: ctx.dir,
    timeoutMs: spec.timeoutMs,
  });
  let result: BrainProcessResult;
  try {
    result = await invoke(ctx);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const usedResume = spec.mode === "revision"
      && ctx.brainSessionEstablished === true && Boolean(ctx.brainSessionId);
    if (!usedResume || !/session|conversation/i.test(message)) throw error;
    // The retained brain session can outlive claude's local session store
    // (journal resume on a pruned machine). Retry ONE sessionless spawn for
    // resume-shaped failures only; every other failure stays loud.
    result = await invoke({ ...ctx, brainSessionEstablished: false });
  }
  const receipt = validateRevisionReceipt(parseRevisionReceipt(result.message), review);
  return { provider: "legacy", ms: result.ms, receipt };
}

export function runProducerRevision(
  ctx: AutoEditCtx,
  reviewValue: ProducerReview,
  round: number,
  dependencies: BrainReviewDependencies = {},
): Promise<ProducerRevisionResult> {
  if (!Number.isInteger(round) || round < 1) {
    throw new Error("producer revision round must be a positive integer");
  }
  const review = validateProducerReview(reviewValue, reviewValue.stage);
  if (!review.materialIssues.length) throw new Error("cannot revise a passing producer review");
  return runIsolatedRevision(ctx, review, { round, mode: "revision" }, dependencies);
}

/** Bounded low-effort fixer for deterministic gate failures: same isolated
 * staging/receipt plumbing as a revision, but fed ONLY the machine gate
 * diagnostics + the plan, with a 6-minute deadline. Callers own the budget
 * exemption — a gate-fix spawn never charges the planning round budget. */
export function runProducerGateFix(
  ctx: AutoEditCtx,
  reviewValue: ProducerReview,
  round: number,
  dependencies: BrainReviewDependencies = {},
): Promise<ProducerRevisionResult> {
  if (!Number.isInteger(round) || round < 1) {
    throw new Error("producer gate fix round must be a positive integer");
  }
  const review = validateProducerReview(reviewValue, reviewValue.stage);
  if (!review.materialIssues.length) throw new Error("cannot gate-fix a passing producer review");
  return runIsolatedRevision(ctx, review, { round, mode: "gate-fix" }, dependencies);
}

async function runIsolatedRevision(
  ctx: AutoEditCtx,
  review: ProducerReview,
  spawn: { round: number; mode: RevisionMode },
  dependencies: BrainReviewDependencies,
): Promise<ProducerRevisionResult> {
  const staging = prepareRevisionStaging(ctx);
  try {
    const provider = (dependencies.provider ?? brainProvider)();
    const spec = revisionSpawnSpec(staging.ctx, review, spawn.round, spawn.mode);
    const result = provider === "codex"
      ? await runCodexRevision(staging.ctx, review, spec, dependencies.codex ?? runCodex)
      : await runLegacyRevision(staging.ctx, review, spec, dependencies.legacy ?? runLegacyBrainProcess);
    if (review.stage === "cut") assertCutOnlyRevision(staging);
    if (!result.receipt.changedPlan) {
      assertRevisionPlanUnchanged(staging);
      return result;
    }
    promoteRevisionPlan(staging, review.stage !== "cut");
    return result;
  } finally {
    staging.dispose();
  }
}
