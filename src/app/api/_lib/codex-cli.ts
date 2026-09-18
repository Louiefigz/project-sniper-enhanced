import { spawn } from "child_process";
import path from "path";
import readline from "readline";
import { providerMediaJail } from "./provider-media-jail";
import { admitSubscriptionInvocation } from "./subscription-invocation";
import { CODEX_SUBSCRIPTION_CONFIG } from "./subscription-policy";
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
  | "producer-revision"
  | "producer-treatment-proposal"
  | "producer-treatment-proposal-v3"
  | "producer-treatment-proposal-v4"
  | "producer-treatment-proposal-v5"
  | "producer-treatment-proposal-v6"
  | "producer-treatment-proposal-v7"
  | "producer-treatment-proposal-v8"
  | "producer-treatment-proposal-v9"
  | "producer-treatment-proposal-v10"
  | "producer-native-director"
  | "producer-native-director-review"
  | "producer-proposal-readiness";

export interface CodexRunOptions {
  prompt: string;
  sandbox: "read-only" | "workspace-write";
  timeoutMs: number;
  /** Override the global effort for this bounded invocation only. */
  reasoning?: CodexReasoningLevel;
  cwd?: string;
  schema?: CodexSchema;
  addDirs?: string[];
  /** Explicit controller-owned frozen image attachments, separate from filesystem tool access. */
  imagePaths?: string[];
  /** Remove every local/external inspection tool for evidence embedded in the prompt. */
  tools?: "default" | "none";
  onEvent?: (event: Record<string, unknown>) => void;
  signal?: AbortSignal;
  /** Optional aggregate stdout+stderr byte budget; never truncate a successful result. */
  maxOutputBytes?: number;
  /** Run under the OS media boundary (provider-media-jail.ts); requires tools "none". */
  jail?: boolean;
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
  "producer-treatment-proposal": "../producer/treatment-proposal-v2.schema.json",
  "producer-treatment-proposal-v3": "../producer/treatment-proposal-v3.schema.json",
  "producer-treatment-proposal-v4": "../producer/treatment-proposal-v4.schema.json",
  "producer-treatment-proposal-v5": "../producer/treatment-proposal-v5.schema.json",
  "producer-treatment-proposal-v6": "../producer/treatment-proposal-v6.schema.json",
  "producer-treatment-proposal-v7": "../producer/treatment-proposal-v7.schema.json",
  "producer-treatment-proposal-v8": "../producer/treatment-proposal-v8.schema.json",
  "producer-treatment-proposal-v9": "../producer/treatment-proposal-v9.schema.json",
  "producer-treatment-proposal-v10": "../producer/treatment-proposal-v10.schema.json",
  "producer-native-director": "../producer/native-director-v1.schema.json",
  "producer-native-director-review": "../producer/native-director-review-v1.schema.json",
  "producer-proposal-readiness": "../producer/proposal-readiness-v1.schema.json",
};

const MAX_STDERR_CHARS = 8_000;
/** Per-call bound on controller-owned image attachments (frames or labelled contact sheets). */
export const MAX_IMAGE_ATTACHMENTS = 24;
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
    ...CODEX_SUBSCRIPTION_CONFIG,
    "-c", 'model_provider="openai"',
    "-c", `model_reasoning_effort=${configValue(reasoning)}`,
    "-c", 'web_search="disabled"',
    "-c", "features.apps=false",
    "-c", "features.hooks=false",
    "-c", "features.multi_agent=false",
    "--sandbox", options.sandbox,
    "--json",
  ];
  for (const dir of options.addDirs ?? []) args.push("--add-dir", dir);
  if ((options.imagePaths?.length ?? 0) > MAX_IMAGE_ATTACHMENTS) throw new Error("Codex image attachments exceed the evidence bound");
  for (const image of options.imagePaths ?? []) {
    if (!path.isAbsolute(image) || image.includes("\0")) throw new Error("Codex image attachments need absolute controller-owned paths");
    args.push("--image", image);
  }
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

