import { NextRequest } from "next/server";
import { findProjectRoot } from "../../_lib/workspace";
import { acquireAutoEditLaunchLease } from "@/lib/server/auto-edit-launch-lock";
import { localApiRejection } from "@/lib/server/local-request-policy";
import { autoEditJobStream } from "./job-stream";
import {
  SSE_HEADERS,
} from "./stream";
import {
  guardPalmierCanonicalForAiEdit,
  PalmierCanonicalError,
} from "../ai-edit/palmier-canonical";
import {
  classifyPalmierWorkspace,
  type PalmierWorkspaceClassification,
} from "../ai-edit/palmier-native-stream";
import { guardProjectMutation } from "../../_lib/project-mutation";
import { prepareRequest, type PreparedRequest } from "./request";
import { RequestFailure } from "./request-failure";
import { startDetachedRun } from "./launch";

export { validateReferenceSelection } from "./saved-plan-request";
export { legacyPlanHash } from "./launch";

export const maxDuration = 2400;
export const dynamic = "force-dynamic";

interface PalmierLaunchDependencies {
  classify: (dir: string) => PalmierWorkspaceClassification;
  legacyGuard: (dir: string) => Promise<void>;
}

const PALMIER_LAUNCH_DEPENDENCIES: PalmierLaunchDependencies = {
  classify: classifyPalmierWorkspace,
  legacyGuard: guardPalmierCanonicalForAiEdit,
};

/** Let a managed Palmier run reconcile its own working head inside the worker.
 *
 * The plan-only guard intentionally rejects manual/promoted Palmier origins.
 * Calling it before a Palmier-primary worker starts would prevent the native
 * reconciler from adopting precisely the manual readback it is designed to
 * edit. Invalid managed metadata still fails closed; projects without a
 * managed workspace retain the legacy plan-first guard.
 */
export async function guardPalmierForAutoEditLaunch(
  dir: string,
  dependencies: PalmierLaunchDependencies = PALMIER_LAUNCH_DEPENDENCIES,
): Promise<void> {
  const workspace = dependencies.classify(dir);
  if (workspace.state === "invalid") {
    throw new PalmierCanonicalError(
      `${workspace.error} Refusing to launch against an unprovable Palmier working head.`,
      409,
    );
  }
  if (workspace.state === "managed") return;
  await dependencies.legacyGuard(dir);
}

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
    await guardedPalmierLaunch(prepared.ctx.dir);
    const started = await startDetachedRun(prepared);
    return new Response(autoEditJobStream(started.jobPath, started.token), { headers: SSE_HEADERS });
  } finally {
    mutation.lease.release();
    lease.release();
  }
}

async function guardedPalmierLaunch(dir: string): Promise<void> {
  try {
    await guardPalmierForAutoEditLaunch(dir);
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
