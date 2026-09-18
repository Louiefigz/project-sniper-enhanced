import { existsSync } from "fs";
import path from "node:path";
import { palmierStatePath, readJsonObject } from "../_lib";
import { currentApprovedCandidate } from "@/lib/server/palmier-candidate-qc";

export type PalmierViewKind =
  | "pending-candidate"
  | "approved-candidate"
  | "rejected-candidate"
  | "quarantined-candidate"
  | "working-head"
  | "working-draft"
  | "verified-mirror"
  | "previous-mirror";

export interface PalmierViewTarget {
  projectPath: string;
  timelineId: string;
  ownership: "sniper" | "palmier";
  kind: PalmierViewKind;
  verified: boolean;
  workingAssetKind: "saved-cut" | "source" | null;
}

interface PalmierViewError {
  error: string;
  status: number;
}

/** Resolve a managed Palmier timeline without claiming that it is current. */
export function loadViewTarget(dir: string): PalmierViewTarget | PalmierViewError {
  const state = readJsonObject(palmierStatePath(dir));
  if (!state || state.schemaVersion !== 4) {
    return { error: "No managed Palmier workspace exists for this project yet.", status: 409 };
  }
  const ownership = state.ownership === "palmier"
    ? "palmier"
    : state.ownership === "sniper" || state.ownership === undefined ? "sniper" : null;
  const projectPath = typeof state.projectPath === "string" && existsSync(state.projectPath)
    ? state.projectPath : null;
  const savedTimelineId = typeof state.latestTimelineId === "string" ? state.latestTimelineId : null;
  const authority = readJsonObject(path.join(dir, "palmier.timeline-authority.json"));
  const candidate = readJsonObject(path.join(dir, "palmier.timeline-candidate.json"));
  const candidateTarget = candidateViewTarget(
    candidate,
    state.projectId,
    currentApprovedCandidate(dir, typeof state.projectId === "string" ? state.projectId : null) != null,
  );
  const draft = state.workspaceMode === "managed-draft";
  const authorityOrigin = authority?.origin;
  const authorityIsCurrent = draft || authorityOrigin === "palmier-manual"
    || authorityOrigin === "sniper-promoted";
  const workingTimelineId = authorityIsCurrent && authority && authority.projectId === state.projectId
    && typeof authority.timelineId === "string" ? authority.timelineId : null;
  const timelineId = candidateTarget?.timelineId ?? workingTimelineId ?? savedTimelineId;
  const mirror = state.workspaceMode === "verified-mirror" || state.mirrorMode === "visual-master";
  if (!ownership || !projectPath || !timelineId || (!draft && !mirror)) {
    return { error: "The managed Palmier workspace record is incomplete.", status: 409 };
  }
  const proof = asObject(state.verification);
  const verified = mirror && proof?.ok === true && proof.timelineId === timelineId;
  const fallbackKind: PalmierViewKind = workingTimelineId && workingTimelineId !== savedTimelineId
    ? "working-head" : draft
      ? "working-draft" : verified ? "verified-mirror" : "previous-mirror";
  const kind = candidateTarget?.kind ?? fallbackKind;
  const assetKind = asObject(state.draft)?.assetKind;
  const workingAssetKind = assetKind === "saved-cut" ? "saved-cut"
    : assetKind === "source" ? "source" : null;
  return { projectPath, timelineId, ownership, kind, verified, workingAssetKind };
}

function candidateViewTarget(
  candidate: Record<string, unknown> | null,
  projectId: unknown,
  approved: boolean,
): { timelineId: string; kind: PalmierViewKind } | null {
  if (!candidate || candidate.schemaVersion !== 1 || candidate.projectId !== projectId) return null;
  if (candidate.status === "quarantined" || candidate.status === "quarantined-recovered") {
    const base = asObject(candidate.base);
    if (!base || base.projectId !== projectId || typeof base.timelineId !== "string") return null;
    return { timelineId: base.timelineId, kind: "quarantined-candidate" };
  }
  if (candidate.status === "qc-rejected") {
    const base = asObject(candidate.base);
    if (!base || base.projectId !== projectId || typeof base.timelineId !== "string") return null;
    return { timelineId: base.timelineId, kind: "rejected-candidate" };
  }
  if (candidate.status === "qc-approved" && typeof candidate.timelineId === "string") {
    return { timelineId: candidate.timelineId,
      kind: approved ? "approved-candidate" : "pending-candidate" };
  }
  if (candidate.status !== "staged" && candidate.status !== "edited") return null;
  const qc = asObject(candidate.qc);
  if (qc?.approved === true) return null;
  return typeof candidate.timelineId === "string"
    ? { timelineId: candidate.timelineId, kind: "pending-candidate" } : null;
}

function asObject(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}
