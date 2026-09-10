import { createHash, randomUUID } from "node:crypto";
import {
  existsSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import {
  canonicalJson,
  canonicalJsonSha256,
} from "@/lib/server/auto-edit-hash";

export const PLAN_REFIT_RECEIPT_FILE = ".sniper-plan-refit.json";
export const PLAN_REFIT_PENDING_FILE = ".sniper-plan-refit.pending.json";

export type PlanRefitSource = "surgical-cut" | "saved-plan";

export interface PlanRefitChange {
  track: string;
  index: number;
  action: "remapped" | "dropped";
  from?: unknown;
  to?: unknown;
  reason?: string;
}

export interface PlanRefitReceipt {
  schemaVersion: 2;
  transactionState: "staged" | "committed";
  source: PlanRefitSource;
  createdAt: string;
  inputPlanHash: string;
  planHash: string;
  sourceCutHash: string;
  targetCutHash: string;
  sourceCutTrack: unknown;
  targetCutTrack: unknown;
  remapped: number;
  dropped: number;
  changes: PlanRefitChange[];
}

export type PlanRefitDecision =
  | { kind: "unchanged" }
  | { kind: "already-applied"; receipt: PlanRefitReceipt }
  | { kind: "refit"; oldPlanText: string };

export function planRefitReceiptPath(dir: string): string {
  return path.join(dir, PLAN_REFIT_RECEIPT_FILE);
}

/**
 * A cut mismatch is not evidence that output-time lanes are stale. The caller
 * must identify how the current plan was produced before a refit is allowed.
 */
export type PlanRefitProvenance =
  | { kind: "full-plan" }
  | { kind: "cut-only"; oldPlanText: string }
  | { kind: "unknown" };

export function sameRefitJson(left: unknown, right: unknown): boolean {
  if (left === undefined || right === undefined) return left === right;
  return canonicalJson(left) === canonicalJson(right);
}

export function refitSha256(text: string): string {
  return createHash("sha256").update(text).digest("hex");
}

export function cutTrackHash(cutTrack: unknown): string {
  return canonicalJsonSha256(cutTrack);
}

function parsedPlan(text: string, label: string): Record<string, unknown> {
  const value = JSON.parse(text) as unknown;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be a JSON object`);
  }
  return value as Record<string, unknown>;
}

function atomicReceipt(filePath: string, receipt: PlanRefitReceipt): void {
  const temporary = `${filePath}.${randomUUID()}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(receipt, null, 2)}\n`, { flag: "wx", mode: 0o600 });
  renameSync(temporary, filePath);
}

function validateReceipt(value: unknown, label: string): PlanRefitReceipt {
  const row = value as Partial<PlanRefitReceipt> | null;
  if (!row || typeof row !== "object" || row.schemaVersion !== 2
      || !["staged", "committed"].includes(String(row.transactionState))
      || !["surgical-cut", "saved-plan"].includes(String(row.source))
      || typeof row.inputPlanHash !== "string" || typeof row.planHash !== "string"
      || typeof row.sourceCutHash !== "string" || typeof row.targetCutHash !== "string"
      || !Array.isArray(row.sourceCutTrack) || !Array.isArray(row.targetCutTrack)
      || !Number.isInteger(row.remapped) || !Number.isInteger(row.dropped)
      || !Array.isArray(row.changes)
      || cutTrackHash(row.sourceCutTrack) !== row.sourceCutHash
      || cutTrackHash(row.targetCutTrack) !== row.targetCutHash) {
    throw new Error(`${label} is malformed or has conflicting cut-timebase hashes`);
  }
  return row as PlanRefitReceipt;
}

function readReceipt(filePath: string, label: string): PlanRefitReceipt | null {
  if (!existsSync(filePath)) return null;
  try {
    return validateReceipt(JSON.parse(readFileSync(filePath, "utf8")) as unknown, label);
  } catch (error) {
    if (error instanceof SyntaxError) throw new Error(`${label} is not valid JSON`);
    throw error;
  }
}

export function stagePlanRefitReceipt(dir: string, receipt: PlanRefitReceipt): void {
  atomicReceipt(path.join(dir, PLAN_REFIT_PENDING_FILE), {
    ...receipt, transactionState: "staged",
  });
}

export function commitPlanRefitReceipt(
  dir: string,
  receipt: PlanRefitReceipt,
  planPath: string,
): PlanRefitReceipt {
  const planText = readFileSync(planPath, "utf8");
  const plan = parsedPlan(planText, "promoted refit plan");
  if (receipt.planHash !== refitSha256(planText)
      || !sameRefitJson(receipt.targetCutTrack, plan.cutTrack)) {
    throw new Error("refit receipt does not match the promoted plan; refusing timebase authority");
  }
  const committed: PlanRefitReceipt = { ...receipt, transactionState: "committed" };
  atomicReceipt(planRefitReceiptPath(dir), committed);
  rmSync(path.join(dir, PLAN_REFIT_PENDING_FILE), { force: true });
  return committed;
}

export function discardPendingPlanRefit(dir: string): void {
  rmSync(path.join(dir, PLAN_REFIT_PENDING_FILE), { force: true });
}

export function recoverPendingPlanRefit(dir: string, planPath: string): PlanRefitReceipt | null {
  const pendingPath = path.join(dir, PLAN_REFIT_PENDING_FILE);
  const pending = readReceipt(pendingPath, "pending plan refit receipt");
  if (!pending) return null;
  const text = readFileSync(planPath, "utf8");
  const current = parsedPlan(text, "current plan");
  if (pending.planHash === refitSha256(text)
      && sameRefitJson(pending.targetCutTrack, current.cutTrack)) {
    return commitPlanRefitReceipt(dir, pending, planPath);
  }
  if (pending.inputPlanHash === refitSha256(text)) {
    rmSync(pendingPath, { force: true });
    return null;
  }
  if (sameRefitJson(pending.sourceCutTrack, current.cutTrack)) {
    rmSync(pendingPath, { force: true });
    return null;
  }
  throw new Error(
    "pending plan refit conflicts with the current cut timebase; preserve the files and recover the last plan snapshot",
  );
}

export function resolvePlanRefitDecision(
  dir: string,
  planPath: string,
  provenance: PlanRefitProvenance,
): PlanRefitDecision {
  recoverPendingPlanRefit(dir, planPath);
  const currentText = readFileSync(planPath, "utf8");
  const current = parsedPlan(currentText, "current plan");
  const receipt = readReceipt(
    planRefitReceiptPath(dir), "plan refit receipt",
  );
  if (receipt?.planHash === refitSha256(currentText)
      && sameRefitJson(receipt.targetCutTrack, current.cutTrack)) {
    return { kind: "already-applied", receipt };
  }
  if (provenance.kind === "full-plan") return { kind: "unchanged" };
  if (provenance.kind === "unknown") {
    throw new Error(
      "edit plan cut-timebase provenance is unknown; refusing to infer a refit from base_plan.json",
    );
  }
  const previous = parsedPlan(provenance.oldPlanText, "pre-mutation plan");
  if (receipt && !sameRefitJson(receipt.targetCutTrack, previous.cutTrack)) {
    throw new Error(
      "cut-only mutation does not begin at the last proven target timebase; refusing to refit",
    );
  }
  return sameRefitJson(previous.cutTrack, current.cutTrack)
    ? { kind: "unchanged" }
    : { kind: "refit", oldPlanText: provenance.oldPlanText };
}

export function writePlanRefitReceipt(
  dir: string,
  receipt: PlanRefitReceipt,
  planPath: string,
): void {
  commitPlanRefitReceipt(dir, receipt, planPath);
}

export function currentPlanRefitReceipt(dir: string, planPath: string): PlanRefitReceipt | null {
  try {
    const receipt = readReceipt(planRefitReceiptPath(dir), "plan refit receipt");
    if (!receipt || receipt.transactionState !== "committed") return null;
    const text = readFileSync(planPath, "utf8");
    const plan = parsedPlan(text, "current plan");
    return receipt.planHash === refitSha256(text)
      && sameRefitJson(receipt.targetCutTrack, plan.cutTrack) ? receipt : null;
  } catch {
    return null;
  }
}
