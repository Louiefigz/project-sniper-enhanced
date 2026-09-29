/** Controller-owned metadata authority for admitted footage and supporting media. */
import { createHash } from "node:crypto";
import { realpathSync } from "node:fs";
import path from "node:path";
import { atomicWriteJsonSync } from "@/lib/server/atomic-file";
import { canonicalJson, fileSha256 } from "@/lib/server/auto-edit-hash";
import { stableAuthorityHash } from "@/lib/server/auto-edit-authority-snapshot";
import { readBoundedAuthoringFile } from "./initial-authoring-capture";
import type { AutoEditCtx } from "./stream";
import type { VisualPlanAuthorityPin } from "./visual-plan-word-authority";
import type { VisualPlanProjectAuthority } from "./visual-plan-context";
import { validateExternalAuthorization, validateMediaAdmissionReceipt } from
  "./visual-plan-media-receipt";

const MAX_MANIFEST_BYTES = 16 * 1024 * 1024;
const MAX_SOURCE_SET_BYTES = 4 * 1024 * 1024;
const MAX_SOURCES = 64;
const MAX_SUPPORTING = 128;
const MAX_SOURCE_SET_ENTRIES = 256;
const SHA256 = /^[a-f0-9]{64}$/;
const STABLE_ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;
const SOURCE_SET_POLICY = "sniper-producer-source-set-v1";

type MediaModality = "source-footage" | "supplied-broll" | "external-media";
type SourceSetLane = "source" | "broll" | "external" | "music";

interface SourceSetEntry {
  lane: SourceSetLane;
  originalPath: string;
  snapshotPath: string;
  sha256: string;
  sizeBytes: number;
  mediaKind: string;
  admissionReceiptPath: string;
  admissionReceiptSha256: string;
  authorizationEvidence?: { path: string; sha256: string } | null;
}

interface SourceSetAuthority {
  binding: { schemaVersion: 1; receiptPath: string; receiptSha256: string;
    sourceSetDigest: string; entryCount: number };
  entries: SourceSetEntry[];
}

interface MediaAuthorityItem {
  modality: MediaModality;
  recordId: string;
  path: string;
  sourceSha256: string;
  sourceSetLane: "source" | "broll" | "external";
  originalPath: string;
  sourceSetEvidence: { path: string; sha256: string };
  authorizationEvidence: { path: string; sha256: string } | null;
}

