import { NextRequest, NextResponse } from "next/server";
import { spawn } from "child_process";
import { existsSync } from "fs";
import path from "path";
import { pythonInterpreter, SCRIPTS_DIR } from "../../../_lib/spawn-python";
import { fileSha256 } from "@/lib/server/auto-edit-job-store";
import {
  autoEditQcApproval,
  findManifest,
  palmierMetaPath,
  palmierRenderPath,
  palmierStatePath,
  producerAuthorityPath,
  readJsonObject,
} from "../_lib";

export const dynamic = "force-dynamic";

const PUSH = path.join(SCRIPTS_DIR, "producer", "palmier", "push.py");

interface PreflightInput {
  base: string;
  planPath: string;
  manifestPath: string;
  memoryPlan: Record<string, unknown> | null;
}

interface InputError {
  error: string;
  status: number;
}

// Fidelity preflight for the editor's Palmier chip: PURE translate verdict.
// An optional in-memory plan keeps parity live while the user edits; no plan
// snapshot is written and there are no renders or Palmier app calls.
// The Python verdict owns vocabulary + canonical planHash. This route joins it
// to verified export/state metadata so "in sync" is earned, never inferred.
export async function POST(req: NextRequest) {
  const { dir, plan } = (await req.json()) as { dir?: string; plan?: unknown };
  const input = resolveInput(dir, plan);
  if ("error" in input) {
    return NextResponse.json({ error: input.error }, { status: input.status });
  }
  const result = await runPreflight(input);
  try {
    return NextResponse.json(joinCheckpoint(result.stdout, input));
  } catch {
    return NextResponse.json(
      { ok: false, blocked: `preflight produced no verdict (exit ${result.code})` },
      { status: 500 },
    );
  }
}

function resolveInput(dir: string | undefined, plan: unknown): PreflightInput | InputError {
  const base = (dir || "").replace(/\/$/, "");
  if (!base) return { error: "No dir provided", status: 400 };
  const planPath = path.join(base, "edit_plan.json");
  if (!existsSync(planPath)) return { error: `No edit_plan.json in ${base}`, status: 404 };
  const manifestPath = findManifest(base);
  if (!manifestPath) return { error: `No asset manifest for ${base}`, status: 404 };
  const memoryPlan = plan && typeof plan === "object" && !Array.isArray(plan)
    ? plan as Record<string, unknown>
    : null;
  return { base, planPath, manifestPath, memoryPlan };
}

function runPreflight(input: PreflightInput): Promise<{ stdout: string; code: number }> {
  return new Promise((resolve) => {
    const args = [PUSH, input.planPath, input.manifestPath, "--preflight"];
    const { memoryPlan } = input;
    if (memoryPlan) args.push("--plan-stdin");
    const proc = spawn(pythonInterpreter(), args, {
      env: { ...process.env },
    });
    let out = "";
    proc.stdout.on("data", (d: Buffer) => (out += d.toString()));
    proc.stderr.on("data", (d: Buffer) => process.stderr.write(d));
    proc.on("close", (c) => resolve({ stdout: out, code: c ?? 1 }));
    proc.on("error", () => resolve({ stdout: out, code: 1 }));
    proc.stdin.end(memoryPlan ? JSON.stringify(memoryPlan) : undefined);
  });
}

function joinCheckpoint(stdout: string, input: PreflightInput): Record<string, unknown> {
  const line = stdout.trim().split("\n").filter(Boolean).pop() ?? "";
  const verdict = JSON.parse(line) as Record<string, unknown>;
  const planHash = typeof verdict.planHash === "string" ? verdict.planHash : null;
  const state = readJsonObject(palmierStatePath(input.base));
  const meta = readJsonObject(palmierMetaPath(input.base));
  const authority = readJsonObject(producerAuthorityPath(input.base));
  const checkpointParity = asObject(state?.parity);
  const structural = asObject(state?.verification);
  const ownership = state?.ownership === "palmier" ? "palmier" : "sniper";
  const managedWorkspace = state?.schemaVersion === 4
    && typeof state.projectId === "string"
    && typeof state.projectPath === "string"
    && typeof state.latestTimelineId === "string"
    && (state.workspaceMode === "managed-draft"
      || state.workspaceMode === "verified-mirror"
      || state.mirrorMode === "visual-master");
  const renderExists = existsSync(palmierRenderPath(input.base));
  const publishedHash = renderExists ? fileSha256(palmierRenderPath(input.base)) : null;
  const internalRenderExists = existsSync(path.join(input.base, "final.mp4"));
  const audioVerified = meta?.audioVerified === true;
  const authorityHash = typeof authority?.authorityHash === "string"
    ? authority.authorityHash : null;
  const authorityCurrent = internalRenderExists && authority?.planHash === planHash
    && authorityHash != null;
  const qcApproval = autoEditQcApproval(input.base);
  const structurallyVerified = structural?.ok === true;
  const parityVerified = checkpointParity?.mirrorReady === true;
  const publicationVerified = publishedHash != null
    && meta?.publishedHash === publishedHash
    && meta?.visualMasterHash === authorityHash;
  const verified = meta?.exportVerified === true && audioVerified
    && structurallyVerified && parityVerified && publicationVerified
    && meta.planHash === planHash
    && meta.authorityHash === authorityHash && authorityCurrent && renderExists
    ;
  const checkpointed = state?.lastPushPlanHash === planHash;
  const syncState = managedWorkspace
    ? "palmier_owned"
    : verified && checkpointed
      ? "in_sync" : state?.lastPushPlanHash ? "behind" : "not_synced";
  const translated = verdict.ok === true;
  const authorityBlocked = managedWorkspace
    ? "Palmier is the working source of truth; edit there or use Ask AI for a governed candidate"
    : translated && !qcApproval.approved
    ? qcApproval.reason
    : translated && !authorityCurrent
      ? "in-house final.mp4 is stale or unproven for this disk plan — re-render before syncing"
      : verdict.blocked;
  return {
    ...verdict,
    ok: translated && authorityCurrent && qcApproval.approved && !managedWorkspace,
    blocked: authorityBlocked,
    renderExists, exportVerified: verified, audioVerified, structurallyVerified,
    publicationVerified,
    parityVerified, authorityVerified: authorityCurrent, authorityHash, syncState,
    ownership, managedWorkspace,
    qcApprovalRequired: qcApproval.required, qcApproved: qcApproval.approved,
    targetProjectId: state?.projectId ?? null,
    targetProject: state?.projectName ?? null,
    targetProjectPath: state?.projectPath ?? null,
    latestTimelineId: state?.latestTimelineId ?? null,
    previewPlan: input.memoryPlan != null,
  };
}

function asObject(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}
