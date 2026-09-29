/** Controller inspection for an external-media ASSET.json/origin pair. */
import { existsSync, lstatSync, readFileSync, realpathSync } from "node:fs";
import path from "node:path";
import { objectValue } from "@/lib/producer/contracts/validation";
import { fileSha256 } from "./auto-edit-hash";
import { readNativeAssetOrigin } from "./native-short-asset-use-origins";
import type { NativeAssetBinding } from "./native-short-strategy";
import { assertNativeWebCapture } from "./native-web-capture";

export interface ExternalMediaOriginInspection {
  schemaVersion: 1;
  status: "controller-authorized-for-local-review" | "prerequisite-rights-review";
  asset: { path: string; sha256: string; sizeBytes: number };
  origin: { path: string; sha256: string };
  authorizationEvidence: { path: string; sha256: string } | null;
}

function exactAsset(value: unknown): NativeAssetBinding {
  const row = objectValue(value, "external-media ASSET.json");
  const expected = ["file", "path", "sha256", "role", "origin",
    ...(row.webCapture === undefined ? [] : ["webCapture"])].sort();
  if (Object.keys(row).sort().join("\0") !== expected.join("\0")) {
    throw new Error("external-media ASSET.json has unsupported fields");
  }
  return row as unknown as NativeAssetBinding;
}

function canonicalAsset(asset: NativeAssetBinding, directory: string): void {
  if (!asset.origin || !["supporting-video", "image"].includes(asset.role)
      || !path.isAbsolute(asset.path) || realpathSync(asset.path) !== asset.path
      || path.dirname(asset.path) !== directory || fileSha256(asset.path) !== asset.sha256
      || !path.isAbsolute(asset.origin.path) || realpathSync(asset.origin.path) !== asset.origin.path
      || path.dirname(asset.origin.path) !== directory
      || path.basename(asset.origin.path) !== "ASSET-ORIGIN.json"
      || fileSha256(asset.origin.path) !== asset.origin.sha256) {
    throw new Error("external-media ASSET.json does not bind its sibling media and origin");
  }
}

function locallyAuthorized(receipt: ReturnType<typeof readNativeAssetOrigin>): boolean {
  const rights = receipt.record.rights;
  const unexpired = !rights.expiresAt || Date.parse(rights.expiresAt) > Date.now();
  return !["blocked", "expired"].includes(receipt.record.publicationDisposition)
    && unexpired
    && rights.allowedUses.includes("editorial")
    && rights.allowedPlatforms.includes("local-review");
}

/** Inspect only the standard sibling sidecar; this never upgrades rights status. */
export function inspectExternalMediaOrigin(sidecar: string): ExternalMediaOriginInspection {
  const file = realpathSync(sidecar), info = lstatSync(file);
  if (file !== sidecar || !info.isFile() || path.basename(file) !== "ASSET.json"
      || info.size < 2 || info.size > 1024 * 1024) {
    throw new Error("external-media ASSET.json must be a bounded canonical file");
  }
  const asset = exactAsset(JSON.parse(readFileSync(file, "utf8")));
  canonicalAsset(asset, path.dirname(file));
  const receipt = readNativeAssetOrigin(asset);
  if (asset.webCapture) assertNativeWebCapture(asset);
  const origin = asset.origin!;
  const authorizationEvidence = locallyAuthorized(receipt) ? origin : null;
  return { schemaVersion: 1, status: authorizationEvidence
    ? "controller-authorized-for-local-review" : "prerequisite-rights-review",
  asset: { path: asset.path, sha256: asset.sha256,
    sizeBytes: lstatSync(asset.path).size }, origin, authorizationEvidence };
}

function samePin(value: unknown, expected: { path: string; sha256: string } | null): boolean {
  if (expected === null) return value === undefined || value === null;
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  return Object.keys(row).sort().join("\0") === "path\0sha256"
    && row.path === expected.path && row.sha256 === expected.sha256;
}

function sourceSetEntries(manifestPath: string,
  manifest: Record<string, unknown>): Array<Record<string, unknown>> {
  const binding = objectValue(manifest.sourceSetAdmission,
    "external-media source-set binding");
  if (typeof binding.receiptPath !== "string"
      || typeof binding.receiptSha256 !== "string") {
    throw new Error("external-media source-set binding is malformed");
  }
  const receiptPath = path.resolve(path.dirname(manifestPath),
    binding.receiptPath);
  if (fileSha256(receiptPath) !== binding.receiptSha256) {
    throw new Error("external-media source-set receipt changed");
  }
  const receipt = objectValue(JSON.parse(readFileSync(receiptPath, "utf8")),
    "external-media source-set receipt");
  if (!Array.isArray(receipt.entries)) {
    throw new Error("external-media source-set receipt is malformed");
  }
  return receipt.entries.map(value => objectValue(value, "source-set entry"));
}

/** Re-derive manifest authorization from the sibling controller sidecar. */
export function assertManifestExternalOrigins(manifestPath: string,
  manifestValue?: unknown): void {
  const value = manifestValue ?? JSON.parse(readFileSync(manifestPath, "utf8"));
  const manifest = objectValue(value, "external-media manifest");
  const rows = manifest.externalMedia ?? [];
  if (!Array.isArray(rows) || rows.length > 128) {
    throw new Error("external-media manifest inventory is invalid");
  }
  const root = path.dirname(manifestPath);
  let entries: Array<Record<string, unknown>> | null = null;
  for (const value of rows) {
    const row = objectValue(value, "external-media manifest row");
    const original = row.originalPath;
    if (typeof original !== "string" || !path.isAbsolute(original)) {
      throw new Error("external-media manifest row lacks original path authority");
    }
    const sidecar = path.join(path.dirname(original), "ASSET.json");
    const inspection = existsSync(sidecar)
      ? inspectExternalMediaOrigin(realpathSync(sidecar)) : null;
    const expected = inspection?.authorizationEvidence ?? null;
    if (expected || row.authorizationEvidence) {
      entries ??= sourceSetEntries(manifestPath, manifest);
      const matches = entries.filter(entry => entry.lane === "external"
        && entry.originalPath === original
        && entry.snapshotPath === path.resolve(root, String(row.path))
        && entry.sha256 === row.sourceSha256);
      if (matches.length !== 1
          || !samePin(matches[0].authorizationEvidence, expected)) {
        throw new Error("external-media authorization differs from its source-set receipt");
      }
    }
    if (inspection && (inspection.asset.path !== original
        || inspection.asset.sha256 !== row.sourceSha256
        || inspection.asset.sizeBytes !== row.sourceSizeBytes)) {
      throw new Error("external-media sidecar differs from its manifest projection");
    }
    if (!samePin(row.authorizationEvidence, expected)) {
      throw new Error("external-media manifest authorization was not controller-derived");
    }
  }
}