/** The provider's own failure text from a `--json` event (usage limit, auth, model). */
export function codexEventError(event: Record<string, unknown>): string | null {
  if (event.type === "error" && typeof event.message === "string") return event.message;
  const error = event.error as Record<string, unknown> | undefined;
  if (event.type === "turn.failed" && typeof error?.message === "string") return error.message;
  return null;
}

function codexError(code: number | null, stderr: string, message: string, reported = ""): Error {
  const detail = stderr.trim().slice(-1_200);
  if (code === 0 && !message && !reported) return new Error("Codex exited without a final agent message");
  // Codex reports the reason for a failed turn on stdout; stderr often holds only
  // unrelated log lines, so the reported reason leads.
  const reason = reported ? `: Codex reported: ${reported.slice(0, 600)}` : "";
  return new Error(`Codex exited ${code ?? "without a status"}${reason}${detail ? `${reason ? " | " : ": "}${detail}` : ""}`);
}

export async function runCodex(options: CodexRunOptions): Promise<CodexRunResult> {
  if (options.maxOutputBytes !== undefined && (!Number.isSafeInteger(options.maxOutputBytes)
      || options.maxOutputBytes < 1 || options.maxOutputBytes > 16 * 1024 * 1024)) {
    throw new Error("Codex output budget is invalid");
  }
  if (options.jail && options.tools !== "none") {
    throw new Error("The provider media boundary applies only to tool-less Codex runs");
  }
  const settings = codexSettings();
  const admitted = await admitSubscriptionInvocation({ provider: "codex", bin: settings.bin,
    args: buildCodexArgs(options), cwd: options.cwd ?? process.cwd(), env: codexProcessEnv(),
    timeoutMs: options.timeoutMs, signal: options.signal });
  const command = options.jail ? providerMediaJail(admitted.bin, admitted.args)
    : { bin: admitted.bin, args: [...admitted.args] };
  return new Promise((resolve, reject) => {
    const timeoutMs = admitted.remainingMs();
    const proc = trackProcessTree(spawn(command.bin, command.args, {
      cwd: admitted.cwd,
      env: admitted.env,
      stdio: ["pipe", "pipe", "pipe"],
      detached: shouldDetachProcessGroup(),
    }));
    let message = "";
    let stderr = "";
    let reported = "";
    let settled = false;
    let stopError: Error | undefined;
    let outputBytes = 0;
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
      else resolve({ message, stderr, ms: admitted.elapsedMs() });
    };
    const requestStop = (error: Error) => {
      if (settled || stopError) return;
      stopError = error;
      terminateProcessTree(proc);
      forceSettle = setTimeout(() => finish(error), PROCESS_TERM_GRACE_MS + 1_000);
    };
    const countOutput = (data: Buffer) => {
      if (options.maxOutputBytes === undefined || stopError) return;
      outputBytes += data.length;
      if (outputBytes <= options.maxOutputBytes) return;
      lines.close(); proc.stdout.pause();
      requestStop(new Error(`Codex exceeded its ${options.maxOutputBytes}-byte output budget`));
    };
    proc.stdout.prependListener("data", countOutput);
    proc.stderr.prependListener("data", countOutput);
    lines.on("line", (line) => {
      if (stopError) return;
      if (!line.trim()) return;
      try {
        const event = JSON.parse(line) as Record<string, unknown>;
        options.onEvent?.(event);
        message = agentMessage(event) ?? message;
        reported = codexEventError(event) ?? reported;
      } catch {
        options.onEvent?.({ type: "raw", line: line.slice(0, 2_000) });
      }
    });
    proc.stderr.on("data", (data: Buffer) => {
      if (stopError) return;
      stderr = (stderr + data.toString()).slice(-MAX_STDERR_CHARS);
    });
    proc.on("error", (error) => finish(stopError ?? error));
    proc.on("close", (code) => {
      if (stopError) return finish(stopError);
      if (code !== 0 || !message) finish(codexError(code, stderr, message, reported));
      else finish();
    });
    const timer = setTimeout(() => {
      requestStop(new Error(`Codex timed out after ${Math.round(options.timeoutMs / 1_000)}s`));
    }, timeoutMs);
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
