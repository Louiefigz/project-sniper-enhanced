import { spawn } from "node:child_process";
import { claudeProcessEnv } from "../../_lib/ai-provider";
import { runCodex } from "../../_lib/codex-cli";
import { admitSubscriptionInvocation } from "../../_lib/subscription-invocation";
import {
  shouldDetachProcessGroup,
  terminateProcessTree,
  trackProcessTree,
} from "../../_lib/child-process-lifecycle";
import { derror, dlog } from "@/lib/debug";
import { REPO_ROOT } from "./doctrine";
import {
  rollbackSurgicalEdit,
  type FinalizeSurgicalEditInput,
} from "./finalize";
import {
  AI_EDIT_TIMEOUT_MS,
  type AiEditInvocation,
} from "./execution";
import { completeGovernedEdit } from "./complete";
import {
  createStreamCancellationFence,
  finishStream,
  type StreamCancellationFence,
} from "./stream-cancellation";
import { shouldPreservePromotionCandidate } from "./promotion-recovery";

const CLAUDE_BIN = process.env.CLAUDE_BIN || "claude";
type Release = (preserveStaging?: boolean) => void;
type CodexInvocation = Extract<AiEditInvocation, { provider: "codex" }>;
type ClaudeInvocation = Extract<AiEditInvocation, { provider: "legacy" }>;

interface StreamOutput {
  sendLine: (line: string) => void;
  sendObject: (value: Record<string, unknown>) => void;
  close: () => void;
}

interface StreamContext<T extends AiEditInvocation> {
  invocation: T;
  finalizer: FinalizeSurgicalEditInput;
  release: Release;
  fence: StreamCancellationFence;
}

function streamOutput(controller: ReadableStreamDefaultController): StreamOutput {
  const encoder = new TextEncoder();
  const sendLine = (line: string) => {
    try { controller.enqueue(encoder.encode(`data: ${line}\n\n`)); } catch {}
  };
  return {
    sendLine,
    sendObject: (value) => sendLine(JSON.stringify(value)),
    close: () => { try { controller.close(); } catch {} },
  };
}

function keepalive(controller: ReadableStreamDefaultController): NodeJS.Timeout {
  const encoder = new TextEncoder();
  return setInterval(() => {
    try { controller.enqueue(encoder.encode(": keepalive\n\n")); } catch {}
  }, 10_000);
}

function rollbackFailure(finalizer: FinalizeSurgicalEditInput): unknown {
  try {
    rollbackSurgicalEdit(finalizer);
    return undefined;
  } catch (error) {
    return error;
  }
}

function finish(
  context: StreamContext<AiEditInvocation>,
  output: StreamOutput,
  timer: NodeJS.Timeout,
  rollback = false,
): void {
  clearInterval(timer);
  const failure = finishStream(
    context.fence,
    () => context.release(shouldPreservePromotionCandidate(context.finalizer)),
    output.close,
    rollback ? () => rollbackSurgicalEdit(context.finalizer) : undefined,
  );
  if (failure) derror("producer:ai-edit", "stream cleanup failed", failure);
}

function codexAiEditStream(
  invocation: CodexInvocation,
  finalizer: FinalizeSurgicalEditInput,
  release: Release,
): ReadableStream {
  const fence = createStreamCancellationFence();
  const context = { invocation, finalizer, release, fence };
  finalizer.signal = fence.signal;
  return new ReadableStream({
    start(controller) {
      const output = streamOutput(controller);
      const timer = keepalive(controller);
      runCodex({
        ...invocation.options,
        signal: fence.signal,
        onEvent: (event) => output.sendObject({ ...event, provider: "codex" }),
      }).then(async (result) => {
        dlog("producer:ai-edit", "codex closed", { ms: result.ms });
        await completeGovernedEdit(finalizer, output.sendObject);
        output.sendObject({ event: "ai_done", provider: "codex", ms: result.ms });
      }).catch((error: unknown) => {
        const recovery = rollbackFailure(finalizer);
        if (fence.isCancelled()) return;
        derror("producer:ai-edit", "codex failed", recovery ?? error);
        const detail = recovery ?? error;
        output.sendObject({
          event: "error", provider: "codex",
          message: `Governed edit rejected: ${detail instanceof Error ? detail.message : String(detail)}`,
        });
      }).finally(() => finish(context, output, timer));
    },
    cancel() {
      fence.cancel();
      return fence.wait;
    },
  });
}

interface ClaudeRuntime {
  started: number;
  active?: ReturnType<typeof spawn>;
  buffer: string;
  errorTail: string;
  timedOut: boolean;
  terminalHandled: boolean;
  keepalive: NodeJS.Timeout;
  timeout: NodeJS.Timeout;
}

interface ClaudeContext extends StreamContext<ClaudeInvocation> {
  output: StreamOutput;
  runtime: ClaudeRuntime;
}

