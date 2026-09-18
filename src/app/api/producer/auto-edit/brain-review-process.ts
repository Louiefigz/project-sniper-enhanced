import { spawn } from "child_process";
import path from "path";
import { claudeModelArgs, claudeProcessEnv } from "../../_lib/ai-provider";
import { admitSubscriptionInvocation } from "../../_lib/subscription-invocation";
import { providerMediaJail } from "../../_lib/provider-media-jail";
import {
  PROCESS_TERM_GRACE_MS,
  shouldDetachProcessGroup,
  terminateProcessTree,
  trackProcessTree,
} from "../../_lib/child-process-lifecycle";
import type { AutoEditCtx } from "./stream";

const CLAUDE_BIN = process.env.CLAUDE_BIN || "claude";
const READ_TOOLS = "Read,Glob,Grep";

export interface LegacyBrainInvocation {
  args: string[];
  cwd: string;
  timeoutMs: number;
  /** Optional combined stdout/stderr budget; old callers retain their prior behavior. */
  maxOutputBytes?: number;
  signal?: AbortSignal;
  /** stream-json input (text + image blocks) written to stdin, then closed. */
  stdin?: string;
  /** Run under the OS media boundary (provider-media-jail.ts); requires `--tools ""`. */
  jail?: boolean;
}

function toolless(args: readonly string[]): boolean {
  const index = args.indexOf("--tools");
  return index >= 0 && args[index + 1] === "" && args.indexOf("--tools", index + 1) < 0;
}

export interface BrainProcessResult {
  message: string;
  stderr: string;
  ms: number;
}

export type ClaudeJsonSchema = Record<string, unknown>;

export function uniqueBrainDirs(dirs: string[]): string[] {
  return [...new Set(dirs.filter(Boolean).map((dir) => path.resolve(dir)))];
}

function revisionTools(ctx: AutoEditCtx): string {
  const scratch = path.join(ctx.dir, "brain-review-scratch", "**");
  return [
    READ_TOOLS,
    `Edit(${ctx.planPath})`,
    `Write(${ctx.planPath})`,
    `Edit(${scratch})`,
    `Write(${scratch})`,
  ].join(",");
}

/** Resume the job's established brain session for plan-mutating writers only
 * (parity with authoring): the doctrine/plan context is already loaded there.
 * Critics NEVER resume — independence from the authoring conversation is a
 * review invariant. The gate fixer stays sessionless too: its prompt is
 * deliberately minimal and must not inherit the full doctrine context. */
function brainSessionResumeArgs(ctx: AutoEditCtx): string[] {
  return ctx.brainSessionEstablished === true && ctx.brainSessionId
    ? ["--resume", ctx.brainSessionId] : [];
}

export type ClaudeBrainMode = "review" | "isolated-review" | "revision" | "gate-fix";

export function buildClaudeBrainArgs(
  prompt: string,
  ctx: AutoEditCtx,
  mode: ClaudeBrainMode,
  readDirs: string[],
  jsonSchema?: ClaudeJsonSchema,
): string[] {
  const isolated = mode === "isolated-review";
  const args = [
    "-p", prompt,
    ...(mode === "revision" ? brainSessionResumeArgs(ctx) : []),
    // Operator directive (2026-07-14): the editing review/revision brain runs at
    // maximum reasoning (Opus xhigh) — these are the craft judgment calls. The
    // gate fixer applies named mechanical diagnostics only ("make these named
    // deterministic gates pass, change nothing else"), so it stays low effort
    // AND runs on Sonnet, not the Opus editing brain — a gate-fix on Opus was
    // measured at ~5 min/attempt with no editorial upside. Sonnet cuts that
    // sharply; the critic/revision writers keep the Opus default.
    ...(mode === "gate-fix" ? claudeModelArgs("sonnet") : claudeModelArgs()),
    "--effort", mode === "gate-fix" ? "low" : "xhigh",
    "--output-format", "stream-json",
    "--verbose",
    "--permission-mode", "acceptEdits",
    "--tools", isolated ? "" : "default",
    "--allowedTools", isolated ? "" : mode === "review" ? READ_TOOLS : revisionTools(ctx),
  ];
  if (jsonSchema) args.push("--json-schema", JSON.stringify(jsonSchema));
  for (const dir of uniqueBrainDirs(readDirs)) args.push("--add-dir", dir);
  return args;
}

