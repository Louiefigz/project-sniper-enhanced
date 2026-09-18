import { brainProvider, type BrainProvider } from "../../_lib/ai-provider";
import { runCodex } from "../../_lib/codex-cli";
import {
  buildClaudeBrainArgs, runLegacyBrainProcess, uniqueBrainDirs, type BrainProcessResult,
} from "./brain-review-process";
import {
  parseRevisionReceipt, validateProducerReview, validateRevisionReceipt,
  type ProducerReview, type ProducerRevisionReceipt,
} from "./review-contract";
import { buildGateFixPrompt, buildRevisionPrompt } from "./revision-prompt";
import {
  assertCutOnlyRevision, assertRevisionPlanUnchanged, prepareRevisionStaging, promoteRevisionPlan,
} from "./revision-staging";
import { producerRevisionJsonSchema } from "./review-json-schemas";
import type { AutoEditCtx } from "./stream";
import {
  brainReadDirs, GATE_FIX_REASONING, GATE_FIX_TIMEOUT_MS, PRODUCER_CRITIC_REASONING,
  REVIEW_STAGE_DEADLINE_MS, type BrainReviewDependencies, type CodexRunner, type LegacyRunner,
} from "./brain-review-settings";

export {
  buildClaudeBrainArgs, parseClaudeResultStream, runLegacyBrainProcess,
} from "./brain-review-process";
export type { BrainProcessResult, LegacyBrainInvocation } from "./brain-review-process";
export { runProducerReview } from "./brain-review-execution";
export type { ProducerReviewRequest, ProducerReviewResult } from "./brain-review-execution";
export type { BrainReviewDependencies } from "./brain-review-settings";

export interface ProducerRevisionResult {
  provider: BrainProvider;
  ms: number;
  receipt: ProducerRevisionReceipt;
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
    readDirs: brainReadDirs(ctx),
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
