import { existsSync, realpathSync } from "node:fs";
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
import { autoEditJobPath, readAutoEditJob } from "@/lib/server/auto-edit-job-store";
import { activeHumanCutAcceptance, observeHumanCutJob } from "@/lib/server/human-cut-acceptance-store";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import {
  parseAutoEditDeliveryPolicy,
  type AutoEditDeliveryPolicy,
} from "@/lib/producer/auto-edit-delivery-policy";

export interface PreparedRequest {
  ctx: AutoEditCtx;
  resume: boolean;
  bootstrapPlanHash?: string;
  reviewSavedPlan?: boolean;
}

/** Waiting is an explicit approval boundary, not a fresh-launch or Resume hint. */
export function guardPendingCutApproval(dir: string): void {
  const jobPath = autoEditJobPath(dir);
  const job = readAutoEditJob(jobPath);
  if (existsSync(jobPath) && !job) {
    throw new RequestFailure(
      "The saved Auto Edit journal is invalid. Preserve it for diagnosis; a fresh launch cannot establish whether cut approval is pending.", 409,
    );
  }
  if (job?.ctx.workflowV2) throw new RequestFailure("The v2 guided checkpoint requires its explicit stage transition; ordinary launch is unavailable", 409);
  if (job?.status === "awaiting_cut_approval" || job?.status === "cut_accepted") {
    throw new RequestFailure(
      "This edit is waiting for cut approval. Review and accept that exact cut before continuing; Resume or a fresh render cannot approve it.",
      409,
    );
  }
}

/** Only the connected MP4 cut-first path may opt in to the new pause contract. */
export function parseCutWorkflow(
  body: Record<string, unknown>,
  deliveryPolicy: AutoEditDeliveryPolicy,
): "cut-first" | undefined {
  if (body.workflowPolicy === undefined) return undefined;
  if (body.workflowPolicy !== "cut-first") {
    throw new RequestFailure("workflowPolicy must be cut-first when provided", 400);
  }
  if (deliveryPolicy !== "mp4-only") {
    throw new RequestFailure("cut-first approval currently requires mp4-only delivery", 400);
  }
  if (body.reviewSavedPlan === true) {
    throw new RequestFailure("cut-first and saved-plan render review are separate actions", 400);
  }
  return "cut-first";
}

export function canonicalProducerDir(value: unknown): string {
  if (typeof value !== "string" || !path.isAbsolute(value)) {
    throw new RequestFailure("dir must be an absolute Producer project path", 400);
  }
  let dir: string;
  try { dir = realpathSync(value.replace(/\/$/, "")); } catch {
    throw new RequestFailure(`dir not found: ${value}`, 404);
  }
  const root = realpathSync(workspaceRoot({ initialize: false }));
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
  deliveryPolicy: AutoEditDeliveryPolicy,
): AutoEditCtx {
  try {
    return resolveAutoEditContext(dir, scope, intent, deliveryPolicy);
  } catch (error) {
    throw new RequestFailure((error as Error).message, 409);
  }
}

function savedPlanRequest(
  dir: string,
  body: Record<string, unknown>,
  deliveryPolicy: AutoEditDeliveryPolicy,
): PreparedRequest | null {
  if (body.reviewSavedPlan !== undefined
      && typeof body.reviewSavedPlan !== "boolean") {
    throw new RequestFailure("reviewSavedPlan must be a boolean", 400);
  }
  if (body.reviewSavedPlan !== true) return null;
  if (body.resume !== undefined) {
    throw new RequestFailure("reviewSavedPlan and resume are separate actions", 400);
  }
  try {
    return {
      ...prepareSavedPlanReview(dir, deliveryPolicy),
      reviewSavedPlan: true,
    };
  } catch (error) {
    throw new RequestFailure((error as Error).message, 409);
  }
}

/** Accepted-v1 Resume may not reconcile, rewrite or replace the saved creative context. */
function acceptedResumeRequest(dir: string, body: Record<string, unknown>): PreparedRequest | null {
  const existing = readAutoEditJob(autoEditJobPath(dir));
  if (!existing?.cutAcceptance) return null;
  const observed = observeHumanCutJob(dir), job = observed.job;
  activeHumanCutAcceptance(job);
  const allowed = ["dir", "resume", "scope", "deliveryPolicy", "workflowPolicy", "mode", "excerpt",
    "lanes", "brief", "shortDirection", "pace", "style", "reference", "music", "audioEnhance"];
  if (body.resume !== true || !["failed", "interrupted"].includes(job.status)
      || Object.keys(body).some((key) => !allowed.includes(key))
      || body.scope !== job.ctx.scope || body.deliveryPolicy !== job.ctx.deliveryPolicy
      || body.workflowPolicy !== job.ctx.workflowPolicy
      || canonicalJsonSha256(parseAutoEditIntent(body) ?? null)
        !== canonicalJsonSha256(parseAutoEditIntent(job.ctx.intent as Record<string, unknown>) ?? null)) {
    throw new RequestFailure("The accepted cut can only Resume its unchanged saved brief. A new or changed edit requires an explicit separate project; no in-place cut migration is authorized.", 409);
  }
  if (observeHumanCutJob(dir).sha256 !== observed.sha256) throw new RequestFailure("Accepted checkpoint changed during Resume validation", 409);
  return { ctx: job.ctx, resume: true };
}

/** Parse and resolve one canonical Auto Edit launch request. */
export function prepareRequest(body: Record<string, unknown>): PreparedRequest {
  if (Object.hasOwn(body, "workflowV2")) throw new RequestFailure("The v2 guided workflow is not publicly available until opening/body continuation is connected", 409);
  const dir = canonicalProducerDir(body.dir);
  guardPendingCutApproval(dir);
  let accepted: PreparedRequest | null;
  try { accepted = acceptedResumeRequest(dir, body); }
  catch (error) { throw error instanceof RequestFailure ? error : new RequestFailure(String(error), 409); }
  if (accepted) return accepted;
  let deliveryPolicy: AutoEditDeliveryPolicy;
  try {
    deliveryPolicy = parseAutoEditDeliveryPolicy(body.deliveryPolicy);
  } catch (error) {
    throw new RequestFailure((error as Error).message, 400);
  }
  const workflowPolicy = parseCutWorkflow(body, deliveryPolicy);
  const saved = savedPlanRequest(dir, body, deliveryPolicy);
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
  const requestedCtx = resolvedContext(dir, scope, requested, deliveryPolicy);
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
    ctx: { ...resolvedContext(dir, effective.scope, intent, deliveryPolicy),
      ...(workflowPolicy ? { workflowPolicy } : {}) } };
}
