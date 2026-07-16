import {
  copyFileSync,
  cpSync,
  existsSync,
  mkdirSync,
  renameSync,
  rmSync,
  readFileSync,
  writeFileSync,
} from "fs";
import path from "path";
import { randomUUID } from "crypto";
import {
  approvalEvidenceValid,
  parseApprovalRecord,
  type ApprovalRecord,
} from "./auto-edit-approval";

export type {
  ApprovalRecord,
  AuditEvidenceAuthority,
  HashedArtifactRef,
  PlanningReviewEvidence,
  RenderedReviewEvidenceRef,
} from "./auto-edit-approval";

export const AUTO_EDIT_QC_DIR = ".sniper-qc";
export const AUTO_EDIT_APPROVAL_FILE = ".sniper-qc-approved.json";
export const AUTO_EDIT_PREVIEW_STALE_FILE = ".sniper-preview-stale.json";

function safeToken(token: string): string {
  return token.replace(/[^a-zA-Z0-9._-]/g, "_").slice(-96);
}

export function qcRoundDir(dir: string, token: string, round: number): string {
  return path.join(dir, AUTO_EDIT_QC_DIR, safeToken(token), `round-${round}`);
}

export function planningRoundDir(dir: string, token: string, round: number): string {
  return path.join(dir, AUTO_EDIT_QC_DIR, safeToken(token), "planning", `round-${round}`);
}

export function candidateFinalPath(dir: string, token: string, round: number): string {
  return path.join(qcRoundDir(dir, token, round), "final.mp4");
}

export function prepareQcRound(dir: string, token: string, round: number): string {
  const destination = qcRoundDir(dir, token, round);
  rmSync(destination, { recursive: true, force: true });
  mkdirSync(destination, { recursive: true });
  return destination;
}

export function copyAuditInputs(producerDir: string, candidateDir: string): void {
  const names = [
    "edit_plan.json",
    "timeline_map.json",
    "cover.png",
    "render_report.json",
    "captions.srt",
  ];
  for (const name of names) {
    const source = path.join(producerDir, name);
    if (existsSync(source)) copyFileSync(source, path.join(candidateDir, name));
  }
}

export function approvalPath(dir: string): string {
  return path.join(dir, AUTO_EDIT_APPROVAL_FILE);
}

export function readApproval(dir: string): ApprovalRecord | null {
  try {
    const value = parseApprovalRecord(JSON.parse(readFileSync(approvalPath(dir), "utf8")) as unknown);
    const finalPath = path.join(dir, "final.mp4");
    return value && approvalEvidenceValid(dir, finalPath, value) ? value : null;
  } catch {
    return null;
  }
}

export function clearQcApproval(dir: string): void {
  rmSync(approvalPath(dir), { force: true });
}

export function previewStalePath(dir: string): string {
  return path.join(dir, AUTO_EDIT_PREVIEW_STALE_FILE);
}

export function previewAuthorityInvalidated(dir: string): boolean {
  return existsSync(previewStalePath(dir));
}

/** Durable fail-closed marker; only a later approved promotion removes it. */
export function invalidateApprovedPreview(dir: string, reason: string): void {
  const destination = previewStalePath(dir);
  const temporary = `${destination}.${randomUUID()}.tmp`;
  try {
    writeFileSync(temporary, `${JSON.stringify({
      schemaVersion: 1,
      invalidatedAt: new Date().toISOString(),
      reason,
    }, null, 2)}\n`, { flag: "wx", mode: 0o600 });
    renameSync(temporary, destination);
    clearQcApproval(dir);
  } finally {
    rmSync(temporary, { force: true });
  }
}

function moveIfPresent(source: string, destination: string): void {
  if (!existsSync(source)) return;
  rmSync(destination, { recursive: true, force: true });
  renameSync(source, destination);
}

function promoteDiagnostics(candidateDir: string, producerDir: string): void {
  for (const name of ["audit_report.json", "audit_report.md", "graphics_placements.json"]) {
    const source = path.join(candidateDir, name);
    const destination = path.join(producerDir, name);
    rmSync(destination, { recursive: true, force: true });
    if (existsSync(source)) cpSync(source, destination, { recursive: true, force: true });
  }
  const frames = path.join(candidateDir, "audit_frames");
  const framesDestination = path.join(producerDir, "audit_frames");
  rmSync(framesDestination, { recursive: true, force: true });
  if (existsSync(frames)) cpSync(frames, framesDestination, {
    recursive: true, force: true,
  });
}

function promoteMedia(candidate: string, producerDir: string): void {
  const candidateProof = `${candidate}.assembled.json`;
  const candidateProxy = candidate.replace(/\.mp4$/, ".proxy.mp4");
  moveIfPresent(candidate, path.join(producerDir, "final.mp4"));
  moveIfPresent(candidateProof, path.join(producerDir, "final.mp4.assembled.json"));
  moveIfPresent(candidateProxy, path.join(producerDir, "final.proxy.mp4"));
}

function assertPromotionAuthority(candidate: string, producerDir: string, record: ApprovalRecord): void {
  if (!existsSync(candidate) || !existsSync(`${candidate}.assembled.json`)) {
    throw new Error("approved candidate or its assembly authority proof is missing");
  }
  if (!approvalEvidenceValid(producerDir, candidate, record)) {
    throw new Error("approved candidate or its QC evidence does not match the approval record");
  }
}

function writeApproval(dir: string, record: ApprovalRecord): void {
  const destination = approvalPath(dir);
  const temporary = `${destination}.${randomUUID()}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(record, null, 2)}\n`, { flag: "wx", mode: 0o600 });
  renameSync(temporary, destination);
  rmSync(previewStalePath(dir), { force: true });
}

export function writeQualityJson(destination: string, value: unknown): string {
  mkdirSync(path.dirname(destination), { recursive: true });
  const temporary = `${destination}.${randomUUID()}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { flag: "wx", mode: 0o600 });
  renameSync(temporary, destination);
  return destination;
}

export function promoteApprovedCandidate(
  candidate: string,
  producerDir: string,
  record: ApprovalRecord,
): void {
  assertPromotionAuthority(candidate, producerDir, record);
  const candidateDir = path.dirname(candidate);
  promoteMedia(candidate, producerDir);
  promoteDiagnostics(candidateDir, producerDir);
  writeApproval(producerDir, record);
}

export function preserveReviewArtifact(source: string, destination: string): void {
  mkdirSync(path.dirname(destination), { recursive: true });
  if (existsSync(source)) cpSync(source, destination, { recursive: true, force: true });
}