function object(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function exactKeys(row: Record<string, unknown>, keys: string[], label: string): void {
  if (Object.keys(row).sort().join("\0") !== [...keys].sort().join("\0")) {
    throw new Error(`${label} has invalid keys`);
  }
}

function compareCodePoints(left: string, right: string): number {
  const a = Array.from(left, value => value.codePointAt(0)!);
  const b = Array.from(right, value => value.codePointAt(0)!);
  for (let index = 0; index < Math.min(a.length, b.length); index += 1) {
    if (a[index] !== b[index]) return a[index] - b[index];
  }
  return a.length - b.length;
}

function asciiCanonicalBytes(value: unknown): Buffer {
  const ascii = canonicalJson(value).replace(/[^\x00-\x7f]/g, character =>
    `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`);
  return Buffer.from(`${ascii}\n`, "ascii");
}

function sourceSetDigest(entries: SourceSetEntry[]): string {
  return createHash("sha256").update("sniper-producer-source-set-v1\0")
    .update(asciiCanonicalBytes(entries)).digest("hex");
}

function pinnedJson(file: string, expected: string, label: string,
  maximum: number): Record<string, unknown> {
  const bytes = readBoundedAuthoringFile(file, label, maximum);
  if (createHash("sha256").update(bytes).digest("hex") !== expected) {
    throw new Error(`${label} hash differs from its controller pin`);
  }
  let value: Record<string, unknown>;
  try { value = object(JSON.parse(bytes.toString("utf8")), label); }
  catch (error) { throw new Error(`${label} must be UTF-8 JSON: ${(error as Error).message}`); }
  if (!bytes.equals(asciiCanonicalBytes(value))) {
    throw new Error(`${label} must use canonical receipt bytes`);
  }
  return value;
}

function sourceSetEntry(value: unknown, root: string): SourceSetEntry {
  const row = object(value, "source-set entry");
  const baseKeys = ["lane", "originalPath", "snapshotPath", "sha256", "sizeBytes",
    "mediaKind", "admissionReceiptPath", "admissionReceiptSha256"];
  const keys = Object.hasOwn(row, "authorizationEvidence")
    ? [...baseKeys, "authorizationEvidence"] : baseKeys;
  exactKeys(row, keys, "source-set entry");
  const lane = row.lane, original = row.originalPath, snapshot = row.snapshotPath;
  const sha256 = row.sha256, size = row.sizeBytes, kind = row.mediaKind;
  const receipt = row.admissionReceiptPath, receiptSha = row.admissionReceiptSha256;
  if (!["source", "broll", "external", "music"].includes(String(lane))
      || typeof original !== "string" || !path.isAbsolute(original)
      || typeof snapshot !== "string" || !path.isAbsolute(snapshot)
      || typeof sha256 !== "string" || !SHA256.test(sha256)
      || !Number.isSafeInteger(size) || Number(size) < 0
      || typeof kind !== "string" || !kind
      || typeof receiptSha !== "string" || !SHA256.test(receiptSha)
      || receipt !== `.sniper-external-media/receipts/${receiptSha}.json`
      || path.resolve(root, String(receipt)) !== path.join(
        root, ".sniper-external-media", "receipts", `${receiptSha}.json`)) {
    throw new Error("source-set entry identity is malformed");
  }
  let canonicalStore: string;
  try { canonicalStore = realpathSync(path.dirname(path.dirname(snapshot))); }
  catch { throw new Error("source-set entry identity is malformed"); }
  if (path.basename(snapshot) !== `${sha256}.media`
      || path.basename(path.dirname(snapshot)) !== ".sniper-external-media"
      || canonicalStore !== root) {
    throw new Error("source-set entry identity is malformed");
  }
  validateMediaAdmissionReceipt(path.resolve(root, String(receipt)), receiptSha, {
    snapshotPath: snapshot, sha256, sizeBytes: Number(size), mediaKind: kind,
  });
  sourceSetAuthorization(row, root);
  return row as unknown as SourceSetEntry;
}

function sourceSetAuthorization(row: Record<string, unknown>, root: string):
  { path: string; sha256: string } | null {
  const raw = row.authorizationEvidence;
  if (raw === undefined || raw === null) return null;
  if (row.lane !== "external") {
    throw new Error("only external source-set entries may bind authorization evidence");
  }
  const pin = object(raw, "source-set authorization evidence");
  exactKeys(pin, ["path", "sha256"], "source-set authorization evidence");
  if (typeof pin.path !== "string" || !pin.path || typeof pin.sha256 !== "string"
      || !SHA256.test(pin.sha256)) {
    throw new Error("source-set authorization evidence is malformed");
  }
  const file = path.resolve(root, pin.path);
  validateExternalAuthorization(file, pin.sha256, String(row.sha256));
  return { path: realpathSync(file), sha256: pin.sha256 };
}

function sourceSetAuthority(manifest: Record<string, unknown>, root: string): SourceSetAuthority {
  const binding = object(manifest.sourceSetAdmission, "manifest source-set admission");
  const keys = ["schemaVersion", "receiptPath", "receiptSha256", "sourceSetDigest", "entryCount"];
  exactKeys(binding, keys, "manifest source-set admission");
  const receiptSha = binding.receiptSha256, digest = binding.sourceSetDigest;
  if (binding.schemaVersion !== 1 || typeof receiptSha !== "string" || !SHA256.test(receiptSha)
      || typeof digest !== "string" || !SHA256.test(digest)
      || binding.receiptPath !== `.sniper-source-sets/${receiptSha}.json`
      || !Number.isSafeInteger(binding.entryCount) || Number(binding.entryCount) < 1
      || Number(binding.entryCount) > MAX_SOURCE_SET_ENTRIES) {
    throw new Error("manifest source-set admission is malformed");
  }
  const receiptPath = path.join(root, ".sniper-source-sets", `${receiptSha}.json`);
  const receipt = pinnedJson(receiptPath, receiptSha, "source-set receipt", MAX_SOURCE_SET_BYTES);
  exactKeys(receipt, ["schemaVersion", "policy", "entries", "sourceSetDigest"], "source-set receipt");
  if (receipt.schemaVersion !== 1 || receipt.policy !== SOURCE_SET_POLICY
      || !Array.isArray(receipt.entries) || receipt.entries.length !== binding.entryCount) {
    throw new Error("source-set receipt differs from its manifest binding");
  }
  const entries = receipt.entries.map(value => sourceSetEntry(value, root));
  const ordered = [...entries].sort((left, right) =>
    compareCodePoints(`${left.lane}\0${left.originalPath}`,
      `${right.lane}\0${right.originalPath}`));
  const expectedDigest = sourceSetDigest(ordered);
  if (JSON.stringify(entries) !== JSON.stringify(ordered)
      || receipt.sourceSetDigest !== expectedDigest || binding.sourceSetDigest !== expectedDigest) {
    throw new Error("source-set receipt digest or ordering is stale");
  }
  return { binding: { schemaVersion: 1, receiptPath, receiptSha256: receiptSha,
    sourceSetDigest: expectedDigest, entryCount: entries.length }, entries };
}

function manifestItem(value: unknown, modality: MediaModality,
  lane: "source" | "broll" | "external",
  root: string, entries: SourceSetEntry[]): MediaAuthorityItem {
  const row = object(value, `${modality} manifest row`);
  const id = row.id, rawPath = row.path, sha = row.sourceSha256;
  const original = row.originalPath, receipt = row.admissionReceiptPath;
  const receiptSha = row.admissionReceiptSha256;
  if (typeof id !== "string" || !STABLE_ID.test(id)
      || typeof rawPath !== "string" || !rawPath || rawPath.includes("\0")
      || typeof sha !== "string" || !SHA256.test(sha)
      || typeof original !== "string" || !path.isAbsolute(original)
      || typeof receiptSha !== "string" || !SHA256.test(receiptSha)
      || receipt !== `.sniper-external-media/receipts/${receiptSha}.json`) {
    throw new Error(`${modality} manifest row lacks source-set identity`);
  }
  const absolute = path.resolve(root, rawPath);
  const entry = entries.find(item => item.lane === lane && item.originalPath === original
    && item.snapshotPath === absolute && item.sha256 === sha
    && item.admissionReceiptPath === receipt && item.admissionReceiptSha256 === receiptSha);
  if (!entry) throw new Error(`${modality} manifest row is absent from source-set receipt`);
  const authorizationEvidence = sourceSetAuthorization(
    entry as unknown as Record<string, unknown>, root);
  const manifestAuthorization = row.authorizationEvidence ?? null;
  const boundAuthorization = entry.authorizationEvidence ?? null;
  if (JSON.stringify(manifestAuthorization) !== JSON.stringify(boundAuthorization)) {
    throw new Error(`${modality} manifest authorization differs from its source-set receipt`);
  }
  return { modality, recordId: id, path: absolute, sourceSha256: sha,
    sourceSetLane: lane, originalPath: original,
    sourceSetEvidence: { path: path.resolve(root, receipt), sha256: receiptSha },
    authorizationEvidence };
}

function inventory(manifest: Record<string, unknown>, root: string,
  sourceSet: SourceSetAuthority): MediaAuthorityItem[] {
  const specs = [
    ["sources", "source-footage", "source", MAX_SOURCES, true],
    ["broll", "supplied-broll", "broll", MAX_SUPPORTING, false],
    ["externalMedia", "external-media", "external", MAX_SUPPORTING, false],
  ] as const;
  const items: MediaAuthorityItem[] = [];
  for (const [key, modality, lane, maximum, required] of specs) {
    const value = manifest[key] ?? [];
    if (!Array.isArray(value) || value.length > maximum || (required && !value.length)) {
      throw new Error(`visual-plan ${key} inventory exceeds its bound`);
    }
    items.push(...value.map(row => manifestItem(row, modality, lane, root, sourceSet.entries)));
  }
  items.sort((left, right) => compareCodePoints(
    `${left.modality}\0${left.recordId}`, `${right.modality}\0${right.recordId}`));
  const keys = items.map(item => `${item.modality}\0${item.recordId}`);
  const receipts = items.map(item => `${item.sourceSetLane}\0${item.originalPath}`);
  if (new Set(keys).size !== keys.length || new Set(receipts).size !== receipts.length) {
    throw new Error("visual-plan media inventory contains duplicate controller identities");
  }
  return items;
}

function manifestDocument(ctx: AutoEditCtx): {
  value: Record<string, unknown>; path: string; sha256: string;
} {
  const bytes = readBoundedAuthoringFile(
    ctx.manifestPath, "visual-plan media manifest", MAX_MANIFEST_BYTES,
  );
  let value: Record<string, unknown>;
  try { value = object(JSON.parse(bytes.toString("utf8")), "visual-plan media manifest"); }
  catch (error) {
    throw new Error(`visual-plan media manifest must be UTF-8 JSON: ${(error as Error).message}`);
  }
  return { value, path: realpathSync(ctx.manifestPath),
    sha256: createHash("sha256").update(bytes).digest("hex") };
}

/** Freeze source-set metadata and receipts only; this never opens media files. */
export function prepareVisualMediaAuthority(ctx: AutoEditCtx,
  project: VisualPlanProjectAuthority, destination: string): VisualPlanAuthorityPin {
  const manifest = manifestDocument(ctx), root = path.dirname(manifest.path);
  const sourceSet = sourceSetAuthority(manifest.value, root);
  const items = inventory(manifest.value, root, sourceSet);
  const core = { schemaVersion: 1 as const, kind: "visual-plan-media-authority" as const,
    project: { acceptedProgramSha256: project.acceptedProgramSha256,
      transcriptSha256: project.transcriptSha256 },
    manifest: { path: manifest.path, sha256: manifest.sha256 },
    sourceSetAdmission: sourceSet.binding,
    inventoryCount: items.length, inventory: items };
  const value = { ...core, digest: stableAuthorityHash(core) };
  atomicWriteJsonSync(destination, value);
  const sha256 = fileSha256(destination);
  if (!sha256) throw new Error("visual-plan media authority was not materialized");
  return { schemaVersion: 1, path: realpathSync(destination), sha256,
    digest: value.digest };
}
