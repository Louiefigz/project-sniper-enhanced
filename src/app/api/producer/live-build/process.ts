import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { claudeProcessEnv } from "../../_lib/ai-provider";
import { admitSubscriptionInvocation, type AdmittedSubscriptionInvocation } from "../../_lib/subscription-invocation";
import {
  PROCESS_TERM_GRACE_MS,
  shouldDetachProcessGroup,
  terminateProcessTree,
  trackProcessTree,
} from "../../_lib/child-process-lifecycle";
import {
  palmierOpEvents,
  type PalmierOpEvent,
} from "@/lib/producer/palmier-op-event";

const CLAUDE_BIN = process.env.CLAUDE_BIN || "claude";
const TIMEOUT_MS = 30 * 60 * 1000;
const MUTATION_TOOLS = new Set([
  "add_clips", "insert_clips", "split_clips", "move_clips", "remove_clips",
  "ripple_delete_ranges", "set_clip_properties", "set_keyframes",
  "add_texts", "update_text", "add_captions", "apply_color",
  "apply_effect", "apply_layout", "manage_tracks", "sync_clips",
  "remove_silence", "remove_words", "denoise_audio",
]);

export function isLiveBuildMutationTool(tool: string): boolean {
  return MUTATION_TOOLS.has(tool);
}

export interface LiveBuildProcessResult {
  elapsedMs: number;
  firstMutationMs: number;
  operationsSeen: number;
  operationsCompleted: number;
  sessionId: string;
  result: string;
}

export interface ProcessInput {
  args: string[];
  cwd: string;
  expectedSessionId: string;
  signal?: AbortSignal;
  onEvent: (event: PalmierOpEvent) => void;
  onSession?: (sessionId: string) => void;
}

type Resolve = (result: LiveBuildProcessResult) => void;
type Reject = (error: Error) => void;

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}

function blocks(value: Record<string, unknown>): Record<string, unknown>[] {
  const content = record(value.message).content;
  return Array.isArray(content)
    ? content.filter((item): item is Record<string, unknown> =>
      Boolean(item && typeof item === "object" && !Array.isArray(item))) : [];
}

function parseLine(line: string): Record<string, unknown> | null {
  try {
    const value: unknown = JSON.parse(line);
    return Object.keys(record(value)).length ? record(value) : null;
  } catch { return null; }
}

export class ProofTracker {
  private skillInvoked = false;
  private timelineRead = false;
  private finalResult = "";
  private firstMutationMs = 0;
  private sessionId = "";
  private tools = new Map<string, string>();
  private mutations = new Set<string>();
  private completed = new Set<string>();
  private failed = new Set<string>();

  constructor(private input: ProcessInput, private started: number) {}

  consume(value: Record<string, unknown>): void {
    if (typeof value.session_id === "string") {
      this.sessionId = value.session_id;
      this.input.onSession?.(this.sessionId);
    }
    if (value.type === "result" && typeof value.result === "string") {
      this.finalResult = value.result;
    }
    for (const block of blocks(value)) {
      const name = typeof block.name === "string" ? block.name : "";
      if (block.type === "tool_use" && name === "Skill"
          && record(block.input).skill === "producer") this.skillInvoked = true;
    }
    for (const event of palmierOpEvents(value, Date.now() - this.started)) {
      this.trackOperation(event);
      this.input.onEvent(event);
    }
  }

  private trackOperation(event: PalmierOpEvent): void {
    if (event.event === "palmier_op" && event.tool) {
      this.tools.set(event.operationId, event.tool);
      if (isLiveBuildMutationTool(event.tool)) {
        this.mutations.add(event.operationId);
      }
      if (event.tool === "get_timeline") this.timelineRead = true;
      return;
    }
    const tool = this.tools.get(event.operationId);
    if (!tool || !isLiveBuildMutationTool(tool)) return;
    if (event.status === "applied") {
      this.completed.add(event.operationId);
      this.firstMutationMs ||= event.elapsedMs;
    } else this.failed.add(event.operationId);
  }

