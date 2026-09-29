import { createHash } from "node:crypto";
import { copyFileSync, mkdirSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { canonicalJson, fileSha256 } from "../../server/auto-edit-hash";

type Lane = "source" | "broll" | "external";

export interface FixtureMediaRow {
  id: string;
  path: string;
  transcriptPath?: string;
  authorizationEvidence?: { path: string; sha256: string };
}

export interface FixtureMediaManifest {
  sources: FixtureMediaRow[];
  broll?: FixtureMediaRow[];
  externalMedia?: FixtureMediaRow[];
}

function canonicalBytes(value: unknown): Buffer {
  const ascii = canonicalJson(value).replace(/[^\x00-\x7f]/g, character =>
    `\\u${character.charCodeAt(0).toString(16).padStart(4, "0")}`);
  return Buffer.from(`${ascii}\n`, "ascii");
}

function compareCodePoints(left: string, right: string): number {
  const a = Array.from(left, value => value.codePointAt(0)!);
  const b = Array.from(right, value => value.codePointAt(0)!);
  for (let index = 0; index < Math.min(a.length, b.length); index += 1) {
    if (a[index] !== b[index]) return a[index] - b[index];
  }
  return a.length - b.length;
}

function digest(value: Buffer): string {
  return createHash("sha256").update(value).digest("hex");
}

function admittedRows(root: string, lane: Lane,
  rows: FixtureMediaRow[], entries: Record<string, unknown>[]): Record<string, unknown>[] {
  const store = path.join(root, ".sniper-external-media");
  const receipts = path.join(store, "receipts");
  mkdirSync(receipts, { recursive: true });
  return rows.map((row) => {
    const sha256 = fileSha256(row.path)!;
    const snapshot = path.join(store, `${sha256}.media`);
    copyFileSync(row.path, snapshot);
    const sizeBytes = statSync(snapshot).size;
    const receiptBytes = canonicalBytes({ schemaVersion: 1,
      policy: "sniper-external-media-probe-v3",
      snapshot: { path: snapshot, sha256, sizeBytes },
      limits: { max_bytes: 16 * 1024 ** 3, max_width: 8192, max_height: 8192,
        max_frames: 2_000_000, max_duration_seconds: 6 * 60 * 60,
        max_streams: 32, max_decode_seconds: 20 * 60 },
      image: { imageId: `sha256:${"a".repeat(64)}` },
      isolation: { networkMode: "none" }, network: { schemaVersion: 1 },
      decoded: { schemaVersion: 1, ok: true, decoded: true, facts: {
        mediaKind: "timed-media", durationSeconds: 1, sizeBytes,
        width: 32, height: 18, videoStreams: 1, audioStreams: 0,
        streamCount: 1, declaredFrames: 24,
      } } });
    const receiptSha256 = digest(receiptBytes);
    const receiptPath = `.sniper-external-media/receipts/${receiptSha256}.json`;
    writeFileSync(path.join(root, receiptPath), receiptBytes);
    const admitted = { ...row, path: snapshot, originalPath: row.path,
      sourceSha256: sha256, sourceSizeBytes: sizeBytes,
      admissionReceiptPath: receiptPath, admissionReceiptSha256: receiptSha256 };
    entries.push({ lane, originalPath: row.path, snapshotPath: snapshot,
      sha256, sizeBytes, mediaKind: "timed-media",
      admissionReceiptPath: receiptPath, admissionReceiptSha256: receiptSha256,
      authorizationEvidence: row.authorizationEvidence ?? null });
    return admitted;
  });
}

/** Write a realistic metadata-only ingest manifest and its bounded receipt closure. */
export function writeAdmittedMediaManifest(manifestPath: string,
  input: FixtureMediaManifest): Record<string, unknown> {
  const root = path.dirname(manifestPath), entries: Record<string, unknown>[] = [];
  const sources = admittedRows(root, "source", input.sources, entries);
  const broll = admittedRows(root, "broll", input.broll ?? [], entries);
  const externalMedia = admittedRows(
    root, "external", input.externalMedia ?? [], entries);
  entries.sort((left, right) => compareCodePoints(
    `${left.lane}\0${left.originalPath}`, `${right.lane}\0${right.originalPath}`));
  const entryBytes = canonicalBytes(entries);
  const sourceSetDigest = createHash("sha256")
    .update("sniper-producer-source-set-v1\0").update(entryBytes).digest("hex");
  const sourceSet = { schemaVersion: 1, policy: "sniper-producer-source-set-v1",
    entries, sourceSetDigest };
  const receiptBytes = canonicalBytes(sourceSet), receiptSha256 = digest(receiptBytes);
  const receiptPath = `.sniper-source-sets/${receiptSha256}.json`;
  mkdirSync(path.join(root, ".sniper-source-sets"), { recursive: true });
  writeFileSync(path.join(root, receiptPath), receiptBytes);
  const manifest = { sources, broll, externalMedia, music: [], sourceSetAdmission: {
    schemaVersion: 1, receiptPath, receiptSha256, sourceSetDigest,
    entryCount: entries.length } };
  writeFileSync(manifestPath, `${JSON.stringify(manifest)}\n`);
  return manifest;
}
