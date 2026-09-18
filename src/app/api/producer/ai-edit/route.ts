import { NextRequest } from "next/server";
import { rmSync } from "fs";
import { randomUUID } from "node:crypto";
import { dlog, derror } from "@/lib/debug";
import {
  beginSurgicalReview,
  rollbackSurgicalEdit,
  type FinalizeSurgicalEditInput,
} from "./finalize";
import { buildAiEditPrompt } from "./prompt";
import { prepareSurgicalRequest, surgicalAuthorityFailure } from "./prepare";
import { guardProjectMutation, mutationProjectRoot } from "../../_lib/project-mutation";
import {
  buildAiEditInvocation,
  preparePlanForAi,
  type AiEditInvocation,
} from "./execution";
import { classifyPalmierWorkspace, maybePalmierNativeEdit } from "./palmier-native-stream";
import { createAiEditStream } from "./edit-streams";
import { localApiRejection } from "@/lib/server/local-request-policy";
import { canonicalProducerDir } from "../../_lib/workspace";
import {
  CUT_REPAIR_ROUTE_BLOCKER,
  isWordSafeCutRepairIntent,
  parseCutRepairDirective,
  type CutRepairDirectiveV1,
} from "./cut-repair-route-policy";
import {
  cutRepairHeader,
  cutRepairOperation,
  runCutRepairMode,
} from "./cut-repair-route-dispatch";
import { lookupProducerManifest } from "@/lib/server/producer-manifest";

export const maxDuration = 1800;
export const dynamic = "force-dynamic";

function localRejection(req: NextRequest): Response | null {
  const rejected = localApiRejection({
    method: req.method,
    pathname: req.nextUrl.pathname,
    protocol: req.nextUrl.protocol,
    host: req.headers.get("host"),
    origin: req.headers.get("origin"),
    secFetchSite: req.headers.get("sec-fetch-site"),
    contentType: req.headers.get("content-type"),
  });
  return rejected ? json({ error: rejected.error }, rejected.status) : null;
}

function canonicalBody(value: unknown): Record<string, unknown> | Response {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return json({ error: "Request body must be a JSON object" }, 400);
  }
  const body = value as Record<string, unknown>;
  try {
    return { ...body, dir: canonicalProducerDir(body.dir) };
  } catch (error) {
    return json({ error: (error as Error).message }, 400);
  }
}

function cutOnlyScope(value: unknown): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const lanes = (value as Record<string, unknown>).lanes;
  return Array.isArray(lanes) && lanes.length === 1 && lanes[0] === "cuts";
}

function cutRepairResponse(
  directive: CutRepairDirectiveV1,
  analysis: Record<string, unknown>,
): Response {
  return new Response(JSON.stringify({
    ok: true,
    mutation: directive.mode !== "analyze",
    analysis,
  }), {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      "X-Sniper-Edit-Mode": cutRepairHeader(directive.mode),
    },
  });
}

async function handleCutRepair(
  submitted: unknown,
  directive: CutRepairDirectiveV1,
): Promise<Response> {
  const body = canonicalBody(submitted);
  if (body instanceof Response) return body;
  if (!cutOnlyScope(body.scope)) {
    return json({
      error: "cut.restoreSpeech requires scope.lanes=[\"cuts\"]",
    }, 400);
  }
  const dir = body.dir as string;
  const guarded = guardProjectMutation({
    projectRoot: mutationProjectRoot(dir),
    producerDir: dir,
    operation: cutRepairOperation(directive.mode),
    allowCutRepairRecovery:
      directive.mode === "reopen"
      || directive.mode === "execute"
      || directive.mode === "review"
      || directive.mode === "approve",
  });
  if (guarded.response) return guarded.response;
  try {
    const manifest = lookupProducerManifest(dir);
    if (!manifest.path) {
      throw new Error(
        `${manifest.error} — re-ingest or bind one manifest before repair`);
    }
    const analysis = await runCutRepairMode(
      dir, manifest.path, directive);
    return cutRepairResponse(directive, analysis);
  } catch (error) {
    return json({
      error: `Cut repair request failed closed: ${(error as Error).message}`,
      code: "CUT_REPAIR_EVIDENCE_REQUIRED",
    }, 422);
  } finally {
    guarded.lease.release();
  }
}

export async function POST(req: NextRequest) {
  const rejected = localRejection(req);
  if (rejected) return rejected;
  const submitted = await req.json().catch(() => null);
  const submittedRow = submitted && typeof submitted === "object"
    && !Array.isArray(submitted)
    ? submitted as Record<string, unknown> : null;
  let cutRepairDirective: CutRepairDirectiveV1 | null;
  try {
    cutRepairDirective = parseCutRepairDirective(submittedRow?.request);
  } catch (error) {
    return json({ error: (error as Error).message }, 400);
  }
  if (cutRepairDirective) {
    return handleCutRepair(submitted, cutRepairDirective);
  }
  if (isWordSafeCutRepairIntent(submittedRow?.request)) {
    return json({
      error: CUT_REPAIR_ROUTE_BLOCKER,
      code: "FIRST_CLASS_CUT_REPAIR_ROUTE_REQUIRED",
    }, 409);
  }
  const body = canonicalBody(submitted);
  if (body instanceof Response) return body;
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
  const release = (preserveStaging = false) => {
    if (released) return;
    let cleanupFailure: unknown;
    if (stagingDir && !preserveStaging) {
      try {
        rmSync(stagingDir, { recursive: true, force: true });
      } catch (error) {
        cleanupFailure = error;
      }
    }
    guarded.lease.release();
    released = true;
    if (cleanupFailure) {
      derror("producer:ai-edit", "staging cleanup failed after lease release", cleanupFailure);
    }
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
    const captionInput = scope.lanes.includes("captions")
      ? { request, manifestPath, transcriptsDir } : undefined;
    candidate = preparePlanForAi(planPath, plan, captionInput);
    stagingDir = candidate.stagingDir;
  } catch (error) {
    release();
    const status = scope.lanes.includes("captions") ? 422 : 500;
    return json({ error: `Could not stage this AI edit: ${(error as Error).message}` }, status);
  }
  let invocation: AiEditInvocation;
  try {
    const prompt = buildAiEditPrompt(candidate.candidatePath, request, canvas, provider, scope);
    invocation = buildAiEditInvocation(provider, prompt, dir, candidate.candidatePath);
  } catch (error) {
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
    parentPlanHash: candidate.parentPlanHash,
    requestId: randomUUID(),
    submittedAt: new Date().toISOString(),
  };
  dlog("producer:ai-edit", `spawn ${invocation.label.toLowerCase()}`, {
    dir,
    request,
    snapshots: candidate.snapshots,
    provider: invocation.provider,
  });
  let stream: ReadableStream;
  try {
    beginSurgicalReview(dir, scope);
    stream = createAiEditStream(invocation, finalizer, release);
  } catch (error) {
    let failure: unknown = error;
    try { rollbackSurgicalEdit(finalizer); } catch (recovery) { failure = recovery; }
    try { release(); } catch (cleanup) { failure = cleanup; }
    return json({ error: `Could not start this AI edit: ${(failure as Error).message}` }, 500);
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
