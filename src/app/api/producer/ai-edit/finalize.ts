import { existsSync, readFileSync, renameSync, rmSync, writeFileSync } from "fs";
import path from "path";
import { randomUUID } from "crypto";
import type { ProducerReview } from "../auto-edit/review-contract";
import { fileSha256 } from "@/lib/server/auto-edit-hash";
import { reconcileGraphicIds, type EditPlan } from "@/lib/producer/edit-plan";
import {
  assertSurgicalPlanChange,
  type SurgicalEditScope,
} from "@/lib/producer/surgical-edit";
import { runSurgicalEditCritic, type SurgicalCriticInput } from "./critic";
import { atomicWriteFileSync } from "@/lib/server/atomic-file";
import {
  commitPlanRefitReceipt,
  discardPendingPlanRefit,
  recoverPendingPlanRefit,
} from "../../_lib/plan-refit-receipt";
import {
  refitPlanTransaction,
  type PlanRefitReceipt,
} from "../../_lib/plan-refit-transaction";
import {
  runSurgicalGovernance,
  type SurgicalGovernanceInput,
  type SurgicalGovernanceResult,
} from "./surgical-governance";
import { writeTemplateUsageApproval } from "@/lib/server/template-usage-approval";

export const SURGICAL_REVIEW_FILE = ".sniper-surgical-review.json";

export interface FinalizeSurgicalEditInput extends Omit<SurgicalCriticInput, "changedFields"> {
  originalPlanText: string;
  /** Canonical authority promoted only after the isolated candidate passes. */
  authorityPlanPath?: string;
}

export interface FinalizeSurgicalEditDependencies {
  governance?: (input: SurgicalGovernanceInput) => Promise<{
    warnings: string[];
    cutApproval?: { path: string; text: string };
    verdict?: SurgicalGovernanceResult["verdict"];
    templateUsage?: SurgicalGovernanceResult["templateUsage"];
  }>;
  critic?: (input: SurgicalCriticInput) => Promise<ProducerReview>;
}

interface SurgicalReviewMarker {
  schemaVersion: 1;
  status: "pending" | "approved";
  scope: SurgicalEditScope;
  planHash?: string;
  changedFields?: string[];
  gateWarnings?: string[];
  critic?: ProducerReview;
}

function markerPath(dir: string): string {
  return path.join(dir, SURGICAL_REVIEW_FILE);
}

function writeMarker(dir: string, marker: SurgicalReviewMarker): void {
  const destination = markerPath(dir);
  const temporary = `${destination}.${randomUUID()}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(marker, null, 2)}\n`, { flag: "wx", mode: 0o600 });
  renameSync(temporary, destination);
}

export function beginSurgicalReview(dir: string, scope: SurgicalEditScope): void {
  writeMarker(dir, { schemaVersion: 1, status: "pending", scope });
}

export function rollbackSurgicalEdit(input: FinalizeSurgicalEditInput): void {
  const authority = input.authorityPlanPath ?? input.planPath;
  atomicWriteFileSync(authority, input.originalPlanText);
  if (input.planPath !== authority) rmSync(input.planPath, { force: true });
  rmSync(markerPath(input.dir), { force: true });
}

