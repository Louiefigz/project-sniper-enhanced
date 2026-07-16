import { spawn } from "child_process";
import path from "path";
import readline from "readline";
import {
  codexProcessEnv,
  codexReasoningLevel,
  codexSettings,
  type CodexReasoningLevel,
} from "./ai-provider";
import {
  PROCESS_TERM_GRACE_MS,
  shouldDetachProcessGroup,
  terminateProcessTree,
  trackProcessTree,
} from "./child-process-lifecycle";

export type CodexSchema =
  | "segmenter"
  | "clipper-decisions"
  | "clipper-validation"
  | "palmier-mutation-plan"
  | "producer-review"
  | "producer-revision";

export interface CodexRunOptions {
  prompt: string;
  sandbox: "read-only" | "workspace-write";
  timeoutMs: number;
  /** Override the global effort for this bounded invocation only. */
  reasoning?: CodexReasoningLevel;
  cwd?: string;
  schema?: CodexSchema;
  addDirs?: string[];
  /** Remove every local/external inspection tool for evidence embedded in the prompt. */
  tools?: "default" | "none";
  onEvent?: (event: Record<string, unknown>) => void;
  signal?: AbortSignal;
}

export interface CodexRunResult {
  message: string;
  stderr: string;
  ms: number;
}

const SCHEMAS: Record<CodexSchema, string> = {
  segmenter: "segmenter.schema.json",
  "clipper-decisions": "clipper-decisions.schema.json",
  "clipper-validation": "clipper-validation.schema.json",
  "palmier-mutation-plan": "palmier-mutation-plan.schema.json",
  "producer-review": "producer-review.schema.json",
  "producer-revision": "producer-revision.schema.json",
};

const MAX_STDERR_CHARS = 8_000;
const NO_TOOL_FEATURES = [
  "shell_tool",
  "unified_exec",
  "code_mode_host",
  "computer_use",
  "browser_use",
  "browser_use_external",
  "browser_use_full_cdp_access",
  "in_app_browser",
  "workspace_dependencies",
  "image_generation",
] as const;

function configValue(value: string): string {
  return JSON.stringify(value);
}

export function buildCodexArgs(options: Omit<CodexRunOptions, "prompt" | "onEvent">): string[] {
  const settings = codexSettings();
  const reasoning = options.reasoning === undefined
    ? settings.reasoning
    : codexReasoningLevel(options.reasoning);
  const toolArgs = options.tools === "none"
    ? NO_TOOL_FEATURES.flatMap((feature) => ["--disable", feature]) : [];
  const args = [
    "--ask-for-approval", "never",
    ...toolArgs,
    "exec",
    "--skip-git-repo-check",
    "--ignore-user-config",
    "--ignore-rules",
    "--ephemeral",
    "--strict-config",
    "--model", settings.model,
    "-c", `model_reasoning_effort=${configValue(reasoning)}`,
    "-c", 'web_search="disabled"',
    "-c", "features.apps=false",
    "-c", "features.hooks=false",
    "-c", "features.multi_agent=false",
    "--sandbox", options.sandbox,
    "--json",
  ];
  for (const dir of options.addDirs ?? []) args.push("--add-dir", dir);
  if (options.schema) {
    args.push("--output-schema", path.join(process.cwd(), "schemas", "codex", SCHEMAS[options.schema]));
  }
  args.push("-");
  return args;
}

export function agentMessage(event: Record<string, unknown>): string | null {
  if (event.type === "result" && typeof event.result === "string") return event.result;
  const item = event.item as Record<string, unknown> | undefined;
  if (event.type !== "item.completed" || item?.type !== "agent_message") return null;
  return typeof item.text === "string" ? item.text : null;
}

function codexError(code: number | null, stderr: string, message: string): Error {
  const detail = stderr.trim().slice(-1_200);
  if (code === 0 && !message) return new Error("Codex exited without a final agent message");
  return new Error(`Codex exited ${code ?? "without a status"}${detail ? `: ${detail}` : ""}`);
}

export function runCodex(options: CodexRunOptions): Promise<CodexRunResult> {
  return new Promise((resolve, reject) => {
    const settings = codexSettings();
    const started = Date.now();
    const proc = trackProcessTree(spawn(settings.bin, buildCodexArgs(options), {
      cwd: options.cwd ?? process.cwd(),
      env: codexProcessEnv(),
      stdio: ["pipe", "pipe", "pipe"],
      detached: shouldDetachProcessGroup(),
    }));
    let message = "";
    let stderr = "";
    let settled = false;
    let stopError: Error | undefined;
    let forceSettle: ReturnType<typeof setTimeout> | undefined;
    const abort = () => {
      requestStop(new Error("Codex run was cancelled"));
    };
    const lines = readline.createInterface({ input: proc.stdout });
    const finish = (error?: Error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (forceSettle) clearTimeout(forceSettle);
      options.signal?.removeEventListener("abort", abort);
      lines.close();
      if (error) reject(error);
      else resolve({ message, stderr, ms: Date.now() - started });
    };
    const requestStop = (error: Error) => {
      if (settled || stopError) return;
      stopError = error;
      terminateProcessTree(proc);
      forceSettle = setTimeout(() => finish(error), PROCESS_TERM_GRACE_MS + 1_000);
    };
    lines.on("line", (line) => {
      if (!line.trim()) return;
      try {
        const event = JSON.parse(line) as Record<string, unknown>;
        options.onEvent?.(event);
        message = agentMessage(event) ?? message;
      } catch {
        options.onEvent?.({ type: "raw", line: line.slice(0, 2_000) });
      }
    });
    proc.stderr.on("data", (data: Buffer) => {
      stderr = (stderr + data.toString()).slice(-MAX_STDERR_CHARS);
    });
    proc.on("error", (error) => finish(stopError ?? error));
    proc.on("close", (code) => {
      if (stopError) return finish(stopError);
      if (code !== 0 || !message) finish(codexError(code, stderr, message));
      else finish();
    });
    const timer = setTimeout(() => {
      requestStop(new Error(`Codex timed out after ${Math.round(options.timeoutMs / 1_000)}s`));
    }, options.timeoutMs);
    options.signal?.addEventListener("abort", abort, { once: true });
    if (options.signal?.aborted) abort();
    proc.stdin.on("error", (error) => finish(stopError ?? error));
    if (!settled) proc.stdin.end(options.prompt);
  });
}

export async function runCodexJson<T>(options: Omit<CodexRunOptions, "sandbox">): Promise<T> {
  const result = await runCodex({ ...options, sandbox: "read-only" });
  try {
    return JSON.parse(result.message) as T;
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`Codex returned invalid structured JSON: ${detail}`);
  }
}
