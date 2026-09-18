import { randomUUID } from "node:crypto";
import {
  existsSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import { autoEditAuthoritySnapshot } from "@/lib/server/auto-edit-authority-snapshot";
import { fileSha256 } from "@/lib/server/auto-edit-job-store";
import {
  gateBundleOperatorIntent,
  parsePlanningGateVerdict,
  spawnPlanningGate,
  transcriptCutCommand,
  type PlanningGateVerdict,
} from "./planning-gates";
import { AutoEditError, type AutoEditCtx, type Send } from "./stream";

const CUT_APPROVAL_FILE = ".sniper-cut-approval.json";
const SHA256 = /^[a-f0-9]{64}$/;

export interface CutApprovalReceipt {
  schemaVersion: 1;
  stage: "previsual";
  planHash: string;
  manifestHash: string;
  transcriptDigest: string;
  cutTrackDigest: string;
  cutDecisionsDigest: string;
  cuts: number;
  seams: unknown[];
  removals: unknown[];
  outputQuality?: {
    keptWords: number;
    adjacentDuplicates: unknown[];
    incompleteFinalSubordinate: boolean;
    suspiciousWordSpans: unknown[];
    forbiddenOpeningStarts?: unknown[];
  };
}

export type CutAuthorityEvidence = Pick<
  CutApprovalReceipt,
  "planHash" | "manifestHash" | "transcriptDigest"
  | "cutTrackDigest" | "cutDecisionsDigest"
>;

export function cutApprovalPath(ctx: AutoEditCtx): string {
  return path.join(ctx.dir, CUT_APPROVAL_FILE);
}

function receiptFrom(
  verdict: PlanningGateVerdict,
  sourceStage: "previsual" | "planning_gate" = "previsual",
): CutApprovalReceipt {
  const receipt = verdict.metrics?.receipt;
  if (!receipt || typeof receipt !== "object" || Array.isArray(receipt)) {
    throw new AutoEditError("transcript/cut gate returned no hash-bound receipt");
  }
  const value = receipt as Record<string, unknown>;
  const hashes = [
    "planHash", "manifestHash", "transcriptDigest",
    "cutTrackDigest", "cutDecisionsDigest",
  ];
  if (value.schemaVersion !== 1 || value.stage !== sourceStage
      || hashes.some((key) => typeof value[key] !== "string" || !SHA256.test(value[key] as string))
      || !Number.isInteger(value.cuts) || !Array.isArray(value.seams)
      || !Array.isArray(value.removals)) {
    throw new AutoEditError("transcript/cut gate returned a malformed cut receipt");
  }
  return { ...value, stage: "previsual" } as unknown as CutApprovalReceipt;
}

/** Extract the freshly computed immutable cut identity from an approved gate. */
export function cutAuthorityEvidence(
  verdict: PlanningGateVerdict,
): CutAuthorityEvidence {
  const receipt = verdict.metrics?.receipt;
  if (!receipt || typeof receipt !== "object" || Array.isArray(receipt)) {
    throw new AutoEditError("approved transcript/cut gate returned no authority receipt");
  }
  const value = receipt as Record<string, unknown>;
  const keys = [
    "planHash", "manifestHash", "transcriptDigest",
    "cutTrackDigest", "cutDecisionsDigest",
  ] as const;
  if (value.stage !== "planning_gate"
      || keys.some((key) => typeof value[key] !== "string" || !SHA256.test(value[key] as string))) {
    throw new AutoEditError("approved transcript/cut gate returned malformed authority");
  }
  return Object.fromEntries(keys.map((key) => [key, value[key]])) as unknown as CutAuthorityEvidence;
}

function assertCurrentAuthority(ctx: AutoEditCtx, receipt: CutApprovalReceipt): void {
  const authority = autoEditAuthoritySnapshot(ctx);
  if (receipt.planHash !== fileSha256(ctx.planPath)
      || receipt.manifestHash !== authority.manifestHash
      || receipt.transcriptDigest !== authority.transcriptDigest) {
    throw new AutoEditError("cut approval receipt does not match current plan/manifest/transcripts");
  }
}

function persistReceipt(ctx: AutoEditCtx, receipt: CutApprovalReceipt): void {
  const destination = cutApprovalPath(ctx);
  const temporary = `${destination}.${randomUUID()}.tmp`;
  try {
    writeFileSync(temporary, `${JSON.stringify(receipt, null, 2)}\n`, {
      flag: "wx", mode: 0o600,
    });
    renameSync(temporary, destination);
  } finally {
    rmSync(temporary, { force: true });
  }
}

function gateError(stage: string, verdict: PlanningGateVerdict): AutoEditError {
  const detail = verdict.errors.join("; ") || "gate failed without diagnostics";
  return new AutoEditError(`${stage} transcript/cut approval failed: ${detail}`);
}

function gateInput(ctx: AutoEditCtx) {
  return {
    planPath: ctx.planPath,
    manifestPath: ctx.manifestPath,
    transcriptsDir: ctx.transcriptsDir,
    cutApprovalPath: cutApprovalPath(ctx),
    operatorIntent: gateBundleOperatorIntent(ctx.scope, ctx.intent),
  };
}

export async function approvePrevisualCut(
  ctx: AutoEditCtx,
  send?: Send,
): Promise<CutApprovalReceipt> {
  const receipt = await validatePrevisualCut(ctx, send);
  persistReceipt(ctx, receipt);
  send?.({
    event: "cut_approved", cutTrackDigest: receipt.cutTrackDigest,
    planHash: receipt.planHash, cuts: receipt.cuts,
  });
  return receipt;
}

/** Approve only the cut authority of a complete saved plan, without rewriting it. */
export async function approveSavedPlanCut(
  ctx: AutoEditCtx,
  send?: Send,
): Promise<CutApprovalReceipt> {
  const receipt = await validateSavedPlanCut(ctx, send);
  persistReceipt(ctx, receipt);
  send?.({
    event: "cut_approved", savedPlan: true,
    cutTrackDigest: receipt.cutTrackDigest,
    planHash: receipt.planHash, cuts: receipt.cuts,
  });
  return receipt;
}

/** Run the deterministic previsual wall without minting cut authority. */
export async function validatePrevisualCut(
  ctx: AutoEditCtx,
  send?: Send,
): Promise<CutApprovalReceipt> {
  const command = transcriptCutCommand(gateInput(ctx), "previsual");
  const verdict = parsePlanningGateVerdict(command.gate, await spawnPlanningGate(command));
  send?.({ event: "cut_validation_gate", stage: "previsual", ...verdict });
  if (!verdict.ok) throw gateError("previsual", verdict);
  const receipt = receiptFrom(verdict);
  assertCurrentAuthority(ctx, receipt);
  return receipt;
}

/**
 * Validate a complete saved plan's exact bytes and cut fields. The underlying
 * planning-stage gate checks the same transcript boundaries/removal evidence
 * without the cut-writer-only prohibition on populated downstream lanes.
 */
export async function validateSavedPlanCut(
  ctx: AutoEditCtx,
  send?: Send,
): Promise<CutApprovalReceipt> {
  const command = transcriptCutCommand(gateInput(ctx), "saved-plan");
  const verdict = parsePlanningGateVerdict(command.gate, await spawnPlanningGate(command));
  send?.({ event: "cut_validation_gate", stage: "saved-plan", ...verdict });
  if (!verdict.ok) throw gateError("saved-plan", verdict);
  const receipt = receiptFrom(verdict, "planning_gate");
  assertCurrentAuthority(ctx, receipt);
  return receipt;
}

export async function verifyApprovedCut(
  ctx: AutoEditCtx,
  send?: Send,
): Promise<PlanningGateVerdict> {
  if (!existsSync(cutApprovalPath(ctx))) {
    throw new AutoEditError("controller-owned cut approval receipt is missing");
  }
  const command = transcriptCutCommand(gateInput(ctx), "approved");
  const verdict = parsePlanningGateVerdict(command.gate, await spawnPlanningGate(command));
  send?.({ event: "cut_approval_gate", stage: "approved", ...verdict });
  if (!verdict.ok) throw gateError("approved", verdict);
  return verdict;
}

export function readCutApproval(ctx: AutoEditCtx): CutApprovalReceipt | null {
  try {
    const value = JSON.parse(readFileSync(cutApprovalPath(ctx), "utf8"));
    return value && typeof value === "object" ? value as CutApprovalReceipt : null;
  } catch {
    return null;
  }
}
