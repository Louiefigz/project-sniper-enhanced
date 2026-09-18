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
import { fileSha256 } from "./auto-edit-hash";
import { QC_PROMOTION_RECONCILIATION_FILE } from
  "./ask-editor-reconciliation";

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
export const AUTO_EDIT_PROMOTION_RECONCILIATION_FILE =
  QC_PROMOTION_RECONCILIATION_FILE;

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

/** Parse a candidate's .assembled.json; null unless every reuse hash is present. */
function readSeedSidecar(sidecarPath: string): { raw: string; authorityHash: string } | null {
  try {
    const raw = readFileSync(sidecarPath, "utf8");
    const value = JSON.parse(raw) as Record<string, unknown>;
    const authorityHash = value.authorityHash;
    const reuseHashes = [value.videoFingerprint, value.graphicsFingerprint, value.planHash];
    if (typeof authorityHash !== "string" || !authorityHash) return null;
    if (reuseHashes.some((hash) => typeof hash !== "string" || !hash)) return null;
    return { raw, authorityHash };
  } catch {
    return null;
  }
}

/**
 * Does this plan carry produced graphics? The prior round dir holds the exact
 * plan that produced its candidate (copyAuditInputs); the producer dir holds
 * the CURRENT plan the repair just authored. A non-empty graphicsTrack means
 * the composite wrote a placements sidecar that Audit B's fail-closed
 * eye_trace gate requires in every round dir the mux fast path reuses. An
 * unreadable plan is unknown provenance → null (the caller fails closed).
 */
function planHasGraphics(planPath: string): boolean | null {
  try {
    const raw = readFileSync(planPath, "utf8");
    const track = (JSON.parse(raw) as Record<string, unknown>).graphicsTrack;
    return Array.isArray(track) && track.length > 0;
  } catch {
    return null;
  }
}

/**
 * Seed a fresh QC round with the prior round's composited final.mp4 + its
 * .assembled.json provenance so an audio-only repair can take assemble.py's
 * mux fast path (~12s) instead of a full composite (~70-86s). HASH-BOUND
 * fail-closed: the seed lands only when the prior sidecar carries every reuse
 * hash and its recorded authorityHash matches the copied bytes exactly;
 * assemble.py's _reuse_composite then independently requires the sidecar's
 * video/graphics fingerprints to match the CURRENT plan before muxing. A
 * prior round with produced graphics must also contribute its
 * graphics_placements.json (Audit B's eye_trace evidence — the mux fast path
 * skips the composite that would rewrite it; a changed graphicsTrack forces
 * the full composite, which overwrites the copy) — but ONLY when the CURRENT
 * plan still has graphics: a repair that removed every graphic takes the
 * empty-track passthrough, which never rewrites the sidecar, so seeding it
 * would promote the prior round's stale placements as this round's evidence.
 * Any mismatch, missing file/evidence, unreadable prior or current plan, or
 * torn copy leaves the round unseeded — assemble falls back to the full
 * composite (correct but slow).
 */
export function seedQcRoundFromPriorCandidate(dir: string, token: string, round: number): boolean {
  if (round <= 1) return false;
  const source = candidateFinalPath(dir, token, round - 1);
  const sidecar = readSeedSidecar(`${source}.assembled.json`);
  if (!sidecar || !existsSync(source)) return false;
  const sourceDir = path.dirname(source);
  const priorHasGraphics = planHasGraphics(path.join(sourceDir, "edit_plan.json"));
  const currentHasGraphics = planHasGraphics(path.join(dir, "edit_plan.json"));
  if (priorHasGraphics === null || currentHasGraphics === null) return false;
  const placementsSource = path.join(sourceDir, "graphics_placements.json");
  if (priorHasGraphics && !existsSync(placementsSource)) return false;
  const requiresPlacements = priorHasGraphics && currentHasGraphics;
  const destination = candidateFinalPath(dir, token, round);
  const placementsDestination = path.join(path.dirname(destination), "graphics_placements.json");
  const temporary = `${destination}.${randomUUID()}.seed.tmp`;
  try {
    copyFileSync(source, temporary);
    if (fileSha256(temporary) !== sidecar.authorityHash) {
      throw new Error("seeded candidate bytes do not match the prior authority proof");
    }
    renameSync(temporary, destination);
    writeFileSync(`${destination}.assembled.json`, sidecar.raw, { mode: 0o600 });
    if (requiresPlacements) copyFileSync(placementsSource, placementsDestination);
    return true;
  } catch {
    rmSync(placementsDestination, { force: true });
    rmSync(`${destination}.assembled.json`, { force: true });
    rmSync(destination, { force: true });
    return false;
  } finally {
    rmSync(temporary, { force: true });
  }
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

export function assertPromotionAuthority(candidate: string, producerDir: string, record: ApprovalRecord): void {
  if (!existsSync(candidate) || !existsSync(`${candidate}.assembled.json`)) {
    throw new Error("approved candidate or its assembly authority proof is missing");
  }
  if (!approvalEvidenceValid(producerDir, candidate, record)) {
    throw new Error("approved candidate or its QC evidence does not match the approval record");
  }
}

export function writeQualityJson(destination: string, value: unknown): string {
  mkdirSync(path.dirname(destination), { recursive: true });
  const temporary = `${destination}.${randomUUID()}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { flag: "wx", mode: 0o600 });
  renameSync(temporary, destination);
  return destination;
}

export function preserveReviewArtifact(source: string, destination: string): void {
  mkdirSync(path.dirname(destination), { recursive: true });
  if (existsSync(source)) cpSync(source, destination, { recursive: true, force: true });
}

export {
  candidatePromotionTransactionId,
  promoteApprovedCandidate,
  recoverApprovedCandidatePromotionSync,
  type CandidatePromotionHooks,
} from "./auto-edit-candidate-promotion";
