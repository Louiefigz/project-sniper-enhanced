import { randomUUID } from "crypto";
import { spawn } from "child_process";
import {
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "fs";
import path from "path";
import { pythonInterpreter, SCRIPTS_DIR } from "./spawn-python";
import {
  commitPlanRefitReceipt,
  cutTrackHash,
  refitSha256,
  sameRefitJson,
  stagePlanRefitReceipt,
  type PlanRefitChange,
  type PlanRefitReceipt,
  type PlanRefitSource,
} from "./plan-refit-receipt";

const PRODUCER_ROOT = path.join(SCRIPTS_DIR, "producer");
const PLAN_REFIT = path.join(PRODUCER_ROOT, "edit", "plan_refit.py");

export {
  currentPlanRefitReceipt,
  resolvePlanRefitDecision,
  writePlanRefitReceipt,
  type PlanRefitDecision,
  type PlanRefitProvenance,
  type PlanRefitReceipt,
} from "./plan-refit-receipt";

interface PlanRefitInput {
  planPath: string;
  source: PlanRefitSource;
  oldPlanPath?: string;
  oldPlanText?: string;
  receiptDir?: string;
  deferReceiptCommit?: boolean;
}

interface RefitProcessResult {
  code: number;
  stdout: string;
  stderr: string;
}

function parsedObject(text: string, label: string): Record<string, unknown> {
  const value = JSON.parse(text) as unknown;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be a JSON object`);
  }
  return value as Record<string, unknown>;
}

function runRefit(oldPath: string, stagedPath: string): Promise<RefitProcessResult> {
  return new Promise((resolve) => {
    const proc = spawn(pythonInterpreter(), [PLAN_REFIT, oldPath, stagedPath, "--write"], {
      cwd: PRODUCER_ROOT,
      env: {
        ...process.env,
        PYTHONPATH: [PRODUCER_ROOT, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
      },
    });
    let stdout = "";
    let stderr = "";
    proc.stdout.on("data", (data: Buffer) => (stdout += data.toString()));
    proc.stderr.on("data", (data: Buffer) => (stderr += data.toString()));
    proc.on("close", (code) => resolve({ code: code ?? 1, stdout, stderr }));
    proc.on("error", (error) => resolve({ code: 1, stdout, stderr: error.message }));
  });
}

function changesFrom(stdout: string): PlanRefitChange[] {
  return stdout.split("\n").flatMap((line): PlanRefitChange[] => {
    if (!line.trim()) return [];
    let row: Record<string, unknown>;
    try { row = JSON.parse(line) as Record<string, unknown>; } catch { return []; }
    if (row.status !== "refit" || typeof row.track !== "string") return [];
    const dropped = row.dropped === true;
    const remapped = row.remapped === true;
    if (!dropped && !remapped) return [];
    return [{
      track: row.track,
      index: Number.isInteger(row.index) ? Number(row.index) : -1,
      action: dropped ? "dropped" : "remapped",
      from: row.from ?? row.window ?? row.at,
      to: row.to,
      reason: typeof row.reason === "string" ? row.reason : undefined,
    }];
  });
}

function oldText(input: PlanRefitInput): string {
  if (input.oldPlanText !== undefined) return input.oldPlanText;
  if (input.oldPlanPath) return readFileSync(input.oldPlanPath, "utf8");
  throw new Error("plan refit requires an old plan path or old plan text");
}

export function cutTimebaseChanged(input: Omit<PlanRefitInput, "source">): boolean {
  const previous = parsedObject(oldText({ ...input, source: "saved-plan" }), "old plan");
  const current = parsedObject(readFileSync(input.planPath, "utf8"), "edited plan");
  return !sameRefitJson(previous.cutTrack, current.cutTrack);
}

/** Stage, refit, compare-and-swap, then atomically promote a cut-timebase rewrite. */
export async function refitPlanTransaction(input: PlanRefitInput): Promise<PlanRefitReceipt | null> {
  const currentText = readFileSync(input.planPath, "utf8");
  const previousText = oldText(input);
  const previous = parsedObject(previousText, "old plan");
  const current = parsedObject(currentText, "edited plan");
  if (sameRefitJson(previous.cutTrack, current.cutTrack)) return null;

  const token = randomUUID();
  const stagedPath = `${input.planPath}.${token}.refit.json`;
  const temporaryOldPath = input.oldPlanText === undefined
    ? null : `${input.planPath}.${token}.before.json`;
  const oldPath = temporaryOldPath ?? input.oldPlanPath!;
  try {
    if (temporaryOldPath) writeFileSync(temporaryOldPath, previousText, { flag: "wx", mode: 0o600 });
    writeFileSync(stagedPath, currentText, { flag: "wx", mode: 0o600 });
    const result = await runRefit(oldPath, stagedPath);
    if (result.code !== 0) {
      throw new Error(`plan_refit failed (exit ${result.code}): ${(result.stderr || result.stdout).slice(-500)}`);
    }
    const stagedText = readFileSync(stagedPath, "utf8");
    const stagedPlan = parsedObject(stagedText, "refitted plan");
    const planChanged = !sameRefitJson(stagedPlan, current);
    const promotedText = planChanged ? stagedText : currentText;
    const changes = changesFrom(result.stdout);
    const receipt: PlanRefitReceipt = {
      schemaVersion: 2,
      transactionState: "staged",
      source: input.source,
      createdAt: new Date().toISOString(),
      inputPlanHash: refitSha256(currentText),
      planHash: refitSha256(promotedText),
      sourceCutHash: cutTrackHash(previous.cutTrack),
      targetCutHash: cutTrackHash(stagedPlan.cutTrack),
      sourceCutTrack: previous.cutTrack,
      targetCutTrack: stagedPlan.cutTrack,
      remapped: changes.filter((item) => item.action === "remapped").length,
      dropped: changes.filter((item) => item.action === "dropped").length,
      changes,
    };
    if (readFileSync(input.planPath, "utf8") !== currentText) {
      throw new Error("edit_plan.json changed before its refit receipt could be staged; retry the edit");
    }
    if (input.receiptDir) stagePlanRefitReceipt(input.receiptDir, receipt);
    if (planChanged) {
      // The input bytes were checked immediately above; this rename is the
      // compare-and-swap promotion paired with the already durable receipt.
      renameSync(stagedPath, input.planPath);
    }
    if (input.receiptDir && !input.deferReceiptCommit) {
      return commitPlanRefitReceipt(input.receiptDir, receipt, input.planPath);
    }
    return receipt;
  } finally {
    rmSync(stagedPath, { force: true });
    if (temporaryOldPath) rmSync(temporaryOldPath, { force: true });
  }
}

export function planRefitEvent(
  receipt: PlanRefitReceipt,
  application: "newly-applied" | "reused" = "newly-applied",
): Record<string, unknown> {
  const reused = application === "reused";
  return {
    event: "plan_refit_receipt",
    ...(receipt.dropped ? { status: "plan_refit_dropped" } : {}),
    source: receipt.source,
    remapped: receipt.remapped,
    dropped: receipt.dropped,
    changes: receipt.changes,
    application,
    alreadyApplied: reused,
    createdAt: receipt.createdAt,
  };
}
