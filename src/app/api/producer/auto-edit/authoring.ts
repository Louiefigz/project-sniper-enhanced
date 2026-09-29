import path from "path";
import type { ChildProcess } from "node:child_process";
import {
  brainProvider,
  claudeModelArgs,
  type BrainProvider,
} from "../../_lib/ai-provider";
import { runCodex } from "../../_lib/codex-cli";
import { dlog, derror } from "@/lib/debug";
import {
  buildAuthoringPrompt,
  claudeAuthoringBashPatterns,
} from "./authoring-prompt";
import {
  buildVisualPlanningPrompt, visualPlanningBashPatterns,
} from "./visual-planning-prompt";
import { visualPlanAuthoringPaths } from "./authoring-prompt-inputs";
import {
  buildCutAuthoringPrompt,
  claudeCutAuthoringBashPatterns,
} from "./cut-authoring-prompt";
import {
  authoringWorkDir, ordinaryVisualPlanRequired, AutoEditCtx, Send,
} from "./stream";
import { authoringReasoning } from "./authoring-reasoning";
import { AUTHORING_OUTPUT_MAX_BYTES, authoringTextState, observeCodexAuthoringError, observeAuthoringEvent, observeAuthoringText } from "./authoring-stream-contract";
import {
  AUTHORING_TIMEOUT_MS,
  runClaudeAuthoringProcess,
  type AuthoringResult,
} from "./claude-authoring-process";
import { prepareVisualPlanContext } from "./visual-plan-context";
import {
  fenceProcessTree,
  withTrackedProcessObserver,
} from "../../_lib/child-process-lifecycle";
import {
  assertAuthoringAuthorityOutsideStaging,
  prepareInitialAuthoringStaging,
  promoteInitialAuthoring,
} from "./initial-authoring-staging";
import { allocatedCreativeRoute } from "./creative-route-dispatch";
export { buildAuthoringPrompt } from "./authoring-prompt";
export {
  authoringPermissionDenial,
  authoringStreamSessionId,
} from "./authoring-stream-contract";

// PHASE 1 — the EDITOR BRAIN. Claude keeps the established repo-root bridge;
// Codex runs from the job dir with the repo read-only. Both only AUTHOR the
// edit plan; deterministic rendering remains phase 2, route-side.
// Exact command spelling matters: Claude's matcher treats redundant shell
// quotes as bytes, so prompts use minimally quoted canonical commands. Gate
// readers receive exact pinned commands. Claude permission paths beginning in
// // are absolute; a single / is workspace-relative and silently misses an
// absolute tool input. dontAsk therefore stays fail-closed outside the exact
// plan path and pinned Bash commands.
export type AuthoringStage = "cut" | "visual";
export type AuthoringPassStage = AuthoringStage | "visual-plan";

function claudeAuthoringEffort(): "xhigh" {
  // Operator directive (2026-07-14): run the editing brain at maximum reasoning
  // (Opus xhigh) for BOTH cut and visual authoring. The editorial/craft
  // decisions are the whole point — spend the tokens where the judgment lives.
  return "xhigh";
}

function stagePrompt(ctx: AutoEditCtx, provider: BrainProvider, stage: AuthoringPassStage): string {
  if (stage === "cut") return buildCutAuthoringPrompt(ctx, provider);
  return stage === "visual-plan"
    ? buildVisualPlanningPrompt(ctx, provider) : buildAuthoringPrompt(ctx, provider);
}

function allowedTools(ctx: AutoEditCtx, stage: AuthoringPassStage): string {
  const patterns = stage === "cut" ? claudeCutAuthoringBashPatterns(ctx)
    : stage === "visual-plan" ? visualPlanningBashPatterns(ctx)
      : claudeAuthoringBashPatterns(ctx);
  const bash = patterns.map((command) => `Bash(${command})`);
  const writable = stage === "visual-plan" ? visualPlanAuthoringPaths(ctx)
    : [ctx.planPath, ...(stage === "visual" && !ctx.visualPlan
      ? visualPlanAuthoringPaths(ctx) : [])];
  // No Skill(...) entry: authoring runs with no setting sources, so skills never load;
  // the prompt names the pinned doctrine files to read instead.
  return [
    ...bash,
    ...writable.flatMap((file) => [`Edit(/${file})`, `Write(/${file})`]),
    "Read",
    ...(stage !== "cut" ? ["Glob", "Grep"] : []),
  ].join(",");
}

