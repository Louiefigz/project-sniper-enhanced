import { randomUUID } from "node:crypto";
import {
  existsSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import { snapshotPlan } from "../../_lib/plan-snapshots";
import {
  commitPlanRefitReceipt,
  discardPendingPlanRefit,
  recoverPendingPlanRefit,
  sameRefitJson,
} from "../../_lib/plan-refit-receipt";
import {
  planRefitEvent,
  refitPlanTransaction,
} from "../../_lib/plan-refit-transaction";
import { reconcileGraphicIds, type EditPlan } from "@/lib/producer/edit-plan";
import { atomicWriteFileSync, atomicWriteJsonSync } from "@/lib/server/atomic-file";

export type SavePlanTimebase = "auto" | "full-plan";

export class AmbiguousCutTimebaseError extends Error {}
export class StalePlanVersionError extends Error {}

export interface SavePlanResult {
  plan: EditPlan;
  planVersion: number;
  snapshots: number;
  refit: Record<string, unknown> | null;
}

interface SavePlanInput {
  filePath: string;
  plan: EditPlan;
  timebase: SavePlanTimebase;
}

function parsedPlan(text: string, label: string): EditPlan {
  const value = JSON.parse(text) as unknown;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be a JSON object`);
  }
  return value as EditPlan;
}

function nextPlan(plan: EditPlan): EditPlan {
  const reconciled = reconcileGraphicIds(plan).plan;
  return { ...reconciled, planVersion: (Number(plan.planVersion) || 0) + 1 };
}

function changedFields(before: EditPlan, after: EditPlan): string[] {
  const keys = new Set([...Object.keys(before), ...Object.keys(after)]);
  keys.delete("planVersion");
  return [...keys].filter((key) => !sameRefitJson(
    (before as unknown as Record<string, unknown>)[key],
    (after as unknown as Record<string, unknown>)[key],
  ));
}

function ordinarySave(filePath: string, plan: EditPlan): SavePlanResult {
  const snapshots = snapshotPlan(filePath);
  atomicWriteJsonSync(filePath, plan);
  return { plan, planVersion: Number(plan.planVersion), snapshots, refit: null };
}

function assertCutOnly(fields: string[]): void {
  const other = fields.filter((field) => field !== "cutTrack");
  if (!other.length) return;
  throw new AmbiguousCutTimebaseError(
    `cutTrack changed with ${other.join(", ")}; declare a complete-plan timebase or save the cut separately`,
  );
}

function assertCurrentVersion(before: EditPlan, requested: EditPlan): void {
  const current = Number(before.planVersion) || 0;
  const expected = Number(requested.planVersion) || 0;
  if (current === expected) return;
  throw new StalePlanVersionError(
    `edit plan version changed from ${expected} to ${current}; reload before saving`,
  );
}

async function saveCutOnly(
  filePath: string,
  beforeText: string,
  plan: EditPlan,
): Promise<SavePlanResult> {
  const dir = path.dirname(filePath);
  const candidate = `${filePath}.${randomUUID()}.cut-save.json`;
  let promoted = false;
  try {
    writeFileSync(candidate, `${JSON.stringify(plan, null, 2)}\n`, { flag: "wx", mode: 0o600 });
    const receipt = await refitPlanTransaction({
      planPath: candidate,
      oldPlanText: beforeText,
      source: "surgical-cut",
      receiptDir: dir,
      deferReceiptCommit: true,
    });
    if (!receipt) throw new Error("cut-only save produced no deterministic refit receipt");
    if (readFileSync(filePath, "utf8") !== beforeText) {
      throw new Error("edit_plan.json changed before the cut-only save could be promoted");
    }
    const snapshots = snapshotPlan(filePath);
    renameSync(candidate, filePath);
    promoted = true;
    const committed = commitPlanRefitReceipt(dir, receipt, filePath);
    const authoritative = parsedPlan(readFileSync(filePath, "utf8"), "refitted plan");
    return {
      plan: authoritative,
      planVersion: Number(authoritative.planVersion),
      snapshots,
      refit: planRefitEvent(committed),
    };
  } catch (error) {
    if (promoted) atomicWriteFileSync(filePath, beforeText);
    discardPendingPlanRefit(dir);
    throw error;
  } finally {
    rmSync(candidate, { force: true });
  }
}

/** Save a complete plan, or transactionally refit an explicitly proven cut-only diff. */
export async function savePlanTransaction(input: SavePlanInput): Promise<SavePlanResult> {
  const plan = nextPlan(input.plan);
  if (!existsSync(input.filePath)) return ordinarySave(input.filePath, plan);
  recoverPendingPlanRefit(path.dirname(input.filePath), input.filePath);
  const beforeText = readFileSync(input.filePath, "utf8");
  const before = parsedPlan(beforeText, "saved plan");
  assertCurrentVersion(before, input.plan);
  const fields = changedFields(before, plan);
  if (!fields.includes("cutTrack") || input.timebase === "full-plan") {
    return ordinarySave(input.filePath, plan);
  }
  assertCutOnly(fields);
  return saveCutOnly(input.filePath, beforeText, plan);
}
