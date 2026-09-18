import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { prepareSavedPlanReview } from "../auto-edit/saved-plan-request";
import {
  gateBundleOperatorIntent,
  parsePlanningGateVerdict,
  runPlanningGateBundle,
  spawnPlanningGate,
  transcriptCutCommand,
  type GateBundleVerdict,
} from "../auto-edit/planning-gates";
import type { SurgicalEditScope } from "@/lib/producer/surgical-edit";
import {
  captureTemplateUsageAuthority,
} from "@/lib/server/template-usage-history";
import { fileSha256 } from "@/lib/server/auto-edit-job-store";

const CUT_APPROVAL_FILE = ".sniper-cut-approval.json";
const HASH = /^[a-f0-9]{64}$/;
// The transcript_cut previsual gate (PREVISUAL_KEYS in transcript_cut_contract.py)
// permits ONLY these top-level keys on a cut-approval shadow; ANY other populated
// field is rejected — not just the visual lanes (graphicsTrack, transitions,
// punchIns, music, …) but their rationale sidecars (transitionRationale,
// graphicsDecisions, …) too. Build the shadow as an allowlist that mirrors that
// gate so it can never drift out of sync (a denylist silently leaks new fields).
const PREVISUAL_CUT_KEYS = ["planVersion", "target", "cutTrack", "cutDecisions"] as const;

export interface SurgicalGovernanceInput {
  dir: string;
  planPath: string;
  manifestPath: string;
  transcriptsDir: string;
  scope: SurgicalEditScope;
}

export interface SurgicalGovernanceResult {
  verdict: GateBundleVerdict;
  warnings: string[];
  templateUsage: ReturnType<typeof captureTemplateUsageAuthority>["authority"];
  cutApproval?: { path: string; text: string };
}

export function surgicalCutOnlyPlan(planPath: string): Record<string, unknown> {
  const value = JSON.parse(readFileSync(planPath, "utf8")) as unknown;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("surgical cut candidate must be a JSON object");
  }
  const full = value as Record<string, unknown>;
  const shadow: Record<string, unknown> = {};
  for (const key of PREVISUAL_CUT_KEYS) {
    if (key in full) shadow[key] = full[key];
  }
  return shadow;
}

function approvalText(verdict: ReturnType<typeof parsePlanningGateVerdict>): string {
  const receipt = verdict.metrics?.receipt as Record<string, unknown> | undefined;
  const hashes = [
    "planHash", "manifestHash", "transcriptDigest", "cutTrackDigest",
    "cutDecisionsDigest",
  ];
  if (!verdict.ok || receipt?.schemaVersion !== 1 || receipt.stage !== "previsual"
      || hashes.some((key) => typeof receipt[key] !== "string"
        || !HASH.test(receipt[key] as string))) {
    const detail = verdict.errors.join(" | ") || "malformed cut approval receipt";
    throw new Error(`transcript/cut authority rejected the surgical cut: ${detail}`);
  }
  return `${JSON.stringify(receipt, null, 2)}\n`;
}

async function candidateCutApproval(
  input: SurgicalGovernanceInput,
): Promise<{ path: string; text: string; temporary: string }> {
  const temporary = mkdtempSync(path.join(os.tmpdir(), "sniper-surgical-cut-gate-"));
  const shadowPath = path.join(temporary, `cut-only-${randomUUID()}.json`);
  const approvalPath = path.join(temporary, CUT_APPROVAL_FILE);
  try {
    writeFileSync(shadowPath, `${JSON.stringify(surgicalCutOnlyPlan(input.planPath), null, 2)}\n`, {
      flag: "wx", mode: 0o600,
    });
    const command = transcriptCutCommand({
      planPath: shadowPath, manifestPath: input.manifestPath,
      transcriptsDir: input.transcriptsDir, cutApprovalPath: approvalPath,
    }, "previsual");
    const verdict = parsePlanningGateVerdict(command.gate, await spawnPlanningGate(command));
    const text = approvalText(verdict);
    writeFileSync(approvalPath, text, { flag: "wx", mode: 0o600 });
    return { path: path.join(input.dir, CUT_APPROVAL_FILE), text, temporary };
  } catch (error) {
    rmSync(temporary, { recursive: true, force: true });
    throw error;
  }
}

function gateError(verdict: GateBundleVerdict): Error {
  const detail = verdict.errors.slice(0, 5)
    .map((item) => `${item.gate}: ${item.message}`).join(" | ");
  return new Error(`deterministic governance rejected the edit: ${detail || "gate failed"}`);
}

/** Run the same stored-intent, transcript, hook, claims, and lint wall as authoring. */
export async function runSurgicalGovernance(
  input: SurgicalGovernanceInput,
): Promise<SurgicalGovernanceResult> {
  const base = prepareSavedPlanReview(input.dir).ctx;
  if (path.resolve(base.manifestPath) !== path.resolve(input.manifestPath)
      || path.resolve(base.transcriptsDir) !== path.resolve(input.transcriptsDir)) {
    throw new Error("surgical gate inputs do not match the stored project media authority");
  }
  let candidate: Awaited<ReturnType<typeof candidateCutApproval>> | undefined;
  try {
    const captureId = `surgical-${fileSha256(input.planPath)?.slice(0, 24) ?? randomUUID()}`;
    const usage = captureTemplateUsageAuthority(base, undefined, {}, captureId);
    candidate = input.scope.lanes.includes("cuts")
      ? await candidateCutApproval(input) : undefined;
    const approvalPath = candidate
      ? path.join(candidate.temporary, CUT_APPROVAL_FILE)
      : path.join(input.dir, CUT_APPROVAL_FILE);
    const reference = base.intent?.reference && base.referenceStudy
      ? { profilePath: base.referenceStudy.profilePath, intent: base.intent.reference }
      : undefined;
    const verdict = await runPlanningGateBundle({
      planPath: input.planPath, manifestPath: input.manifestPath,
      transcriptsDir: input.transcriptsDir, cutApprovalPath: approvalPath,
      templateUsagePath: usage.authority.path,
      templateUsageDigest: usage.authority.digest,
      operatorIntent: gateBundleOperatorIntent(base.scope, base.intent), reference,
    });
    if (!verdict.ok) throw gateError(verdict);
    return {
      verdict,
      warnings: verdict.warnings.map((item) => `${item.gate}: ${item.message}`),
      templateUsage: usage.authority,
      ...(candidate ? { cutApproval: { path: candidate.path, text: candidate.text } } : {}),
    };
  } finally {
    if (candidate) rmSync(candidate.temporary, { recursive: true, force: true });
  }
}