export type { AuthoringResult } from "./claude-authoring-process";

export type AuthoringSessionMode = "start" | "resume";

function sessionArgs(ctx: AutoEditCtx, mode: AuthoringSessionMode): string[] {
  if (!ctx.brainSessionId) return [];
  return mode === "resume"
    ? ["--resume", ctx.brainSessionId]
    : ["--session-id", ctx.brainSessionId];
}

export function claudeArgs(
  ctx: AutoEditCtx,
  stage: AuthoringPassStage = "visual",
  sessionMode: AuthoringSessionMode = "start",
): string[] {
  const readableDirs = [
    authoringWorkDir(ctx),
    ctx.dir,
    ctx.transcriptsDir,
    ...(ctx.pipeline ? [ctx.pipeline.snapshotRoot] : []),
    ...(ctx.referenceStudy ? [path.dirname(ctx.referenceStudy.deepStudyPath)] : []),
  ];
  return [
    "-p", stagePrompt(ctx, "legacy", stage),
    ...sessionArgs(ctx, sessionMode),
    ...claudeModelArgs(),
    "--effort", claudeAuthoringEffort(),
    "--output-format", "stream-json",
    "--verbose",
    ...readableDirs.flatMap((dir) => ["--add-dir", dir]),
    "--permission-mode", "dontAsk",
    "--allowedTools", allowedTools(ctx, stage),
  ];
}

/** Forward one Codex JSONL event using the same authoring_* SSE namespace. */
function forwardCodexEvent(event: Record<string, unknown>, send: Send): void {
  const type = typeof event.type === "string" ? event.type : "raw";
  send({ ...event, event: `authoring_${type}`, provider: "codex" });
}

type CodexRunner = typeof runCodex;

export interface AuthoringDependencies {
  provider?: () => BrainProvider;
  codex?: CodexRunner;
  prepareVisualPlan?: typeof prepareVisualPlanContext;
  /** Focused process-adapter tests may replace the filesystem promotion. */
  promote?: typeof promoteInitialAuthoring;
}