function parsedPlan(text: string, label: string): Record<string, unknown> {
  const value = JSON.parse(text) as unknown;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be a JSON object`);
  }
  return value as Record<string, unknown>;
}

function normalizePlan(planPath: string): Record<string, unknown> {
  const parsed = parsedPlan(readFileSync(planPath, "utf8"), "edited plan");
  const reconciled = reconcileGraphicIds(parsed as EditPlan).plan;
  atomicWriteFileSync(planPath, `${JSON.stringify(reconciled, null, 1)}\n`);
  return reconciled as Record<string, unknown>;
}

/** Every plan WRITE increments planVersion (stale-plan detection; excluded
 * from base fingerprints and planContentHash, so a bump never invalidates a
 * base or reviewed authority). Runs AFTER the surgical scope assert — the
 * counter is bookkeeping, never one of the editor's changed fields — and
 * BEFORE any refit, so refit receipts hash-bind the bumped bytes. */
function bumpPlanVersion(planPath: string, before: Record<string, unknown>): void {
  const current = parsedPlan(readFileSync(planPath, "utf8"), "edited plan");
  const next = { ...current, planVersion: (Number(before.planVersion) || 0) + 1 };
  atomicWriteFileSync(planPath, `${JSON.stringify(next, null, 1)}\n`);
}

function promoteCandidate(input: FinalizeSurgicalEditInput): string {
  const authority = input.authorityPlanPath ?? input.planPath;
  if (authority !== input.planPath) {
    atomicWriteFileSync(authority, readFileSync(input.planPath));
  }
  return authority;
}

interface FileBackup { path: string; previous: Buffer | null }

function promoteCutApproval(value: { path: string; text: string }): FileBackup {
  const backup = {
    path: value.path,
    previous: existsSync(value.path) ? readFileSync(value.path) : null,
  };
  atomicWriteFileSync(value.path, value.text);
  return backup;
}

function restoreFile(backup: FileBackup | null): void {
  if (!backup) return;
  if (backup.previous) atomicWriteFileSync(backup.path, backup.previous);
  else rmSync(backup.path, { force: true });
}

export async function finalizeSurgicalEdit(
  input: FinalizeSurgicalEditInput,
  dependencies: FinalizeSurgicalEditDependencies = {},
): Promise<{ changedFields: string[]; review: ProducerReview; refit: PlanRefitReceipt | null }> {
  let refit: PlanRefitReceipt | null = null;
  let approvalBackup: FileBackup | null = null;
  try {
    recoverPendingPlanRefit(input.dir, input.authorityPlanPath ?? input.planPath);
    const before = parsedPlan(input.originalPlanText, "original plan");
    const after = normalizePlan(input.planPath);
    const changedFields = assertSurgicalPlanChange(before, after, input.scope);
    bumpPlanVersion(input.planPath, before);
    refit = input.scope.lanes.includes("cuts")
      ? await refitPlanTransaction({
        planPath: input.planPath,
        oldPlanText: input.originalPlanText,
        source: "surgical-cut",
        receiptDir: input.dir,
        deferReceiptCommit: true,
      })
      : null;
    const governance = await (dependencies.governance ?? runSurgicalGovernance)({
      dir: input.dir, planPath: input.planPath,
      manifestPath: input.manifestPath, transcriptsDir: input.transcriptsDir,
      scope: input.scope,
    });
    const review = await (dependencies.critic ?? runSurgicalEditCritic)({ ...input, changedFields });
    if (review.verdict !== "pass" || review.materialIssues.length) {
      const issue = review.materialIssues[0];
      throw new Error(`independent critic rejected the edit: ${issue?.message ?? review.summary}`);
    }
    const authority = promoteCandidate(input);
    if (governance.cutApproval) {
      approvalBackup = promoteCutApproval(governance.cutApproval);
    }
    if (governance.verdict && governance.templateUsage) {
      writeTemplateUsageApproval({
        producerDir: input.dir, planPath: authority,
        manifestPath: input.manifestPath, transcriptsDir: input.transcriptsDir,
        templateUsage: governance.templateUsage,
        verdict: governance.verdict.gates.templateUsage,
        operatorIntentVerdict: governance.verdict.gates.operatorIntent,
      });
    }
    const planHash = fileSha256(authority);
    if (!planHash) throw new Error("edited plan disappeared before review approval");
    writeMarker(input.dir, {
      schemaVersion: 1,
      status: "approved",
      scope: input.scope,
      planHash,
      changedFields,
      gateWarnings: governance.warnings,
      critic: review,
    });
    if (authority !== input.planPath) rmSync(input.planPath, { force: true });
    if (refit) refit = commitPlanRefitReceipt(input.dir, refit, authority);
    return { changedFields, review, refit };
  } catch (error) {
    rollbackSurgicalEdit(input);
    restoreFile(approvalBackup);
    if (refit) discardPendingPlanRefit(input.dir);
    throw error;
  }
}

/** A crashed/pending or subsequently changed AI plan may not render as reviewed. */
export function assertSurgicalReviewCurrent(planPath: string): void {
  const destination = markerPath(path.dirname(planPath));
  if (!existsSync(destination)) return;
  let marker: SurgicalReviewMarker;
  try {
    marker = JSON.parse(readFileSync(destination, "utf8")) as SurgicalReviewMarker;
  } catch {
    throw new Error("surgical edit review marker is unreadable; rerun the requested edit");
  }
  if (marker.schemaVersion !== 1 || marker.status !== "approved" || !marker.planHash) {
    throw new Error("surgical edit is still awaiting deterministic validation and independent review");
  }
  if (fileSha256(planPath) !== marker.planHash) {
    throw new Error("the plan changed after its surgical edit review; review the current plan again");
  }
}
