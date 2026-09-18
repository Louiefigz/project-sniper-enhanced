import {
  guardProjectMutation,
  mutationProjectRoot,
  type ProjectMutationGuard,
} from "../../_lib/project-mutation";
import { validateRequestedSurgicalEditScope } from "@/lib/producer/surgical-edit";
import {
  runPalmierNativeEdit,
  type PalmierNativeRunOptions,
} from "./palmier-native-runner";
import type { PalmierNativePromptInput } from "./palmier-native-prompt";
import type { PalmierNativeResult } from "./palmier-native-contract";
import { palmierNativeCapabilityFailure } from "./palmier-native-capabilities";
import {
  classifyPalmierWorkspace,
  type PalmierWorkspaceClassification,
} from "./palmier-workspace-classification";
export {
  classifyPalmierWorkspace,
  type PalmierWorkspaceClassification,
} from "./palmier-workspace-classification";

const UNSUPPORTED = new Set(["broll", "music"]);

type NativeRun = (
  input: PalmierNativePromptInput,
  options: PalmierNativeRunOptions,
) => Promise<PalmierNativeResult>;

export interface PalmierNativeStreamDependencies {
  classifyWorkspace?: (dir: string) => PalmierWorkspaceClassification;
  guard?: (input: {
    projectRoot: string;
    producerDir: string;
    operation: string;
  }) => ProjectMutationGuard;
  run?: NativeRun;
}

function json(value: unknown, status: number): Response {
  return new Response(JSON.stringify(value), {
    status, headers: { "Content-Type": "application/json" },
  });
}

function inputDir(body: unknown): string {
  if (!body || typeof body !== "object" || Array.isArray(body)) return "";
  const value = (body as Record<string, unknown>).dir;
  return typeof value === "string" ? value.replace(/\/$/, "") : "";
}

function prepareNativeRequest(body: unknown): PalmierNativePromptInput | Response {
  const row = body && typeof body === "object" && !Array.isArray(body)
    ? body as Record<string, unknown>
    : {};
  const dir = inputDir(body);
  const request = typeof row.request === "string" ? row.request.trim() : "";
  if (!dir || !request) return json({ error: "Missing dir or request" }, 400);
  try {
    return { dir, request, scope: validateRequestedSurgicalEditScope(request, row.scope) };
  } catch (error) {
    return json({
      error: "Choose a specific edit lane (cuts, graphics, motion, captions, b-roll, audio, music, or reframe): "
        + (error as Error).message,
    }, 422);
  }
}

function once(action: () => void): () => void {
  let called = false;
  return () => {
    if (called) return;
    called = true;
    action();
  };
}

export function nativeStream(
  input: PalmierNativePromptInput,
  release: () => void,
  run: NativeRun = (value, options) => runPalmierNativeEdit(value, {}, options),
): ReadableStream {
  const encoder = new TextEncoder();
  const abort = new AbortController();
  const releaseOnce = once(release);
  let cancelled = false;
  let completion: Promise<void> | undefined;
  return new ReadableStream({
    start(controller) {
      const send = (value: Record<string, unknown>) => {
        if (cancelled) return;
        try { controller.enqueue(encoder.encode(`data: ${JSON.stringify(value)}\n\n`)); } catch {}
      };
      const keepalive = setInterval(() => {
        if (cancelled) return;
        try { controller.enqueue(encoder.encode(": keepalive\n\n")); } catch {}
      }, 10_000);
      send({
        event: "palmier_native_started",
        message: "Reading the current Palmier working head and planning a non-destructive candidate.",
      });
      completion = Promise.resolve()
        .then(() => run(input, { signal: abort.signal, onEvent: send }))
        .then((result) => {
          send({
            event: "palmier_candidate_ready",
            mode: "palmier-native",
            timelineId: result.timelineId,
            fingerprint: result.fingerprint,
            operationCount: result.operationCount,
            message: "Review-only candidate created; the verified parent was restored. Review it, then run candidate QC before any deliberate promotion.",
          });
          send({ event: "ai_done", mode: "palmier-native" });
        })
        .catch((error: unknown) => send({
          event: "error",
          mode: "palmier-native",
          message: error instanceof Error ? error.message : String(error),
        }))
        .finally(() => {
          clearInterval(keepalive);
          releaseOnce();
          if (!cancelled) try { controller.close(); } catch {}
        });
    },
    cancel() {
      cancelled = true;
      abort.abort();
      return completion;
    },
  });
}

/** Route to Palmier-native work whenever a valid managed working head exists. */
export async function maybePalmierNativeEdit(
  body: unknown,
  dependencies: PalmierNativeStreamDependencies = {},
): Promise<Response | null> {
  const dir = inputDir(body);
  if (!dir) return null;
  const workspace = (dependencies.classifyWorkspace ?? classifyPalmierWorkspace)(dir);
  if (workspace.state === "absent") return null;
  if (workspace.state === "invalid") {
    return json({
      error: `${workspace.error} Refusing to fall back to an older Sniper plan.`,
      code: "PALMIER_MANAGED_STATE_INVALID",
    }, 409);
  }
  const prepared = prepareNativeRequest(body);
  if (prepared instanceof Response) return prepared;
  const unsupported = prepared.scope.lanes.filter((lane) => UNSUPPORTED.has(lane));
  if (unsupported.length) {
    return json({
      error: `Palmier-native ${unsupported.join(" + ")} edits are not connected yet. `
        + "The current Palmier timeline was preserved; add/import the asset manually, then retry a supported edit.",
      code: "PALMIER_NATIVE_LANE_UNSUPPORTED",
    }, 409);
  }
  const capability = palmierNativeCapabilityFailure(prepared);
  if (capability) {
    return json({ error: capability.message, code: capability.code }, 409);
  }
  const guarded = (dependencies.guard ?? guardProjectMutation)({
    projectRoot: mutationProjectRoot(prepared.dir),
    producerDir: prepared.dir,
    operation: "applying a Palmier-native AI change",
  });
  if (guarded.response) return guarded.response;
  let stream: ReadableStream;
  try {
    stream = nativeStream(prepared, guarded.lease.release, dependencies.run);
  } catch (error) {
    guarded.lease.release();
    return json({ error: `Could not start this Palmier-native edit: ${(error as Error).message}` }, 500);
  }
  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
      "X-Sniper-Edit-Mode": "palmier-native",
    },
  });
}