/** Preserve explicit editor stops across final output, cancellation and timeout. */
async function runCodexAuthoring(ctx: AutoEditCtx, send: Send,
  codex: CodexRunner, stage: AuthoringPassStage): Promise<AuthoringResult> {
  const started = Date.now();
  const effort = authoringReasoning(ctx);
  const state = authoringTextState(), stop = new AbortController();
  let ownedProcess: ChildProcess | undefined;
  dlog("producer:auto-edit", "spawn codex (authoring)", {
    dir: authoringWorkDir(ctx), scope: ctx.scope, ...effort,
  });
  send({ event: "authoring_reasoning_selected", provider: "codex", ...effort });
  try {
    const result = await withTrackedProcessObserver(
      (child) => { ownedProcess ??= child; }, () => codex({
      prompt: stagePrompt(ctx, "codex", stage),
      sandbox: "workspace-write",
      timeoutMs: AUTHORING_TIMEOUT_MS,
      reasoning: effort.reasoning,
      cwd: authoringWorkDir(ctx),
      maxOutputBytes: AUTHORING_OUTPUT_MAX_BYTES,
      signal: stop.signal,
      onEvent: (event) => {
        observeAuthoringEvent(state, "codex", event);
        forwardCodexEvent(event, send);
        if (state.blocked || state.protocolFailure || state.providerFailure) stop.abort();
      },
      }),
    );
    observeAuthoringText(state, result.message);
    return {
      code: state.protocolFailure || state.providerFailure ? 1 : 0,
      timedOut: false,
      errTail: result.stderr,
      ms: result.ms,
      provider: "codex",
      authored: state.authored,
      blocked: state.blocked, protocolFailure: state.protocolFailure, providerFailure: state.providerFailure,
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    observeCodexAuthoringError(state, message);
    const timedOut = /timed out/i.test(message);
    derror("producer:auto-edit", "codex authoring failed", error);
    return {
      code: 1,
      timedOut,
      errTail: message,
      ms: Date.now() - started,
      provider: "codex",
      authored: null,
      blocked: state.blocked, protocolFailure: state.protocolFailure, providerFailure: state.providerFailure,
    };
  } finally {
    if (ownedProcess) await fenceProcessTree(ownedProcess);
  }
}

/**
 * Run the claude CLI to author the plan; resolves on process exit (never
 * rejects — the caller reads `code`/`timedOut`). See AUTHORING_TIMEOUT_MS.
 */
function runClaudeAuthoring(
  ctx: AutoEditCtx,
  send: Send,
  stage: AuthoringPassStage,
  sessionMode: AuthoringSessionMode,
): Promise<AuthoringResult> {
  return runClaudeAuthoringProcess(ctx, send, stage, claudeArgs(ctx, stage, sessionMode));
}

export interface AuthoringRunOptions {
  stage?: AuthoringStage;
  sessionMode?: AuthoringSessionMode;
}

function shouldPromote(result: AuthoringResult): boolean {
  return result.code === 0 && !result.timedOut && !result.blocked
    && !result.protocolFailure && !result.providerFailure;
}

function promotionFailure(result: AuthoringResult, error: unknown): AuthoringResult {
  const message = error instanceof Error ? error.message : String(error);
  derror("producer:auto-edit", "isolated authoring promotion failed", error);
  return { ...result, code: 1, authored: null,
    errTail: `Isolated authoring output was rejected: ${message}` };
}

interface AuthoringPassOptions {
  stage: AuthoringPassStage;
  sessionMode: AuthoringSessionMode;
}

/** Author with the configured subscription brain, then let the route render. */
async function runAuthoringPass(
  ctx: AutoEditCtx,
  send: Send,
  dependencies: AuthoringDependencies = {},
  options: AuthoringPassOptions,
): Promise<AuthoringResult> {
  const { stage, sessionMode } = options;
  const staging = prepareInitialAuthoringStaging(ctx, stage);
  try {
    assertAuthoringAuthorityOutsideStaging(staging);
    if (stage !== "cut") {
      (dependencies.prepareVisualPlan ?? prepareVisualPlanContext)(staging.ctx);
    }
    const provider = (dependencies.provider ?? brainProvider)();
    const result = provider === "codex"
      ? await runCodexAuthoring(
        staging.ctx, send, dependencies.codex ?? runCodex, stage,
      )
      : await runClaudeAuthoring(staging.ctx, send, stage, sessionMode);
    if (!shouldPromote(result)) return result;
    try {
      (dependencies.promote ?? promoteInitialAuthoring)(staging);
      return result;
    } catch (error) {
      return promotionFailure(result, error);
    }
  } finally {
    staging.dispose();
  }
}

/** Plan route-neutrally, let the controller allocate, then compile only ordinary. */
export async function runAuthoring(
  ctx: AutoEditCtx,
  send: Send,
  dependencies: AuthoringDependencies = {},
  options: AuthoringRunOptions = {},
): Promise<AuthoringResult> {
  const stage = options.stage ?? "visual";
  if (stage !== "visual" || !ordinaryVisualPlanRequired(ctx) || ctx.visualPlan) {
    return runAuthoringPass(ctx, send, dependencies, {
      stage, sessionMode: options.sessionMode ?? "start",
    });
  }
  const planned = await runAuthoringPass(ctx, send, dependencies, {
    stage: "visual-plan", sessionMode: options.sessionMode ?? "start",
  });
  if (!shouldPromote(planned) || !ctx.visualPlan) return planned;
  if (allocatedCreativeRoute(ctx, ctx.visualPlan) !== "ordinary") return planned;
  return runAuthoringPass(ctx, send, dependencies, {
    stage: "visual", sessionMode: "resume",
  });
}
