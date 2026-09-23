import { existsSync, readFileSync } from "fs";
import path from "path";
import { resolveReferenceStudy } from "../../_lib/reference-library";
import { validStoredReferenceDecision } from "../../_lib/reference-decision";
import type { ReferenceDecision } from "../../_lib/reference-types";
import type { ReferenceIntent } from "@/lib/producer/intent-presets";
import { fileSha256 } from "@/lib/server/auto-edit-job-store";
import { resolveManifest } from "./chain";
import {
  resolvePlanRefitDecision,
  type PlanRefitReceipt,
} from "../../_lib/plan-refit-transaction";
import {
  reconcileStoredIntentCapabilities,
  storedAutoEditIntent,
} from "./operator-intent-authority";
import {
  parseAutoEditIntent,
  type AutoEditCtx,
  type AutoEditIntent,
  type AutoEditScope,
  type ResolvedReferenceStudy,
} from "./stream";
import {
  DEFAULT_AUTO_EDIT_DELIVERY_POLICY,
  type AutoEditDeliveryPolicy,
} from "@/lib/producer/auto-edit-delivery-policy";

function readReferenceDecision(study: ResolvedReferenceStudy): ReferenceDecision {
  const decisionPath = path.join(path.dirname(study.deepStudyPath), "reference.json");
  if (!existsSync(decisionPath)) throw new Error(`reference ${study.id} has no confirmed operator decision`);
  let value: unknown;
  try { value = JSON.parse(readFileSync(decisionPath, "utf8")); } catch (error) {
    throw new Error(`reference ${study.id} has an unreadable operator decision: ${(error as Error).message}`);
  }
  if (!validStoredReferenceDecision(value, study.id)) {
    throw new Error(`reference ${study.id} has an invalid operator decision`);
  }
  return value;
}

export function validateReferenceSelection(
  reference: ReferenceIntent,
  study: ResolvedReferenceStudy,
  decision: ReferenceDecision,
): void {
  const checks: Array<[string, unknown, unknown]> = [
    ["resolved reference mode", study.mode, reference.mode],
    ["decision.referenceId", decision.referenceId, reference.id],
    ["decision.mode", decision.mode, reference.mode],
    ["decision.strategy", decision.strategy, reference.strategy],
    ["decision.targetStyle", decision.targetStyle, reference.targetStyle ?? null],
    ["decision.candidateStyleName", decision.candidateStyleName, reference.candidateStyleName ?? null],
  ];
  const mismatch = checks.find(([, actual, expected]) => actual !== expected);
  if (!mismatch) return;
  const [field, actual, expected] = mismatch;
  throw new Error(
    `${field} must match the selected reference (${JSON.stringify(expected)}), got ${JSON.stringify(actual)}`,
  );
}

export function resolveReferenceContext(intent: AutoEditIntent | undefined): ResolvedReferenceStudy | undefined {
  const reference = intent?.reference;
  if (!reference) return undefined;
  const study = resolveReferenceStudy(reference.id);
  if (study.id !== reference.id) {
    throw new Error(`resolved reference id ${study.id} does not match requested ${reference.id}`);
  }
  validateReferenceSelection(reference, study, readReferenceDecision(study));
  if (!study.representativeFrames.length) {
    throw new Error(`reference ${reference.id} has no representative frames — run the full study first`);
  }
  return study;
}

export function resolveAutoEditContext(
  dir: string,
  scope: AutoEditScope,
  intent: AutoEditIntent | undefined,
  deliveryPolicy: AutoEditDeliveryPolicy = DEFAULT_AUTO_EDIT_DELIVERY_POLICY,
): AutoEditCtx {
  return {
    dir,
    scope,
    deliveryPolicy,
    intent,
    referenceStudy: resolveReferenceContext(intent),
    planPath: path.join(dir, "edit_plan.json"),
    ...resolveManifest(dir),
  };
}

/** Review-only launches derive every creative choice from project.json. */
export function prepareSavedPlanReview(
  dir: string,
  deliveryPolicy: AutoEditDeliveryPolicy = DEFAULT_AUTO_EDIT_DELIVERY_POLICY,
): {
  ctx: AutoEditCtx;
  resume: false;
  bootstrapPlanHash: string;
} {
  const stored = storedAutoEditIntent(dir);
  const requested = parseAutoEditIntent(stored as unknown as Record<string, unknown>);
  const requestedCtx = resolveAutoEditContext(
    dir, stored.scope, requested, deliveryPolicy,
  );
  const effective = reconcileStoredIntentCapabilities(dir, stored, requestedCtx.manifestPath);
  const intent = parseAutoEditIntent(effective as unknown as Record<string, unknown>);
  const ctx = resolveAutoEditContext(
    dir, effective.scope, intent, deliveryPolicy,
  );
  const bootstrapPlanHash = fileSha256(ctx.planPath);
  if (!bootstrapPlanHash) throw new Error("Render updated video requires a saved edit_plan.json");
  return { ctx, resume: false, bootstrapPlanHash };
}

export interface SavedPlanRefitResult {
  receipt: PlanRefitReceipt | null;
  snapshots?: number;
  alreadyApplied?: boolean;
}

/**
 * Verify a complete saved plan before review. Full-plan writers author every
 * timed lane in the plan's own cut timebase, so a base-plan cut mismatch must
 * never trigger a remap here. Explicit cut-only writers refit at mutation time
 * and leave a hash-bound receipt which this path may reuse.
 */
export async function refitSavedPlanBeforeReview(ctx: AutoEditCtx): Promise<SavedPlanRefitResult> {
  const decision = resolvePlanRefitDecision(
    ctx.dir,
    ctx.planPath,
    { kind: "full-plan" },
  );
  if (decision.kind === "unchanged") return { receipt: null };
  if (decision.kind === "already-applied") {
    return { receipt: decision.receipt, alreadyApplied: true };
  }
  throw new Error("complete saved plans may not enter the cut-only refit path");
}
