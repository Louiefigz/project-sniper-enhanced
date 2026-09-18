import { NextRequest, NextResponse } from "next/server";
import {
  guardProjectMutation,
  mutationProjectRoot,
} from "../../_lib/project-mutation";
import { canonicalPalmierDir, localPalmierRejection } from "../palmier/request";
import {
  LiveBuildPreflightError,
  preflightLiveBuild,
} from "./preflight";
import { runLiveBuild } from "./runner";
import { readLiveBuildState } from "./state";

export const dynamic = "force-dynamic";
export const maxDuration = 2400;

function jsonError(error: unknown, status = 400): Response {
  const message = error instanceof Error ? error.message : String(error);
  const code = error instanceof LiveBuildPreflightError ? error.code : undefined;
  return NextResponse.json({ error: message, ...(code ? { code } : {}) }, { status });
}

export async function GET(req: NextRequest) {
  const rejection = localPalmierRejection(req);
  if (rejection) return jsonError(rejection.error, rejection.status);
  try {
    const dir = canonicalPalmierDir(req.nextUrl.searchParams.get("dir"));
    return NextResponse.json({ state: readLiveBuildState(dir) });
  } catch (error) {
    return jsonError(error);
  }
}

export async function POST(req: NextRequest) {
  const rejection = localPalmierRejection(req);
  if (rejection) return jsonError(rejection.error, rejection.status);
  const body = await req.json().catch(() => null) as Record<string, unknown> | null;
  let dir: string;
  try { dir = canonicalPalmierDir(body?.dir); } catch (error) { return jsonError(error); }
  const resume = body?.resume === true;
  if (body?.resume !== undefined && typeof body.resume !== "boolean") {
    return jsonError("resume must be a boolean");
  }
  const guarded = guardProjectMutation({
    projectRoot: mutationProjectRoot(dir), producerDir: dir,
    operation: resume ? "resuming a Palmier live build" : "building live in Palmier",
  });
  if (guarded.response) return guarded.response;
  let preflight;
  try {
    preflight = await preflightLiveBuild(dir, resume);
  } catch (error) {
    guarded.lease.release();
    return jsonError(error, error instanceof LiveBuildPreflightError ? error.status : 500);
  }
  return liveBuildResponse(preflight, resume, guarded.lease.release);
}

function liveBuildResponse(
  preflight: Awaited<ReturnType<typeof preflightLiveBuild>>,
  resume: boolean,
  release: () => void,
): Response {
  const encoder = new TextEncoder();
  const abort = new AbortController();
  let closed = false;
  const stream = new ReadableStream({
    start(controller) {
      const keepalive = setInterval(() => {
        if (!closed) try { controller.enqueue(encoder.encode(": keepalive\n\n")); } catch {}
      }, 10_000);
      const send = (event: Record<string, unknown>) => {
        if (!closed) try {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
        } catch {}
      };
      runLiveBuild(preflight, resume, send, abort.signal)
        .then(send)
        .catch((error) => send({ event: "error", message:
          error instanceof Error ? error.message : String(error) }))
        .finally(() => {
          clearInterval(keepalive);
          release();
          if (!closed) try { controller.close(); } catch {}
        });
    },
    cancel() {
      closed = true;
      abort.abort();
    },
  });
  return new Response(stream, { headers: {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
    "X-Accel-Buffering": "no",
    "X-Sniper-Edit-Mode": "palmier-live-build",
  } });
}
