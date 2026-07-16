import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { cachedFileSha256 } from "./cached-file-sha256";
import {
  durableProcessAlive,
  validProcessIdentity,
} from "./process-liveness";

export const PALMIER_CANDIDATE_FILE = "palmier.timeline-candidate.json";
export const PALMIER_NATIVE_QC_FILE = "palmier.native-qc.json";
export const PALMIER_NATIVE_QC_RUN_FILE = "palmier.native-qc.run.json";

export interface PalmierCandidateQcRun {
  active: boolean;
  action: "run_qc" | "promote" | "discard" | null;
  step: string | null;
  message: string | null;
  log: Array<{ at: string; step: string; message: string }>;
}

type JsonObject = Record<string, unknown>;

export interface PalmierCandidateQcState {
  state: "none" | "pending" | "prepared" | "checking" | "approved" | "stale" | "rejected" | "quarantined";
  canRunQc: boolean;
  canPromote: boolean;
  canDiscard: boolean;
  candidateTimelineId: string | null;
  detail: string;
  run: PalmierCandidateQcRun;
}

function readObject(filePath: string): JsonObject | null {
  try {
    const value = JSON.parse(readFileSync(filePath, "utf8")) as unknown;
    return value && typeof value === "object" && !Array.isArray(value)
      ? value as JsonObject : null;
  } catch {
    return null;
  }
}

function objectValue(value: unknown): JsonObject | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as JsonObject : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function sameIdentity(candidate: JsonObject, receipt: JsonObject | null): boolean {
  const approved = objectValue(receipt?.candidate);
  return !!approved && approved.timelineId === candidate.timelineId
    && approved.fingerprint === candidate.fingerprint;
}

function exportMatches(filePath: string, expected: unknown): boolean {
  if (typeof expected !== "string" || !existsSync(filePath)) return false;
  try { return cachedFileSha256(filePath) === expected; } catch { return false; }
}

export function candidateReceipt(dir: string): JsonObject | null {
  return readObject(path.join(dir, PALMIER_CANDIDATE_FILE));
}

function candidateArchiveCurrent(dir: string, candidate: JsonObject): boolean {
  const qc = objectValue(candidate.qc);
  const resolution = objectValue(candidate.resolution);
  const archive = stringValue(resolution?.archivePath) ?? stringValue(qc?.archivePath);
  if (!archive || !path.isAbsolute(archive)) return false;
  const relative = path.relative(path.resolve(dir), path.resolve(archive));
  if (relative.startsWith("..") || path.isAbsolute(relative)) return false;
  const manifest = readObject(path.join(archive, "archive.json"));
  const archived = objectValue(manifest?.candidate);
  return manifest?.schemaVersion === 1 && manifest.state === candidate.status
    && archived?.projectId === candidate.projectId
    && archived?.timelineId === candidate.timelineId
    && archived?.fingerprint === candidate.fingerprint;
}

/** Fast UX guard; locked Python repeats this before any Palmier candidate fork. */
export function assertCandidateSlotAvailable(dir: string): void {
  const candidate = candidateReceipt(dir);
  if (!candidate || ["promoted", "superseded-manual"]
    .includes(String(candidate.status))) return;
  if (["qc-rejected", "discarded"].includes(String(candidate.status))
      && candidateArchiveCurrent(dir, candidate)) return;
  const action = candidate.status === "qc-approved"
    ? "Use the approved candidate, or choose Discard candidate & keep parent"
    : candidate.status === "quarantined" || candidate.status === "quarantined-recovered"
      ? "Choose Discard candidate & keep parent to archive the failure"
      : "Review it and run candidate QC, or choose Discard candidate & keep parent";
  throw new Error(`A Palmier AI candidate is already ${String(candidate.status)}; ${action} before asking AI for another change. Its receipt and QC evidence were preserved.`);
}

export function nativeQcReceipt(dir: string): JsonObject | null {
  return readObject(path.join(dir, PALMIER_NATIVE_QC_FILE));
}

function qcRun(dir: string): PalmierCandidateQcRun {
  const value = readObject(path.join(dir, PALMIER_NATIVE_QC_RUN_FILE));
  const pid = typeof value?.pid === "number" ? value.pid : undefined;
  const identity = validProcessIdentity(value?.ownerIdentity) ? value.ownerIdentity : undefined;
  const updatedAt = typeof value?.updatedAt === "string" ? value.updatedAt : "";
  const wasRunning = value?.status === "running";
  const active = wasRunning && durableProcessAlive(pid, identity, updatedAt);
  const action = value?.action === "run_qc" || value?.action === "promote"
    || value?.action === "discard"
    ? value.action : null;
  const rows = Array.isArray(value?.log) ? value.log : [];
  const log = rows.flatMap((item) => {
    const row = objectValue(item);
    return typeof row?.at === "string" && typeof row.step === "string"
      && typeof row.message === "string"
      ? [{ at: row.at, step: row.step, message: row.message }] : [];
  });
  return {
    active,
    action,
    step: wasRunning && !active ? "interrupted" : stringValue(value?.step),
    message: wasRunning && !active
      ? interruptedMessage(action)
      : stringValue(value?.message),
    log,
  };
}