  result(): LiveBuildProcessResult {
    const seen = this.mutations.size;
    const completed = this.completed.size;
    const failed = this.failed.size;
    const exactLifecycle = completed === seen
      && [...this.completed].every((id) => this.mutations.has(id));
    if (!this.skillInvoked || !this.timelineRead || completed < 1
        || failed > 0 || !exactLifecycle
        || this.sessionId !== this.input.expectedSessionId) {
      throw new Error(`Live build proof failed (skill=${this.skillInvoked}, readback=${this.timelineRead}, seen=${seen}, applied=${completed}, failed=${failed}, unresolved=${seen - completed}, session=${this.sessionId || "missing"}).`);
    }
    return { elapsedMs: Date.now() - this.started,
      firstMutationMs: this.firstMutationMs, operationsSeen: seen,
      operationsCompleted: completed, sessionId: this.sessionId,
      result: this.finalResult };
  }
}

class LiveProcessRunner {
  private child: ChildProcessWithoutNullStreams;
  private proof: ProofTracker;
  private pending = "";
  private stderr = "";
  private settled = false;
  private stopError?: Error;
  private timer?: ReturnType<typeof setTimeout>;
  private forced?: ReturnType<typeof setTimeout>;
  private timeoutMs: number;

  constructor(private input: ProcessInput, private resolve: Resolve,
    private reject: Reject, private admitted: AdmittedSubscriptionInvocation) {
    this.timeoutMs = admitted.remainingMs();
    this.child = trackProcessTree(spawn(admitted.bin, admitted.args, {
      cwd: admitted.cwd, env: admitted.env,
      detached: shouldDetachProcessGroup(),
    }));
    this.proof = new ProofTracker(input, Date.now() - admitted.elapsedMs());
  }

  start(): void {
    this.child.stdout.on("data", (data: Buffer) => this.push(data.toString()));
    this.child.stderr.on("data", (data: Buffer) => {
      this.stderr = (this.stderr + data.toString()).slice(-4_000);
    });
    this.child.on("error", (error) => this.finish(this.stopError ?? error));
    this.child.on("close", (code) => this.close(code));
    this.timer = setTimeout(() => this.stop(new Error("Palmier live build timed out.")), this.timeoutMs);
    this.input.signal?.addEventListener("abort", this.abort, { once: true });
    if (this.input.signal?.aborted) this.abort();
  }

  private push(text: string): void {
    this.pending += text;
    const lines = this.pending.split("\n");
    this.pending = lines.pop() ?? "";
    for (const line of lines) {
      const value = parseLine(line);
      if (value && !this.consume(value)) return;
    }
  }

  private close(code: number | null): void {
    const value = parseLine(this.pending);
    if (value && !this.consume(value)) return;
    if (this.stopError) return this.finish(this.stopError);
    if (code !== 0) return this.finish(new Error(
      `Claude live build exited ${code}: ${this.stderr || "no diagnostic output"}`,
    ));
    this.finish();
  }

  private consume(value: Record<string, unknown>): boolean {
    try {
      this.proof.consume(value);
      return true;
    } catch (reason) {
      this.stop(
        reason instanceof Error ? reason : new Error(String(reason)));
      return false;
    }
  }

  private finish(error?: Error): void {
    if (this.settled) return;
    this.settled = true;
    if (this.timer) clearTimeout(this.timer);
    if (this.forced) clearTimeout(this.forced);
    this.input.signal?.removeEventListener("abort", this.abort);
    if (error) return this.reject(error);
    try { this.resolve(this.proof.result()); } catch (reason) {
      this.reject(reason instanceof Error ? reason : new Error(String(reason)));
    }
  }

  private stop(error: Error): void {
    if (this.settled || this.stopError) return;
    this.stopError = error;
    terminateProcessTree(this.child);
    this.forced = setTimeout(() => this.finish(error), PROCESS_TERM_GRACE_MS + 1_000);
  }

  private abort = () => this.stop(new Error(
    "Palmier live build was stopped; its candidate checkpoint is preserved.",
  ));
}

/** Spawn the exact smoke-proved Claude session and stream direct MCP operations. */
export async function runLiveBuildProcess(input: ProcessInput): Promise<LiveBuildProcessResult> {
  const admitted = await admitSubscriptionInvocation({ provider: "claude", bin: CLAUDE_BIN,
    args: input.args, cwd: input.cwd, env: claudeProcessEnv(), timeoutMs: TIMEOUT_MS, signal: input.signal });
  return new Promise((resolve, reject) => {
    new LiveProcessRunner(input, resolve, reject, admitted).start();
  });
}
