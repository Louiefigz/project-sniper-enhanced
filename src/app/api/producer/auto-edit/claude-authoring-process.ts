import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { TextDecoder } from "node:util";
import {
  claudeProcessEnv,
  claudeSettings,
  type BrainProvider,
} from "../../_lib/ai-provider";
import {
  shouldDetachProcessGroup,
  terminateProcessTree,
  trackProcessTree,
} from "../../_lib/child-process-lifecycle";
import { derror, dlog } from "@/lib/debug";
import { admitSubscriptionInvocation } from "../../_lib/subscription-invocation";
import { REPO_ROOT } from "./authoring-prompt";
import { AUTHORING_OUTPUT_MAX_BYTES, authoringPermissionDenial, authoringStreamSessionId,
  authoringTextState, failAuthoringProtocol, observeAuthoringEvent, type AuthoringBlock, type AuthoringTextState } from "./authoring-stream-contract";
import type { AuthoringSessionMode, AuthoringStage } from "./authoring";
import { type AutoEditCtx, type Send, lineSplitter, tailCollector } from "./stream";

const CLAUDE_BIN = process.env.CLAUDE_BIN || "claude";
// Opus 4.8 at xhigh effort reasons for a long time on visual authoring ("all
// the bells and whistles" for an intro), and 30 min was cutting it off
// mid-thought — leaving a partial plan that drew a flood of review issues. Give
// the authoring brain real headroom; the deadline-recovery salvage + review
// triage remain the backstop if it still overruns.
// The deadline applies PER SPAWN (cut pass and visual pass each get their own
// clock). Full-length longform (10+ min of footage) can legitimately need more
// than the default on the visual pass — raise SNIPER_AUTHORING_TIMEOUT_MIN in
// .env.local (integer minutes, 10..240) and restart Next so new workers see it.
function authoringTimeoutMin(): number {
  const raw = process.env.SNIPER_AUTHORING_TIMEOUT_MIN?.trim();
  if (!raw) return 45;
  const parsed = Number(raw);
  if (!Number.isInteger(parsed) || parsed < 10 || parsed > 240) {
    throw new Error("SNIPER_AUTHORING_TIMEOUT_MIN must be an integer 10..240 (minutes)");
  }
  return parsed;
}
export const AUTHORING_TIMEOUT_MIN = authoringTimeoutMin();
export const AUTHORING_TIMEOUT_MS = AUTHORING_TIMEOUT_MIN * 60 * 1000;

export interface AuthoringResult {
  code: number;
  timedOut: boolean;
  errTail: string;
  ms: number;
  provider: BrainProvider;
  authored: { segments: number; graphics: number } | null;
  blocked?: AuthoringBlock | null;
  protocolFailure?: string | null;
  providerFailure?: string | null;
  sessionEstablished?: boolean;
}

interface ProcessInput {
  ctx: AutoEditCtx;
  send: Send;
  stage: AuthoringStage;
  started: number;
  timeoutMs: number;
}

interface ProcessState {
  closed: boolean;
  timedOut: boolean;
  text: AuthoringTextState;
  permissionFailure: string;
  outputFailure: string;
  outputBytes: number;
  sessionEstablished: boolean;
}

/** Inspect one bounded stream row and request at most one explicit outcome stop. */
function processLine(
  input: ProcessInput,
  state: ProcessState,
  proc: ChildProcessWithoutNullStreams,
  line: string,
): void {
  const alreadyStopped = Boolean(state.text.blocked || state.text.protocolFailure || state.text.providerFailure);
  try {
    const obj = JSON.parse(line) as Record<string, unknown> & { type?: string };
    observeAuthoringEvent(state.text, "legacy", obj);
    input.send({ ...obj, event: `authoring_${obj.type || "raw"}` });
  } catch {
    observeAuthoringEvent(state.text, "legacy", { type: "raw" });
    input.send({ event: "authoring_raw", line: line.slice(0, 2000) });
  }
  if (authoringStreamSessionId(line) === input.ctx.brainSessionId) {
    state.sessionEstablished = true;
  }
  if (state.text.blocked || state.text.protocolFailure || state.text.providerFailure) {
    if (!alreadyStopped && !state.closed) terminateProcessTree(proc);
    return;
  }
  const denial = authoringPermissionDenial(line);
  if (!denial || state.permissionFailure) return;
  state.permissionFailure = `Claude authoring permission allowlist mismatch: ${denial}`;
  input.send({ event: "authoring_permission_denied", stage: input.stage,
    message: state.permissionFailure });
  terminateProcessTree(proc);
}

