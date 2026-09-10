import { NextRequest } from "next/server";
import { findProjectRoot } from "../../_lib/workspace";
import { acquireAutoEditLaunchLease } from "@/lib/server/auto-edit-launch-lock";
import { localApiRejection } from "@/lib/server/local-request-policy";
import { autoEditJobStream } from "./job-stream";
import {
  SSE_HEADERS,
} from "./stream";
import { PalmierCanonicalError } from "../ai-edit/palmier-canonical";
import { guardProjectMutation } from "../../_lib/project-mutation";
import { prepareRequest, type PreparedRequest } from "./request";
import { RequestFailure } from "./request-failure";
import { guardAutoEditDeliveryForLaunch, startDetachedRun } from "./launch";
import type { AutoEditCtx } from "./stream";

export const maxDuration = 2400;
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

async function preparedFromRequest(req: NextRequest): Promise<PreparedRequest> {
  try {
    const body = await req.json() as Record<string, unknown>;
    return prepareRequest(body);
  } catch (error) {
    if (error instanceof RequestFailure) throw error;
    throw new RequestFailure((error as Error).message, 400);
  }
}

async function runPreparedRequest(prepared: PreparedRequest): Promise<Response> {
  const lease = acquireAutoEditLaunchLease(prepared.ctx.dir);
  if (!lease) return json({ error: "Another Auto Edit launch is already being prepared." }, 409);
  const root = findProjectRoot(prepared.ctx.dir);
  if (!root) {
    lease.release();
    return json({ error: "Auto Edit project authority could not be resolved." }, 409);
  }
  const mutation = guardProjectMutation({
    projectRoot: root,
    producerDir: prepared.ctx.dir,
    operation: "starting Auto Edit",
  });
  if (mutation.response) {
    lease.release();
    return mutation.response;
  }
  try {
    await guardedPalmierLaunch(prepared.ctx);
    const started = await startDetachedRun(prepared);
    return new Response(autoEditJobStream(started.jobPath, started.token), { headers: SSE_HEADERS });
  } finally {
    mutation.lease.release();
    lease.release();
  }
}

async function guardedPalmierLaunch(ctx: AutoEditCtx): Promise<void> {
  try {
    await guardAutoEditDeliveryForLaunch(ctx);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const status = error instanceof PalmierCanonicalError ? error.statusCode : 503;
    throw new RequestFailure(`Palmier is the source of truth: ${message}`, status);
  }
}

export async function POST(req: NextRequest) {
  const rejection = localRejection(req);
  if (rejection) return rejection;
  try {
    return await runPreparedRequest(await preparedFromRequest(req));
  } catch (error) {
    const failure = error instanceof RequestFailure
      ? error : new RequestFailure((error as Error).message, 500);
    return json({ error: failure.message }, failure.status);
  }
}

function json(obj: unknown, status: number): Response {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
