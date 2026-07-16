import { NextRequest } from "next/server";
import { spawn } from "child_process";
import { rmSync } from "fs";
import { claudeProcessEnv } from "../../_lib/ai-provider";
import { runCodex } from "../../_lib/codex-cli";
import {
  shouldDetachProcessGroup,
  terminateProcessTree,
  trackProcessTree,
} from "../../_lib/child-process-lifecycle";
import { dlog, derror } from "@/lib/debug";
import { REPO_ROOT } from "./doctrine";
import {
  beginSurgicalReview,
  finalizeSurgicalEdit,
  rollbackSurgicalEdit,
  type FinalizeSurgicalEditInput,
} from "./finalize";
import { buildAiEditPrompt } from "./prompt";
import { prepareSurgicalRequest, surgicalAuthorityFailure } from "./prepare";
import { guardProjectMutation, mutationProjectRoot } from "../../_lib/project-mutation";
import { planRefitEvent } from "../../_lib/plan-refit-transaction";
import {
  AI_EDIT_TIMEOUT_MS,
  buildAiEditInvocation,
  preparePlanForAi,
  type AiEditInvocation,
} from "./execution";
import { classifyPalmierWorkspace, maybePalmierNativeEdit } from "./palmier-native-stream";

export { buildAiEditPrompt } from "./prompt";
export { buildAiEditInvocation, claudeAiEditArgs } from "./execution";
export const maxDuration = 1800;
export const dynamic = "force-dynamic";

// Subscription-brain bridge. The legacy path keeps the local `claude` CLI;
// local-safe mode uses Codex with a workspace-write sandbox scoped to the job.
// Both edit only edit_plan.json; the user re-renders (assemble) to see the change.
const CLAUDE_BIN = process.env.CLAUDE_BIN || "claude";

type CodexInvocation = Extract<AiEditInvocation, { provider: "codex" }>;
type ClaudeInvocation = Extract<AiEditInvocation, { provider: "legacy" }>;

async function completeGovernedEdit(
  input: FinalizeSurgicalEditInput,
  send: (value: Record<string, unknown>) => void,
): Promise<void> {
  send({
    event: "surgical_review_started",
    lanes: input.scope.lanes,
    message: "Writer finished; running stored-intent, transcript/cut, hook, claims, lane lint, and fresh craft review.",
  });
  const result = await finalizeSurgicalEdit(input);
  if (result.refit) send(planRefitEvent(result.refit));
  send({
    event: "surgical_review",
    ok: true,
    lanes: input.scope.lanes,
    changedFields: result.changedFields,
    summary: result.review.summary,
  });
}

function codexAiEditStream(
  invocation: CodexInvocation,
  finalizer: FinalizeSurgicalEditInput,
  release: () => void,
): ReadableStream {
  const encoder = new TextEncoder();
  const abort = new AbortController();
  let cancelled = false;
  return new ReadableStream({
    start(controller) {
      const send = (value: Record<string, unknown>) => {
        try { controller.enqueue(encoder.encode(`data: ${JSON.stringify(value)}\n\n`)); } catch {}
      };
      const keepalive = setInterval(() => {
        try { controller.enqueue(encoder.encode(`: keepalive\n\n`)); } catch {}
      }, 10000);
      runCodex({
        ...invocation.options,
        signal: abort.signal,
        onEvent: (event) => send({ ...event, provider: "codex" }),
      })
        .then(async (result) => {
          dlog("producer:ai-edit", "codex closed", { ms: result.ms });
          await completeGovernedEdit(finalizer, send);
          send({ event: "ai_done", provider: "codex", ms: result.ms });
        })
        .catch((error: unknown) => {
          if (cancelled) return;
          rollbackSurgicalEdit(finalizer);
          derror("producer:ai-edit", "codex failed", error);
          const detail = error instanceof Error ? error.message : String(error);
          send({ event: "error", provider: "codex", message: `Governed edit rejected: ${detail}` });
        })
        .finally(() => {
          clearInterval(keepalive);
          release();
          try { controller.close(); } catch {}
        });
    },
    cancel() {
      cancelled = true;
      abort.abort();
      try { rollbackSurgicalEdit(finalizer); } finally { release(); }
    },
  });
}

