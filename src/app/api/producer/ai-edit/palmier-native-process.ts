import { spawn } from "node:child_process";
import path from "node:path";
import { claudeProcessEnv } from "../../_lib/ai-provider";
import {
  PROCESS_TERM_GRACE_MS,
  shouldDetachProcessGroup,
  terminateProcessTree,
  trackProcessTree,
} from "../../_lib/child-process-lifecycle";
import { pythonInterpreter, SCRIPTS_DIR } from "../../_lib/spawn-python";
import {
  parseClaudeResultStream,
  type BrainProcessResult,
  type LegacyBrainInvocation,
} from "../auto-edit/brain-review-runner";

const DEFAULT_CLI = path.join(
  SCRIPTS_DIR, "producer", "palmier", "native_delta_cli.py",
);
const CLI_TIMEOUT_MS = 30 * 60 * 1000;
const CLAUDE_BIN = process.env.CLAUDE_BIN || "claude";

interface CommandResult {
  code: number | null;
  stdout: string;
  stderr: string;
  ms: number;
}

type NativeEvent = Record<string, unknown>;

function objectLine(line: string): NativeEvent | null {
  try {
    const value: unknown = JSON.parse(line);
    return value && typeof value === "object" && !Array.isArray(value)
      ? value as NativeEvent : null;
  } catch {
    return null;
  }
}

function runCommand(
  command: string,
  args: string[],
  options: {
    cwd: string;
    env: NodeJS.ProcessEnv;
    timeoutMs: number;
    signal?: AbortSignal;
    onStdoutLine?: (line: string) => void;
  },
): Promise<CommandResult> {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const child = trackProcessTree(spawn(command, args, {
      cwd: options.cwd, env: options.env, detached: shouldDetachProcessGroup(),
    }));
    let stdout = "";
    let pending = "";
    let stderr = "";
    let settled = false;
    let stopError: Error | undefined;
    let forced: ReturnType<typeof setTimeout> | undefined;
    const finish = (error?: Error, code: number | null = null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (forced) clearTimeout(forced);
      options.signal?.removeEventListener("abort", abort);
      if (error) reject(error);
      else resolve({ code, stdout, stderr, ms: Date.now() - started });
    };
    const stop = (error: Error) => {
      if (settled || stopError) return;
      stopError = error;
      terminateProcessTree(child);
      forced = setTimeout(() => finish(error), PROCESS_TERM_GRACE_MS + 1_000);
    };
    const abort = () => stop(new Error("Palmier native edit was cancelled"));
    child.stdout.on("data", (data: Buffer) => {
      const text = data.toString();
      stdout += text;
      pending += text;
      const lines = pending.split("\n");
      pending = lines.pop() ?? "";
      for (const line of lines) if (line.trim()) options.onStdoutLine?.(line);
    });
    child.stderr.on("data", (data: Buffer) => (stderr = (stderr + data.toString()).slice(-8_000)));
    child.on("error", (error) => finish(stopError ?? error));
    child.on("close", (code) => {
      if (pending.trim()) options.onStdoutLine?.(pending);
      finish(stopError, code);
    });
    const timer = setTimeout(() => stop(new Error(
      `Palmier native process timed out after ${Math.round(options.timeoutMs / 1_000)}s`,
    )), options.timeoutMs);
    options.signal?.addEventListener("abort", abort, { once: true });
    if (options.signal?.aborted) abort();
  });
}

function lastObject(stdout: string): Record<string, unknown> {
  for (const line of stdout.trim().split("\n").filter(Boolean).reverse()) {
    try {
      const value = JSON.parse(line) as unknown;
      if (value && typeof value === "object" && !Array.isArray(value)) {
        return value as Record<string, unknown>;
      }
    } catch {}
  }
  throw new Error("Palmier native controller returned no JSON verdict");
}

export async function runNativeCli(
  args: string[],
  signal?: AbortSignal,
  cliPath = DEFAULT_CLI,
  onEvent?: (event: NativeEvent) => void,
): Promise<Record<string, unknown>> {
  const result = await runCommand(pythonInterpreter(), [cliPath, ...args], {
    cwd: process.cwd(), env: { ...process.env }, timeoutMs: CLI_TIMEOUT_MS, signal,
    onStdoutLine: (line) => {
      const event = objectLine(line);
      if (event && event.status !== "candidate-staged") onEvent?.(event);
    },
  });
  let verdict: Record<string, unknown>;
  try { verdict = lastObject(result.stdout); } catch (error) {
    if (result.code === 0) throw error;
    throw new Error(result.stderr.trim() || `Palmier native controller exited ${result.code}`);
  }
  if (result.code !== 0 || verdict.ok !== true) {
    const detail = typeof verdict.error === "string" ? verdict.error : result.stderr.trim();
    throw new Error(detail || `Palmier native controller exited ${result.code}`);
  }
  return verdict;
}

export async function runLegacyNative(
  invocation: LegacyBrainInvocation,
  signal?: AbortSignal,
): Promise<BrainProcessResult> {
  const result = await runCommand(CLAUDE_BIN, invocation.args, {
    cwd: invocation.cwd,
    env: claudeProcessEnv(),
    timeoutMs: invocation.timeoutMs,
    signal,
  });
  if (result.code !== 0) {
    const detail = result.stderr.trim() ? `: ${result.stderr.trim().slice(-1_200)}` : "";
    throw new Error(`Claude exited ${result.code}${detail}`);
  }
  return {
    message: parseClaudeResultStream(result.stdout),
    stderr: result.stderr,
    ms: result.ms,
  };
}