/** Preserve protocol and editor failures independently of the process exit code. */
function completedResult(state: ProcessState, code: number | null, started: number,
  stderr: string): AuthoringResult {
  return {
    code: state.permissionFailure || state.outputFailure || state.text.protocolFailure || state.text.providerFailure ? 1 : code ?? 1,
    timedOut: state.timedOut,
    errTail: state.permissionFailure || state.outputFailure || state.text.protocolFailure || state.text.providerFailure || stderr,
    ms: performance.now() - started,
    provider: "legacy",
    authored: state.text.authored,
    blocked: state.text.blocked,
    protocolFailure: state.text.protocolFailure,
    providerFailure: state.text.providerFailure,
    sessionEstablished: state.sessionEstablished,
  };
}

/** Cap bytes before the shared line splitter or JSON parser allocates whole rows. */
function acceptOutput(state: ProcessState, proc: ChildProcessWithoutNullStreams, data: Buffer): boolean {
  if (state.outputFailure) return false;
  state.outputBytes += data.length;
  if (state.outputBytes <= AUTHORING_OUTPUT_MAX_BYTES) return true;
  state.outputFailure = `Claude authoring exceeded its ${AUTHORING_OUTPUT_MAX_BYTES}-byte output budget`;
  state.text.protocolFailure = state.outputFailure;
  state.text.authored = null;
  terminateProcessTree(proc);
  return false;
}

/** Decode stdout incrementally, refusing invalid bytes and incomplete EOF sequences. */
function decodeOutput(state: ProcessState, proc: ChildProcessWithoutNullStreams,
  decoder: TextDecoder, data?: Buffer): string {
  if (state.text.protocolFailure || state.text.providerFailure) return "";
  try {
    return decoder.decode(data, { stream: data !== undefined });
  } catch {
    failAuthoringProtocol(state.text);
  }
  if (!state.closed && !state.text.blocked) terminateProcessTree(proc);
  return "";
}

/** Observe an already-owned child; this seam neither spawns nor grants provider authority. */
export function bindClaudeAuthoringProcess(
  proc: ChildProcessWithoutNullStreams,
  input: ProcessInput,
  resolve: (result: AuthoringResult) => void,
): void {
  const state: ProcessState = {
    closed: false, timedOut: false, text: authoringTextState(), permissionFailure: "", outputFailure: "",
    outputBytes: 0, sessionEstablished: false,
  };
  const stderr = tailCollector();
  const decoder = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });
  const lines = lineSplitter((line) => processLine(input, state, proc, line));
  const timer = setTimeout(() => {
    if (state.outputFailure || state.text.blocked || state.text.protocolFailure || state.text.providerFailure) return;
    state.timedOut = true;
    derror("producer:auto-edit", "authoring timed out — terminating process tree", {
      dir: input.ctx.dir,
    });
    terminateProcessTree(proc);
  }, input.timeoutMs);
  proc.stdout.on("data", (data: Buffer) => { if (acceptOutput(state, proc, data)) lines.push(decodeOutput(state, proc, decoder, data)); });
  proc.stderr.on("data", (data: Buffer) => { if (acceptOutput(state, proc, data)) stderr.push(data.toString()); });
  proc.on("close", (code) => {
    state.closed = true;
    clearTimeout(timer);
    if (!state.outputFailure) { lines.push(decodeOutput(state, proc, decoder)); lines.flush(); }
    resolve(completedResult(state, code, input.started, stderr.get()));
  });
  proc.on("error", (error) => {
    clearTimeout(timer);
    derror("producer:auto-edit", "claude spawn failed", error);
    resolve({ ...completedResult(state, 1, input.started, error.message), authored: null });
  });
}

export async function runClaudeAuthoringProcess(
  ctx: AutoEditCtx,
  send: Send,
  stage: AuthoringStage,
  args: string[],
): Promise<AuthoringResult> {
  const env = claudeProcessEnv();
  if (ctx.pipeline) env.SNIPER_PIPELINE_ROOT = ctx.pipeline.snapshotRoot;
  const started = performance.now();
  const admitted = await admitSubscriptionInvocation({ provider: "claude", bin: CLAUDE_BIN,
    args, cwd: REPO_ROOT, env, timeoutMs: AUTHORING_TIMEOUT_MS });
  const model = claudeSettings().model;
  dlog("producer:auto-edit", "spawn claude (authoring)", { dir: ctx.dir, scope: ctx.scope, model });
  send({ event: "authoring_model_selected", provider: "legacy", model });
  const timeoutMs = admitted.remainingMs();
  const proc = trackProcessTree(spawn(admitted.bin, admitted.args, {
    cwd: admitted.cwd, env: admitted.env, detached: shouldDetachProcessGroup(),
  }));
  return new Promise((resolve) => bindClaudeAuthoringProcess(proc, { ctx, send, stage, started, timeoutMs }, resolve));
}

export type { AuthoringSessionMode };
