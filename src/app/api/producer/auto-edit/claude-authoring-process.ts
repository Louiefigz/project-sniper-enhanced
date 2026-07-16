import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
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
import { REPO_ROOT } from "./authoring-prompt";
import { authoringPermissionDenial, authoringStreamSessionId } from "./authoring-stream-contract";
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
  sessionEstablished?: boolean;
}

interface ProcessInput {
  ctx: AutoEditCtx;
  send: Send;
  stage: AuthoringStage;
  started: number;
}

interface ProcessState {
  timedOut: boolean;
  resultText: string;
  permissionFailure: string;
  sessionEstablished: boolean;
}

function parsedAuthored(message: string): AuthoringResult["authored"] {
  const match = message.match(/AUTHORED ok segments=(\d+) graphics=(\d+)/);
  return match ? { segments: Number(match[1]), graphics: Number(match[2]) } : null;
}

function processLine(
  input: ProcessInput,
  state: ProcessState,
  proc: ChildProcessWithoutNullStreams,
  line: string,
): void {
  try {
    const obj = JSON.parse(line) as Record<string, unknown> & { type?: string };
    if (obj.type === "result" && typeof obj.result === "string") state.resultText = obj.result;
    input.send({ ...obj, event: `authoring_${obj.type || "raw"}` });
  } catch {
    input.send({ event: "authoring_raw", line: line.slice(0, 2000) });
  }
  if (authoringStreamSessionId(line) === input.ctx.brainSessionId) {
    state.sessionEstablished = true;
  }
  const denial = authoringPermissionDenial(line);
  if (!denial || state.permissionFailure) return;
  state.permissionFailure = `Claude authoring permission allowlist mismatch: ${denial}`;
  input.send({ event: "authoring_permission_denied", stage: input.stage,
    message: state.permissionFailure });
  terminateProcessTree(proc);
}

function completedResult(state: ProcessState, code: number | null, started: number,
  stderr: string): AuthoringResult {
  return {
    code: state.permissionFailure ? 1 : code ?? 1,
    timedOut: state.timedOut,
    errTail: state.permissionFailure || stderr,
    ms: Date.now() - started,
    provider: "legacy",
    authored: parsedAuthored(state.resultText),
    sessionEstablished: state.sessionEstablished,
  };
}

function bindProcess(
  proc: ChildProcessWithoutNullStreams,
  input: ProcessInput,
  resolve: (result: AuthoringResult) => void,
): void {
  const state: ProcessState = {
    timedOut: false, resultText: "", permissionFailure: "", sessionEstablished: false,
  };
  const stderr = tailCollector();
  const lines = lineSplitter((line) => processLine(input, state, proc, line));
  const timer = setTimeout(() => {
    state.timedOut = true;
    derror("producer:auto-edit", "authoring timed out — terminating process tree", {
      dir: input.ctx.dir,
    });
    terminateProcessTree(proc);
  }, AUTHORING_TIMEOUT_MS);
  proc.stdout.on("data", (data: Buffer) => lines.push(data.toString()));
  proc.stderr.on("data", (data: Buffer) => stderr.push(data.toString()));
  proc.on("close", (code) => {
    clearTimeout(timer);
    lines.flush();
    resolve(completedResult(state, code, input.started, stderr.get()));
  });
  proc.on("error", (error) => {
    clearTimeout(timer);
    derror("producer:auto-edit", "claude spawn failed", error);
    resolve({ ...completedResult(state, 1, input.started, error.message), authored: null });
  });
}

export function runClaudeAuthoringProcess(
  ctx: AutoEditCtx,
  send: Send,
  stage: AuthoringStage,
  args: string[],
): Promise<AuthoringResult> {
  const env = claudeProcessEnv();
  if (ctx.pipeline) env.SNIPER_PIPELINE_ROOT = ctx.pipeline.snapshotRoot;
  const started = Date.now();
  const model = claudeSettings().model;
  dlog("producer:auto-edit", "spawn claude (authoring)", { dir: ctx.dir, scope: ctx.scope, model });
  send({ event: "authoring_model_selected", provider: "legacy", model });
  const proc = trackProcessTree(spawn(CLAUDE_BIN, args, {
    cwd: REPO_ROOT, env, detached: shouldDetachProcessGroup(),
  }));
  return new Promise((resolve) => bindProcess(proc, { ctx, send, stage, started }, resolve));
}

export type { AuthoringSessionMode };
