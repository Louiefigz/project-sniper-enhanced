import {
  existsSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { AUTO_EDIT_QUALITY_POLICY_VERSION } from "./auto-edit-authority-snapshot";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import { autoEditRequestKey } from "./auto-edit-hash";
import { validAutoEditPipelineAuthority } from "./auto-edit-pipeline-authority";

export const AUTO_EDIT_QUALITY_POLICY_FILE = ".sniper-quality-policy.json";

export type AutoEditQualityPolicyMarker =
  | {
    schemaVersion: 1;
    mode: "managed";
    qualityPolicyVersion: typeof AUTO_EDIT_QUALITY_POLICY_VERSION;
    activatedAt: string;
    requestKey: string;
    ctx: AutoEditCtx;
  }
  | {
    schemaVersion: 1;
    mode: "legacy";
    migratedAt: string;
    reason: string;
  };

export function qualityPolicyMarkerPath(dir: string): string {
  return path.join(dir, AUTO_EDIT_QUALITY_POLICY_FILE);
}

function validMarker(value: unknown): value is AutoEditQualityPolicyMarker {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  if (row.schemaVersion !== 1) return false;
  if (row.mode === "managed") {
    const ctx = row.ctx as Partial<AutoEditCtx> | undefined;
    const structurallyValid = row.qualityPolicyVersion === AUTO_EDIT_QUALITY_POLICY_VERSION
      && typeof row.activatedAt === "string"
      && typeof row.requestKey === "string" && !!row.requestKey
      && !!ctx && typeof ctx === "object"
      && typeof ctx.dir === "string"
      && typeof ctx.planPath === "string"
      && typeof ctx.manifestPath === "string"
      && typeof ctx.transcriptsDir === "string";
    return structurallyValid && (!ctx.pipeline || validAutoEditPipelineAuthority(ctx.pipeline))
      && autoEditRequestKey(ctx as AutoEditCtx) === row.requestKey;
  }
  return row.mode === "legacy"
    && typeof row.migratedAt === "string"
    && typeof row.reason === "string" && !!row.reason;
}

export function readQualityPolicyMarker(dir: string): AutoEditQualityPolicyMarker | null {
  try {
    const value: unknown = JSON.parse(readFileSync(qualityPolicyMarkerPath(dir), "utf8"));
    return validMarker(value) ? value : null;
  } catch {
    return null;
  }
}

function writeMarker(dir: string, marker: AutoEditQualityPolicyMarker): void {
  const destination = qualityPolicyMarkerPath(dir);
  const temporary = `${destination}.${randomUUID()}.tmp`;
  try {
    writeFileSync(temporary, `${JSON.stringify(marker, null, 2)}\n`, { flag: "wx", mode: 0o600 });
    renameSync(temporary, destination);
  } finally {
    rmSync(temporary, { force: true });
  }
}

/** Persist the QC policy independently of the mutable worker journal. */
export function activateManagedQualityPolicy(dir: string, requestKey: string, ctx: AutoEditCtx): void {
  const markerPath = qualityPolicyMarkerPath(dir);
  if (existsSync(markerPath) && !readQualityPolicyMarker(dir)) {
    throw new Error(`quality-policy marker is corrupt: ${markerPath}`);
  }
  const existing = readQualityPolicyMarker(dir);
  writeMarker(dir, {
    schemaVersion: 1,
    mode: "managed",
    qualityPolicyVersion: AUTO_EDIT_QUALITY_POLICY_VERSION,
    activatedAt: existing?.mode === "managed" ? existing.activatedAt : new Date().toISOString(),
    requestKey,
    ctx,
  });
}

/**
 * Explicit one-time migration for outputs created before policy-v1 existed.
 * Callers must prove the project is actually legacy before invoking this.
 */
export function markLegacyQualityPolicy(dir: string, reason: string): void {
  if (!reason.trim()) throw new Error("legacy quality-policy migration requires a reason");
  if (existsSync(qualityPolicyMarkerPath(dir))) {
    throw new Error("quality-policy marker already exists; refusing to downgrade it");
  }
  writeMarker(dir, {
    schemaVersion: 1,
    mode: "legacy",
    migratedAt: new Date().toISOString(),
    reason: reason.trim(),
  });
}

export interface QualityPolicyRequirement {
  required: boolean;
  legacy: boolean;
  valid: boolean;
  reason: string | null;
}

/** Missing/corrupt policy state never means "legacy". */
export function qualityPolicyRequirement(dir: string): QualityPolicyRequirement {
  const markerPath = qualityPolicyMarkerPath(dir);
  if (!existsSync(markerPath)) {
    return {
      required: true,
      legacy: false,
      valid: false,
      reason: `quality-policy marker is missing: ${markerPath}`,
    };
  }
  const marker = readQualityPolicyMarker(dir);
  if (!marker) {
    return {
      required: true,
      legacy: false,
      valid: false,
      reason: `quality-policy marker is invalid: ${markerPath}`,
    };
  }
  return marker.mode === "legacy"
    ? { required: false, legacy: true, valid: true, reason: null }
    : { required: true, legacy: false, valid: true, reason: null };
}