export function parseClaudeResultStream(stdout: string): string {
  let message = "";
  for (const line of stdout.split("\n")) {
    if (!line.trim()) continue;
    let event: Record<string, unknown>;
    try {
      event = JSON.parse(line) as Record<string, unknown>;
    } catch {
      continue;
    }
    if (event.type !== "result") continue;
    if (event.structured_output && typeof event.structured_output === "object") {
      message = JSON.stringify(event.structured_output);
    } else if (typeof event.result === "string") {
      message = event.result;
    }
  }
  if (!message) throw new Error("Claude exited without a structured result message");
  return message;
}

export async function runLegacyBrainProcess(
  invocation: LegacyBrainInvocation,
): Promise<BrainProcessResult> {
  if (invocation.maxOutputBytes !== undefined && (!Number.isSafeInteger(invocation.maxOutputBytes)
      || invocation.maxOutputBytes < 1 || invocation.maxOutputBytes > 16 * 1024 * 1024)) {
    throw new Error("Claude output budget is invalid");
  }
  if (invocation.jail && !toolless(invocation.args)) {
    throw new Error("The provider media boundary applies only to tool-less Claude runs");
  }
  const admitted = await admitSubscriptionInvocation({ provider: "claude", bin: CLAUDE_BIN,
    args: invocation.args, cwd: invocation.cwd, env: claudeProcessEnv(),
    timeoutMs: invocation.timeoutMs, signal: invocation.signal });
  const command = invocation.jail ? providerMediaJail(admitted.bin, admitted.args)
    : { bin: admitted.bin, args: [...admitted.args] };
  return new Promise((resolve, reject) => {
    const timeoutMs = admitted.remainingMs();
    const proc = trackProcessTree(spawn(command.bin, command.args, {
      cwd: admitted.cwd,
      env: admitted.env,
      detached: shouldDetachProcessGroup(),
    }));
    let stdout = "";
    const stdoutChunks: Buffer[] = [];
    let outputBytes = 0;
    let stderr = "";
    let settled = false;
    let stopError: Error | undefined;
    let forceSettle: ReturnType<typeof setTimeout> | undefined;
    const finish = (error?: Error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (forceSettle) clearTimeout(forceSettle);
      invocation.signal?.removeEventListener("abort", abort);
      if (error) reject(error);
      else {
        try {
          const text = invocation.maxOutputBytes === undefined ? stdout : Buffer.concat(stdoutChunks).toString("utf8");
          resolve({ message: parseClaudeResultStream(text), stderr, ms: admitted.elapsedMs() });
        } catch (parseError) {
          reject(parseError);
        }
      }
    };
    const requestStop = (error: Error) => {
      if (settled || stopError) return;
      stopError = error;
      terminateProcessTree(proc);
      forceSettle = setTimeout(() => finish(error), PROCESS_TERM_GRACE_MS + 1_000);
    };
    const abort = () => requestStop(new Error("Claude run was cancelled"));
    const append = (data: Buffer, stream: "stdout" | "stderr") => {
      if (stopError || settled) return;
      outputBytes += data.length;
      if (invocation.maxOutputBytes !== undefined && outputBytes > invocation.maxOutputBytes) {
        requestStop(new Error(`Claude exceeded its ${invocation.maxOutputBytes}-byte output budget`)); return;
      }
      if (stream === "stderr") stderr = (stderr + data.toString()).slice(-8_000);
      else if (invocation.maxOutputBytes === undefined) stdout += data.toString();
      else stdoutChunks.push(data);
    };
    proc.stdout.on("data", (data: Buffer) => append(data, "stdout"));
    proc.stderr.on("data", (data: Buffer) => append(data, "stderr"));
    proc.on("error", (error) => finish(stopError ?? error));
    proc.on("close", (code) => {
      if (stopError) return finish(stopError);
      const detail = stderr.trim().slice(-1_200);
      if (code !== 0) finish(new Error(`Claude exited ${code}${detail ? `: ${detail}` : ""}`));
      else finish();
    });
    const timer = setTimeout(() => {
      requestStop(new Error(`Claude timed out after ${Math.round(invocation.timeoutMs / 1_000)}s`));
    }, timeoutMs);
    invocation.signal?.addEventListener("abort", abort, { once: true });
    if (invocation.signal?.aborted) abort();
    if (invocation.stdin !== undefined && !settled) {
      proc.stdin.on("error", (error) => finish(stopError ?? error));
      proc.stdin.end(invocation.stdin);
    }
  });
}