function interruptedMessage(action: PalmierCandidateQcRun["action"]): string {
  if (action === "promote") {
    return "Candidate promotion was interrupted. Nothing was promoted; recheck before trying again.";
  }
  if (action === "discard") {
    return "Candidate discard was interrupted. Its receipt remains protected; retry to archive and restore safely.";
  }
  return "Candidate QC was interrupted. Its completed checkpoint is saved; run QC to resume safely.";
}

export function currentApprovedCandidate(
  dir: string,
  projectId?: string | null,
): JsonObject | null {
  const candidate = candidateReceipt(dir);
  const qc = nativeQcReceipt(dir);
  const candidateQc = objectValue(candidate?.qc);
  const exported = objectValue(qc?.export);
  const exportPath = path.join(dir, "palmier.candidate.mp4");
  const exportCurrent = exported?.path === exportPath
    && exportMatches(exportPath, exported.hash);
  if (!candidate || !qc || candidate.schemaVersion !== 1 || qc.schemaVersion !== 1
      || candidate.status !== "qc-approved" || qc.status !== "qc-approved"
      || candidateQc?.approved !== true
      || typeof candidateQc.approvalDigest !== "string"
      || candidateQc.approvalDigest !== qc.approvalDigest
      || !exportCurrent
      || (projectId && candidate.projectId !== projectId) || !sameIdentity(candidate, qc)) return null;
  return candidate;
}

function stateDetail(state: PalmierCandidateQcState["state"]): string {
  const details: Record<PalmierCandidateQcState["state"], string> = {
    none: "No governed Palmier candidate is waiting.",
    pending: "The candidate is review-only. Run exported deterministic and visual QC before approval.",
    prepared: "The exact candidate export is prepared; deterministic and visual checks remain.",
    checking: "Deterministic checks passed; both independent rendered reviews remain required.",
    approved: "The candidate passed exported deterministic, composition, and editorial QC. Promotion still performs a fresh compare-and-swap check.",
    stale: "The candidate's prior approval no longer matches its receipt or exported evidence. Review it, then discard it safely before asking for a fresh governed candidate.",
    rejected: "Candidate QC stopped safely. The rejected candidate is archived and the verified parent remains current.",
    quarantined: "The candidate failed safely. Restore and verify its preserved parent before continuing.",
  };
  return details[state];
}

export function palmierCandidateQcState(dir: string): PalmierCandidateQcState {
  const run = qcRun(dir);
  const candidate = candidateReceipt(dir);
  if (!candidate || candidate.schemaVersion !== 1) return empty("none", run);
  const timelineId = stringValue(candidate.timelineId);
  if (candidate.status === "quarantined" || candidate.status === "quarantined-recovered") {
    return value("quarantined", false, false, !run.active, timelineId, run);
  }
  if (candidate.status === "qc-rejected" || candidate.status === "discarded") {
    return value("rejected", false, false, false, timelineId, run);
  }
  const qc = nativeQcReceipt(dir);
  const approved = currentApprovedCandidate(dir, stringValue(candidate.projectId));
  if (approved) return value("approved", false, !run.active, !run.active, timelineId, run);
  if (candidate.status === "qc-approved") {
    return value("stale", false, false, !run.active, timelineId, run);
  }
  const status = qc?.schemaVersion === 1 && sameIdentity(candidate, qc) ? qc.status : null;
  if (status === "deterministic-passed") {
    return value("checking", !run.active, false, !run.active, timelineId, run);
  }
  if (status === "prepared") {
    return value("prepared", !run.active, false, !run.active, timelineId, run);
  }
  if (!["staged", "edited"].includes(String(candidate.status))) return empty("none", run);
  return value("pending", !run.active, false, !run.active, timelineId, run);
}

function value(
  state: PalmierCandidateQcState["state"],
  canRunQc: boolean,
  canPromote: boolean,
  canDiscard: boolean,
  candidateTimelineId: string | null,
  run: PalmierCandidateQcRun,
): PalmierCandidateQcState {
  const detail = run.active && run.message ? run.message : stateDetail(state);
  return { state, canRunQc, canPromote, canDiscard, candidateTimelineId, detail, run };
}

function empty(state: "none", run: PalmierCandidateQcRun): PalmierCandidateQcState {
  return value(state, false, false, false, null, run);
}

export function candidateExportExists(dir: string): boolean {
  return existsSync(path.join(dir, "palmier.candidate.mp4"));
}
