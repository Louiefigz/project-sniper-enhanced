import fs from "node:fs";
import path from "node:path";
import type {
  PalmierProjectState,
  PalmierProjectStateKind,
} from "@/lib/producer/project-card-state";
import {
  candidateReceipt,
  currentApprovedCandidate,
  palmierCandidateQcState,
} from "@/lib/server/palmier-candidate-qc";

function readObject(filePath: string): Record<string, unknown> | null {
  try {
    const value = JSON.parse(fs.readFileSync(filePath, "utf8")) as unknown;
    return value && typeof value === "object" && !Array.isArray(value)
      ? value as Record<string, unknown> : null;
  } catch {
    return null;
  }
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

function sameHead(
  head: Record<string, unknown> | null,
  authority: Record<string, unknown>,
): boolean {
  if (!head) return false;
  return head.projectId === authority.projectId
    && head.timelineId === authority.timelineId
    && head.fingerprint === authority.fingerprint;
}

function approvedWorkingHead(authority: Record<string, unknown> | null): boolean {
  if (!authority || authority.origin !== "sniper-promoted"
      || authority.approvalCurrent !== true) return false;
  const coverage = objectValue(authority.readbackCoverage);
  const working = objectValue(authority.workingHead);
  const approved = objectValue(authority.approvedHead);
  return coverage?.complete === true
    && sameHead(working, authority)
    && sameHead(approved, authority)
    && stringValue(approved?.qcApprovalDigest) !== null
    && stringValue(approved?.exportHash) !== null;
}

function liveCandidate(producerDir: string, projectId: string): Record<string, unknown> | null {
  const candidate = candidateReceipt(producerDir);
  if (!candidate || candidate.schemaVersion !== 1 || candidate.projectId !== projectId) return null;
  if (!["staged", "edited", "qc-approved", "qc-rejected", "quarantined",
    "quarantined-recovered"].includes(String(candidate.status))) return null;
  return stringValue(candidate.timelineId) ? candidate : null;
}

function kindFromRecords(
  sidecar: Record<string, unknown>,
  authority: Record<string, unknown> | null,
  candidate: Record<string, unknown> | null,
  candidateApproved: boolean,
): PalmierProjectStateKind {
  if (candidate?.status === "quarantined"
      || candidate?.status === "quarantined-recovered") return "quarantined_candidate";
  if (candidate?.status === "qc-rejected") return "rejected_candidate";
  if (candidateApproved) return "approved_candidate";
  if (candidate) return "pending_candidate";
  const origin = stringValue(authority?.origin);
  const savedTimeline = stringValue(sidecar.latestTimelineId);
  if (origin === "palmier-manual") return "manual_working_head";
  if (approvedWorkingHead(authority)) return "approved_working_head";
  if (sidecar.workspaceMode === "managed-draft") {
    const draft = sidecar.draft as Record<string, unknown> | undefined;
    return draft?.assetKind === "saved-cut" ? "saved_cut" : "source_bootstrap";
  }
  const proof = sidecar.verification as Record<string, unknown> | undefined;
  if (proof?.ok === true && proof.timelineId === savedTimeline
      && authority?.approvalCurrent !== false) return "approved_mirror";
  return "previous_export";
}

function stateDetail(state: PalmierProjectStateKind): string {
  const copy: Record<PalmierProjectStateKind, string> = {
    no_workspace: "No managed Palmier workspace exists yet.",
    source_bootstrap: "Palmier contains a source-only bootstrap timeline, not the finished edit.",
    saved_cut: "Palmier contains the latest saved flat cut, which has not been delivery-approved.",
    approved_mirror: "Palmier contains the verified approved edit.",
    approved_working_head: "Palmier contains the exact editable timeline that passed QC and is both the current working head and approved head.",
    manual_working_head: "Palmier contains a newer manual revision that is now the working source of truth.",
    pending_candidate: "A review-only AI candidate is ready in Palmier; its parent remains canonical until the candidate passes QC and you choose to use it.",
    approved_candidate: "The review-only candidate passed current exported QC. It is not the working head until you deliberately use it.",
    rejected_candidate: "The rejected candidate is archived for diagnosis; the verified parent remains the Palmier working head.",
    quarantined_candidate: "A failed AI candidate is quarantined. Its preserved parent can be restored and verified safely.",
    previous_export: "Palmier contains a previous or stale export that is not the current approved edit.",
    unavailable: "The Palmier workspace record is incomplete or unreadable.",
  };
  return copy[state];
}

export function projectPalmierState(producerDir: string): PalmierProjectState {
  const sidecarPath = path.join(producerDir, "palmier.sync.json");
  if (!fs.existsSync(sidecarPath)) return emptyState("no_workspace");
  const sidecar = readObject(sidecarPath);
  const projectPath = stringValue(sidecar?.projectPath);
  const projectId = stringValue(sidecar?.projectId);
  const savedTimeline = stringValue(sidecar?.latestTimelineId);
  if (!sidecar || sidecar.schemaVersion !== 4 || !projectPath || !projectId
      || !savedTimeline || !fs.existsSync(projectPath)) {
    return emptyState("unavailable");
  }
  const authority = readObject(path.join(producerDir, "palmier.timeline-authority.json"));
  const approvedCandidate = currentApprovedCandidate(producerDir, projectId);
  const candidate = approvedCandidate ?? liveCandidate(producerDir, projectId);
  const qc = palmierCandidateQcState(producerDir);
  const state = kindFromRecords(sidecar, authority, candidate, approvedCandidate != null);
  const candidateBase = candidate?.base as Record<string, unknown> | undefined;
  const candidateTarget = candidate?.status === "quarantined"
    || candidate?.status === "quarantined-recovered" || candidate?.status === "qc-rejected"
    ? stringValue(candidateBase?.timelineId)
    : stringValue(candidate?.timelineId);
  const timelineId = candidateTarget ?? stringValue(authority?.timelineId) ?? savedTimeline;
  const approvedHead = authority?.approvedHead as Record<string, unknown> | undefined;
  const approvedTimelineId = stringValue(approvedHead?.timelineId);
  const detail = state === "manual_working_head" && approvedTimelineId
    ? `${stateDetail(state)} Last approved delivery: ${approvedTimelineId}.`
    : stateDetail(state);
  return {
    state,
    canOpen: true,
    projectPath,
    projectId,
    timelineId,
    verified: state === "approved_mirror" || state === "approved_working_head",
    authorityOrigin: stringValue(authority?.origin),
    approvedTimelineId,
    approvalCurrent: authority?.approvalCurrent === true,
    candidateQc: {
      state: qc.state, active: qc.run.active,
      action: qc.run.action,
      canRunQc: qc.canRunQc, canPromote: qc.canPromote,
      canDiscard: qc.canDiscard,
      step: qc.run.step, message: qc.run.message,
    },
    candidateApprovalStale: candidate?.status === "qc-approved" && approvedCandidate == null,
    detail,
  };
}

function emptyState(state: "no_workspace" | "unavailable"): PalmierProjectState {
  return {
    state,
    canOpen: false,
    projectPath: null,
    projectId: null,
    timelineId: null,
    verified: false,
    authorityOrigin: null,
    approvedTimelineId: null,
    approvalCurrent: false,
    candidateQc: undefined,
    candidateApprovalStale: false,
    detail: stateDetail(state),
  };
}
