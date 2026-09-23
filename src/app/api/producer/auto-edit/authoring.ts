import path from "path";
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
  buildCutAuthoringPrompt,
  claudeCutAuthoringBashPatterns,
} from "./cut-authoring-prompt";
import { AutoEditCtx, Send } from "./stream";
import { authoringReasoning } from "./authoring-reasoning";
import { AUTHORING_OUTPUT_MAX_BYTES, authoringTextState, observeCodexAuthoringError, observeAuthoringEvent, observeAuthoringText } from "./authoring-stream-contract";
import {
  AUTHORING_TIMEOUT_MS,
  runClaudeAuthoringProcess,
  type AuthoringResult,
} from "./claude-authoring-process";
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

function claudeAuthoringEffort(): "xhigh" {
  // Operator directive (2026-07-14): run the editing brain at maximum reasoning
  // (Opus xhigh) for BOTH cut and visual authoring. The editorial/craft
  // decisions are the whole point — spend the tokens where the judgment lives.
  return "xhigh";
}

function stagePrompt(ctx: AutoEditCtx, provider: BrainProvider, stage: AuthoringStage): string {
  return stage === "cut"
    ? buildCutAuthoringPrompt(ctx, provider)
    : buildAuthoringPrompt(ctx, provider);
}

function allowedTools(ctx: AutoEditCtx, stage: AuthoringStage): string {
  const patterns = stage === "cut"
    ? claudeCutAuthoringBashPatterns(ctx) : claudeAuthoringBashPatterns(ctx);
  const bash = patterns.map((command) => `Bash(${command})`);
  // No Skill(...) entry: authoring runs with no setting sources, so skills never load;
  // the prompt names the pinned doctrine files to read instead.
  return [
    ...bash,
    `Edit(/${ctx.planPath})`,
    `Write(/${ctx.planPath})`,
    "Read",
    ...(stage === "visual" ? ["Glob", "Grep"] : []),
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
  stage: AuthoringStage = "visual",
  sessionMode: AuthoringSessionMode = "start",
): string[] {
  const readableDirs = [
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
}

/** Preserve explicit editor stops across final output, cancellation and timeout. */
async function runCodexAuthoring(ctx: AutoEditCtx, send: Send,
  codex: CodexRunner, stage: AuthoringStage): Promise<AuthoringResult> {
  const started = Date.now();
  const effort = authoringReasoning(ctx);
  const state = authoringTextState(), stop = new AbortController();
  dlog("producer:auto-edit", "spawn codex (authoring)", {
    dir: ctx.dir, scope: ctx.scope, ...effort,
  });
  send({ event: "authoring_reasoning_selected", provider: "codex", ...effort });
  try {
    const result = await codex({
      prompt: stagePrompt(ctx, "codex", stage),
      sandbox: "workspace-write",
      timeoutMs: AUTHORING_TIMEOUT_MS,
      reasoning: effort.reasoning,
      cwd: ctx.dir,
      maxOutputBytes: AUTHORING_OUTPUT_MAX_BYTES,
      signal: stop.signal,
      onEvent: (event) => {
        observeAuthoringEvent(state, "codex", event);
        forwardCodexEvent(event, send);
        if (state.blocked || state.protocolFailure || state.providerFailure) stop.abort();
      },
    });
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
  }
}

/**
 * Run the claude CLI to author the plan; resolves on process exit (never
 * rejects — the caller reads `code`/`timedOut`). See AUTHORING_TIMEOUT_MS.
 */
function runClaudeAuthoring(
  ctx: AutoEditCtx,
  send: Send,
  stage: AuthoringStage,
  sessionMode: AuthoringSessionMode,
): Promise<AuthoringResult> {
  return runClaudeAuthoringProcess(ctx, send, stage, claudeArgs(ctx, stage, sessionMode));
}

export interface AuthoringRunOptions {
  stage?: AuthoringStage;
  sessionMode?: AuthoringSessionMode;
}

/** Author with the configured subscription brain, then let the route render. */
export function runAuthoring(
  ctx: AutoEditCtx,
  send: Send,
  dependencies: AuthoringDependencies = {},
  options: AuthoringRunOptions = {},
): Promise<AuthoringResult> {
  const stage = options.stage ?? "visual";
  const sessionMode = options.sessionMode ?? "start";
  const provider = (dependencies.provider ?? brainProvider)();
  if (provider === "codex") {
    return runCodexAuthoring(
      ctx, send, dependencies.codex ?? runCodex, stage,
    );
  }
  return runClaudeAuthoring(ctx, send, stage, sessionMode);
}