function claudeAiEditStream(
  invocation: ClaudeInvocation,
  finalizer: FinalizeSurgicalEditInput,
  release: () => void,
): ReadableStream {
  const encoder = new TextEncoder();
  const skillsEnv = claudeProcessEnv();
  let active: ReturnType<typeof spawn> | undefined;
  let cancelled = false;
  return new ReadableStream({
    start(controller) {
      const send = (line: string) => {
        try { controller.enqueue(encoder.encode(`data: ${line}\n\n`)); } catch {}
      };
      const sendObject = (value: Record<string, unknown>) => send(JSON.stringify(value));
      sendObject({ event: "ai_model_selected", provider: "legacy", model: invocation.model });
      const proc = trackProcessTree(spawn(CLAUDE_BIN, invocation.args, {
        cwd: REPO_ROOT,
        env: skillsEnv,
        detached: shouldDetachProcessGroup(),
      }));
      active = proc;
      let buf = "";
      let errTail = "";
      let timedOut = false;
      const keepalive = setInterval(() => {
        try { controller.enqueue(encoder.encode(`: keepalive\n\n`)); } catch {}
      }, 10000);
      const timeout = setTimeout(() => {
        timedOut = true;
        terminateProcessTree(proc);
      }, AI_EDIT_TIMEOUT_MS);
      proc.stdout.on("data", (data: Buffer) => {
        buf += data.toString();
        const parts = buf.split("\n");
        buf = parts.pop() || "";
        for (const line of parts) if (line.trim()) send(line);
      });
      proc.stderr.on("data", (data: Buffer) => {
        errTail = (errTail + data.toString()).slice(-800);
      });
      proc.on("close", async (code) => {
        active = undefined;
        clearTimeout(timeout);
        if (cancelled) {
          clearInterval(keepalive);
          release();
          return;
        }
        if (buf.trim()) send(buf);
        dlog("producer:ai-edit", "claude closed", { code, model: invocation.model });
        try {
          if (timedOut) throw new Error(`Claude timed out after ${AI_EDIT_TIMEOUT_MS / 1000}s`);
          if (code !== 0) throw new Error(`Claude exited ${code}. ${errTail.slice(-400)}`);
          await completeGovernedEdit(finalizer, sendObject);
          sendObject({ event: "ai_done", provider: "legacy", model: invocation.model });
        } catch (error) {
          rollbackSurgicalEdit(finalizer);
          const detail = error instanceof Error ? error.message : String(error);
          sendObject({
            event: "error", provider: "legacy", model: invocation.model,
            message: `Governed edit rejected: ${detail}`,
          });
        } finally {
          clearInterval(keepalive);
          release();
          try { controller.close(); } catch {}
        }
      });
      proc.on("error", (error) => {
        active = undefined;
        clearTimeout(timeout);
        if (cancelled) {
          clearInterval(keepalive);
          release();
          return;
        }
        derror("producer:ai-edit", "claude spawn failed", error);
        rollbackSurgicalEdit(finalizer);
        clearInterval(keepalive);
        release();
        sendObject({
          event: "error", provider: "legacy", model: invocation.model, message: error.message,
        });
        try { controller.close(); } catch {}
      });
    },
    cancel() {
      cancelled = true;
      if (active) terminateProcessTree(active);
      try { rollbackSurgicalEdit(finalizer); } finally { release(); }
    },
  });
}

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  const native = await maybePalmierNativeEdit(body);
  if (native) return native;
  let prepared = prepareSurgicalRequest(body);
  if (prepared instanceof Response) return prepared;
  const guarded = guardProjectMutation({
    projectRoot: mutationProjectRoot(prepared.dir),
    producerDir: prepared.dir,
    operation: "applying an AI timeline change",
  });
  if (guarded.response) return guarded.response;
  let released = false;
  let stagingDir: string | undefined;
  const release = () => {
    if (released) return;
    released = true;
    if (stagingDir) rmSync(stagingDir, { recursive: true, force: true });
    guarded.lease.release();
  };
  // Re-read under the lease so the model never starts from a pre-lock plan.
  prepared = prepareSurgicalRequest(body);
  if (prepared instanceof Response) {
    release();
    return prepared;
  }
  const workspaceUnderLease = classifyPalmierWorkspace(prepared.dir);
  if (workspaceUnderLease.state !== "absent") {
    release();
    const detail = workspaceUnderLease.state === "invalid"
      ? workspaceUnderLease.error
      : "A managed Palmier workspace became canonical while this request was starting.";
    return json({ error: `${detail} Retry the request; no Sniper plan was changed.` }, 409);
  }
  const { dir, request, scope, planPath, plan, canvas,
    manifestPath, transcriptsDir, provider } = prepared;
  const authorityFailure = await surgicalAuthorityFailure(dir);
  if (authorityFailure) {
    release();
    return authorityFailure;
  }
  let candidate: ReturnType<typeof preparePlanForAi>;
  try {
    candidate = preparePlanForAi(planPath, plan);
    stagingDir = candidate.stagingDir;
  } catch (error) {
    release();
    return json({ error: `Could not stage this AI edit: ${(error as Error).message}` }, 500);
  }
  let invocation: AiEditInvocation;
  try {
    const prompt = buildAiEditPrompt(candidate.candidatePath, request, canvas, provider, scope);
    invocation = buildAiEditInvocation(provider, prompt, dir, candidate.candidatePath);
  } catch (error) {
    rmSync(candidate.candidatePath, { force: true });
    release();
    return json({ error: `AI provider configuration failed: ${(error as Error).message}` }, 500);
  }
  const finalizer: FinalizeSurgicalEditInput = {
    provider: invocation.provider,
    dir,
    planPath: candidate.candidatePath,
    authorityPlanPath: planPath,
    manifestPath,
    transcriptsDir,
    request,
    scope,
    originalPlanText: candidate.originalPlanText,
  };
  beginSurgicalReview(dir, scope);
  dlog("producer:ai-edit", `spawn ${invocation.label.toLowerCase()}`, {
    dir,
    request,
    snapshots: candidate.snapshots,
    provider: invocation.provider,
  });
  let stream: ReadableStream;
  try {
    stream = invocation.provider === "codex"
      ? codexAiEditStream(invocation, finalizer, release)
      : claudeAiEditStream(invocation, finalizer, release);
  } catch (error) {
    rollbackSurgicalEdit(finalizer);
    release();
    return json({ error: `Could not start this AI edit: ${(error as Error).message}` }, 500);
  }

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
      "X-Sniper-Edit-Mode": "plan",
    },
  });
}

function json(obj: unknown, status: number): Response {
  return new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
}