async function handleClaudeClose(
  context: ClaudeContext,
  code: number | null,
): Promise<void> {
  const { fence, finalizer, invocation, output, runtime } = context;
  if (runtime.terminalHandled) return;
  runtime.terminalHandled = true;
  runtime.active = undefined;
  clearTimeout(runtime.timeout);
  if (fence.isCancelled()) {
    finish(context, output, runtime.keepalive, true);
    return;
  }
  if (runtime.buffer.trim()) output.sendLine(runtime.buffer);
  dlog("producer:ai-edit", "claude closed", { code, model: invocation.model });
  let failed = false;
  try {
    if (runtime.timedOut) throw new Error(`Claude timed out after ${AI_EDIT_TIMEOUT_MS / 1000}s`);
    if (code !== 0) throw new Error(`Claude exited ${code}. ${runtime.errorTail.slice(-400)}`);
    await completeGovernedEdit(finalizer, output.sendObject);
    output.sendObject({ event: "ai_done", provider: "legacy", model: invocation.model });
  } catch (error) {
    failed = true;
    if (!fence.isCancelled()) output.sendObject({
      event: "error", provider: "legacy", model: invocation.model,
      message: `Governed edit rejected: ${error instanceof Error ? error.message : String(error)}`,
    });
  } finally {
    finish(context, output, runtime.keepalive, failed);
  }
}

function handleClaudeError(context: ClaudeContext, error: Error): void {
  const { fence, invocation, output, runtime } = context;
  if (runtime.terminalHandled) return;
  runtime.terminalHandled = true;
  runtime.active = undefined;
  clearTimeout(runtime.timeout);
  if (!fence.isCancelled()) {
    derror("producer:ai-edit", "claude spawn failed", error);
    output.sendObject({
      event: "error", provider: "legacy", model: invocation.model,
      message: error.message,
    });
  }
  finish(context, output, runtime.keepalive, true);
}

async function startClaude(context: ClaudeContext): Promise<void> {
  const { invocation, output, runtime } = context;
  const admitted = await admitSubscriptionInvocation({ provider: "claude", bin: CLAUDE_BIN,
    args: invocation.args, cwd: REPO_ROOT, env: claudeProcessEnv(), signal: context.fence.signal,
    timeoutMs: AI_EDIT_TIMEOUT_MS - (performance.now() - runtime.started) });
  admitted.remainingMs();
  if (runtime.timedOut || runtime.terminalHandled) throw new Error("Claude edit expired before inference");
  output.sendObject({
    event: "ai_model_selected", provider: "legacy", model: invocation.model,
  });
  const proc = trackProcessTree(spawn(admitted.bin, admitted.args, {
    cwd: admitted.cwd,
    env: admitted.env,
    detached: shouldDetachProcessGroup(),
  }));
  runtime.active = proc;
  proc.stdout.on("data", (data: Buffer) => {
    runtime.buffer += data.toString();
    const parts = runtime.buffer.split("\n");
    runtime.buffer = parts.pop() || "";
    for (const line of parts) if (line.trim()) output.sendLine(line);
  });
  proc.stderr.on("data", (data: Buffer) => {
    runtime.errorTail = (runtime.errorTail + data.toString()).slice(-800);
  });
  proc.on("close", (code) => void handleClaudeClose(context, code));
  proc.on("error", (error) => handleClaudeError(context, error));
}

function claudeAiEditStream(
  invocation: ClaudeInvocation,
  finalizer: FinalizeSurgicalEditInput,
  release: Release,
): ReadableStream {
  const fence = createStreamCancellationFence();
  finalizer.signal = fence.signal;
  let runtime: ClaudeRuntime | undefined;
  return new ReadableStream({
    start(controller) {
      runtime = {
        started: performance.now(),
        buffer: "", errorTail: "", timedOut: false, terminalHandled: false,
        keepalive: keepalive(controller),
        timeout: setTimeout(() => {
          if (!runtime) return;
          runtime.timedOut = true;
          if (runtime.active) terminateProcessTree(runtime.active);
        }, AI_EDIT_TIMEOUT_MS),
      };
      const context = {
        invocation, finalizer, release, fence,
        output: streamOutput(controller), runtime,
      };
      void startClaude(context).catch((error) => {
        handleClaudeError(
          context,
          error instanceof Error ? error : new Error(String(error)),
        );
      });
    },
    cancel() {
      fence.cancel();
      if (runtime?.active) terminateProcessTree(runtime.active);
      return fence.wait;
    },
  });
}

export function createAiEditStream(
  invocation: AiEditInvocation,
  finalizer: FinalizeSurgicalEditInput,
  release: Release,
): ReadableStream {
  return invocation.provider === "codex"
    ? codexAiEditStream(invocation, finalizer, release)
    : claudeAiEditStream(invocation, finalizer, release);
}
