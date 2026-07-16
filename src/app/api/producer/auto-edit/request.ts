import { realpathSync } from "node:fs";
import path from "node:path";
import { findProjectRoot, workspaceRoot } from "../../_lib/workspace";
import {
  authoritativeAutoEditIntent,
  reconcileStoredIntentCapabilities,
} from "./operator-intent-authority";
import {
  prepareSavedPlanReview,
  resolveAutoEditContext,
} from "./saved-plan-request";
import {
  AUTO_EDIT_SCOPES,
  parseAutoEditIntent,
  type AutoEditCtx,
  type AutoEditIntent,
  type AutoEditScope,
} from "./stream";
import { RequestFailure } from "./request-failure";

export interface PreparedRequest {
  ctx: AutoEditCtx;
  resume: boolean;
  bootstrapPlanHash?: string;
  reviewSavedPlan?: boolean;
}

function canonicalProducerDir(value: unknown): string {
  if (typeof value !== "string" || !path.isAbsolute(value)) {
    throw new RequestFailure("dir must be an absolute Producer project path", 400);
  }
  let dir: string;
  try { dir = realpathSync(value.replace(/\/$/, "")); } catch {
    throw new RequestFailure(`dir not found: ${value}`, 404);
  }
  const root = realpathSync(workspaceRoot());
  const relative = path.relative(root, dir);
  const projectRoot = findProjectRoot(dir);
  const outside = relative === "" || relative.startsWith("..")
    || path.isAbsolute(relative);
  if (outside || !projectRoot
      || dir !== path.join(realpathSync(projectRoot), "producer")) {
    throw new RequestFailure(
      "Auto Edit may run only in a canonical producer/ directory inside the configured workspace",
      403,
    );
  }
  return dir;
}

function resolvedContext(
  dir: string,
  scope: AutoEditScope,
  intent: AutoEditIntent | undefined,
): AutoEditCtx {
  try { return resolveAutoEditContext(dir, scope, intent); } catch (error) {
    throw new RequestFailure((error as Error).message, 409);
  }
}

function savedPlanRequest(
  dir: string,
  body: Record<string, unknown>,
): PreparedRequest | null {
  if (body.reviewSavedPlan !== undefined
      && typeof body.reviewSavedPlan !== "boolean") {
    throw new RequestFailure("reviewSavedPlan must be a boolean", 400);
  }
  if (body.reviewSavedPlan !== true) return null;
  if (body.resume !== undefined) {
    throw new RequestFailure("reviewSavedPlan and resume are separate actions", 400);
  }
  try { return { ...prepareSavedPlanReview(dir), reviewSavedPlan: true }; } catch (error) {
    throw new RequestFailure((error as Error).message, 409);
  }
}

/** Parse and resolve one canonical Auto Edit launch request. */
export function prepareRequest(body: Record<string, unknown>): PreparedRequest {
  const dir = canonicalProducerDir(body.dir);
  const saved = savedPlanRequest(dir, body);
  if (saved) return saved;
  const scope = body.scope as AutoEditScope;
  if (!AUTO_EDIT_SCOPES.includes(scope)) {
    throw new RequestFailure(`scope must be one of: ${AUTO_EDIT_SCOPES.join(", ")}`, 400);
  }
  if (body.resume !== undefined && typeof body.resume !== "boolean") {
    throw new RequestFailure("resume must be a boolean", 400);
  }
  let requested: AutoEditIntent | undefined;
  try { requested = parseAutoEditIntent(body); } catch (error) {
    throw new RequestFailure((error as Error).message, 400);
  }
  const requestedCtx = resolvedContext(dir, scope, requested);
  let storedIntent;
  try {
    storedIntent = authoritativeAutoEditIntent(
      dir, body, requestedCtx.manifestPath,
    );
  } catch (error) {
    throw new RequestFailure((error as Error).message, 409);
  }
  let effective: ReturnType<typeof reconcileStoredIntentCapabilities>;
  try {
    effective = reconcileStoredIntentCapabilities(
      dir, storedIntent, requestedCtx.manifestPath,
    );
  } catch (error) {
    throw new RequestFailure((error as Error).message, 409);
  }
  let intent: AutoEditIntent | undefined;
  try {
    intent = parseAutoEditIntent(effective as unknown as Record<string, unknown>);
  } catch (error) {
    throw new RequestFailure(
      `resolved edit intent is invalid: ${(error as Error).message}`, 409,
    );
  }
  return { resume: body.resume === true,
    ctx: resolvedContext(dir, effective.scope, intent) };
}
