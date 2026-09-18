import crypto from "node:crypto";
import fs, { type BigIntStats } from "node:fs";
import path from "node:path";
import { verifyReferenceVttAdmission } from "./reference-sidecar";

const SHA256 = /^[0-9a-f]{64}$/u;
const IMAGE_ID = /^sha256:[0-9a-f]{64}$/u;
const CONTAINER_ID = /^[0-9a-f]{64}$/u;
// v3 retains the receipt schema and isolation contract; validation decode uses four CPUs/threads.
const PROBE_POLICIES = new Set(["sniper-external-media-probe-v2", "sniper-external-media-probe-v3"]);
const hashCache = new Map<string, { key: string; value: string }>();
const REFERENCE_LIMITS = {
  max_bytes: 2 * 1024 ** 3,
  max_width: 8192,
  max_height: 8192,
  max_frames: 500_000,
  max_duration_seconds: 3600,
  max_streams: 32,
  max_decode_seconds: 1200,
};

function object(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function sameFile(file: string, observed: BigIntStats): boolean {
  try {
    const current = fs.lstatSync(file, { bigint: true });
    return current.isFile() && !current.isSymbolicLink() &&
      current.nlink === BigInt(1) && observed.nlink === BigInt(1) &&
      current.dev === observed.dev && current.ino === observed.ino &&
      current.size === observed.size && current.mtimeNs === observed.mtimeNs &&
      current.ctimeNs === observed.ctimeNs;
  } catch {
    return false;
  }
}

function readRegular(file: string, maxBytes: number): Buffer | null {
  let descriptor = -1;
  try {
    descriptor = fs.openSync(
      file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0),
    );
    const before = fs.fstatSync(descriptor, { bigint: true });
    if (!before.isFile() || before.nlink !== BigInt(1) ||
        before.size <= BigInt(0) || before.size > BigInt(maxBytes)) return null;
    const bytes = fs.readFileSync(descriptor);
    const after = fs.fstatSync(descriptor, { bigint: true });
    return BigInt(bytes.length) === before.size &&
      before.dev === after.dev && before.ino === after.ino &&
      before.size === after.size && before.mtimeNs === after.mtimeNs &&
      before.ctimeNs === after.ctimeNs && sameFile(file, after)
      ? bytes : null;
  } catch {
    return null;
  } finally {
    if (descriptor >= 0) fs.closeSync(descriptor);
  }
}

function readObject(file: string, maxBytes: number): Record<string, unknown> | null {
  const bytes = readRegular(file, maxBytes);
  if (!bytes) return null;
  try {
    return object(JSON.parse(bytes.toString("utf8")));
  } catch {
    return null;
  }
}

function hashFile(file: string, expectedSize: number): string {
  const descriptor = fs.openSync(
    file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0),
  );
  const before = fs.fstatSync(descriptor, { bigint: true });
  if (!before.isFile() || before.nlink !== BigInt(1) ||
      before.size !== BigInt(expectedSize)) {
    fs.closeSync(descriptor);
    throw new Error("reference is not the admitted regular file");
  }
  const key = [
    before.dev, before.ino, before.size, before.mtimeNs, before.ctimeNs,
  ].join(":");
  const cached = hashCache.get(file);
  if (cached?.key === key && sameFile(file, before)) {
    fs.closeSync(descriptor);
    return cached.value;
  }
  const hash = crypto.createHash("sha256");
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  let after: BigIntStats;
  try {
    let size = fs.readSync(descriptor, buffer, 0, buffer.length, null);
    while (size) {
      hash.update(buffer.subarray(0, size));
      size = fs.readSync(descriptor, buffer, 0, buffer.length, null);
    }
    after = fs.fstatSync(descriptor, { bigint: true });
  } finally {
    fs.closeSync(descriptor);
  }
  const value = hash.digest("hex");
  const afterKey = [
    after.dev, after.ino, after.size, after.mtimeNs, after.ctimeNs,
  ].join(":");
  if (key !== afterKey || !sameFile(file, after)) {
    throw new Error("reference changed while hashing");
  }
  hashCache.set(file, { key, value });
  if (hashCache.size > 128) {
    const oldest = hashCache.keys().next().value;
    if (typeof oldest === "string") hashCache.delete(oldest);
  }
  return value;
}

function exactKeys(value: Record<string, unknown>, keys: string[]): boolean {
  return Object.keys(value).sort().join("\0") === keys.sort().join("\0");
}

function validAdmission(
  admission: Record<string, unknown>,
  video: string,
  dir: string,
): boolean {
  const keys = [
    "durationSeconds", "mediaKind", "policy", "receiptPath",
    "receiptSha256", "schemaVersion", "sizeBytes", "snapshotPath",
    "snapshotSha256",
  ];
  return exactKeys(admission, keys) &&
    admission.schemaVersion === 1 &&
    admission.policy === "sniper-reference-media-admission-v1" &&
    admission.mediaKind === "timed-media" &&
    admission.snapshotPath === video &&
    path.basename(video) === `${String(admission.snapshotSha256)}.media` &&
    typeof admission.snapshotSha256 === "string" &&
    SHA256.test(admission.snapshotSha256) &&
    typeof admission.receiptSha256 === "string" &&
    SHA256.test(admission.receiptSha256) &&
    typeof admission.receiptPath === "string" &&
    admission.receiptPath === path.join(
      dir, ".sniper-reference-admission",
      `${String(admission.receiptSha256)}.json`,
    ) &&
    Number.isSafeInteger(admission.sizeBytes) &&
    Number(admission.sizeBytes) > 0 &&
    Number(admission.sizeBytes) <= REFERENCE_LIMITS.max_bytes &&
    Number.isFinite(admission.durationSeconds) &&
    Number(admission.durationSeconds) > 0 &&
    Number(admission.durationSeconds) <= 3600;
}

function validLimits(value: unknown): boolean {
  const limits = object(value);
  return limits !== null && exactKeys(limits, Object.keys(REFERENCE_LIMITS)) &&
    Object.entries(REFERENCE_LIMITS).every(([key, expected]) =>
      limits[key] === expected);
}

function validFacts(
  facts: Record<string, unknown> | null,
  admission: Record<string, unknown>,
): boolean {
  if (!facts || !exactKeys(facts, [
    "audioStreams", "declaredFrames", "durationSeconds", "height",
    "mediaKind", "sizeBytes", "streamCount", "videoStreams", "width",
  ])) return false;
  const integers = [
    "audioStreams", "declaredFrames", "height", "sizeBytes",
    "streamCount", "videoStreams", "width",
  ];
  return facts.mediaKind === "timed-media" &&
    facts.durationSeconds === admission.durationSeconds &&
    facts.sizeBytes === admission.sizeBytes &&
    integers.every((key) => Number.isSafeInteger(facts[key])) &&
    Number(facts.videoStreams) >= 1 && Number(facts.audioStreams) >= 0 &&
    Number(facts.sizeBytes) > 0 &&
    Number(facts.sizeBytes) <= REFERENCE_LIMITS.max_bytes &&
    Number(facts.streamCount) >= Number(facts.videoStreams) +
      Number(facts.audioStreams) &&
    Number(facts.streamCount) <= REFERENCE_LIMITS.max_streams &&
    Number(facts.width) > 0 && Number(facts.width) <= REFERENCE_LIMITS.max_width &&
    Number(facts.height) > 0 && Number(facts.height) <= REFERENCE_LIMITS.max_height &&
    Number(facts.declaredFrames) > 0 &&
    Number(facts.declaredFrames) <= REFERENCE_LIMITS.max_frames;
}

function receiptMatches(
  receipt: Record<string, unknown>,
  admission: Record<string, unknown>,
  video: string,
): boolean {
  const snapshot = object(receipt.snapshot);
  const decoded = object(receipt.decoded);
  const facts = object(decoded?.facts);
  const isolation = object(receipt.isolation);
  const network = object(receipt.network);
  const image = object(receipt.image);
  const isolationKeys = [
    "containerId", "imageId", "mountSource", "networkMode",
    "nonrootUser", "readonlyRoot",
  ];
  const keys = [
    "decoded", "image", "isolation", "limits", "network",
    "policy", "schemaVersion", "snapshot",
  ];
  return exactKeys(receipt, keys) &&
    receipt.schemaVersion === 1 &&
    typeof receipt.policy === "string" && PROBE_POLICIES.has(receipt.policy) &&
    snapshot?.path === video &&
    snapshot?.sha256 === admission.snapshotSha256 &&
    snapshot?.sizeBytes === admission.sizeBytes &&
    decoded?.schemaVersion === 1 &&
    decoded?.ok === true &&
    decoded?.decoded === true &&
    validFacts(facts, admission) &&
    validLimits(receipt.limits) &&
    isolation !== null && exactKeys(isolation, isolationKeys) &&
    image?.Id === isolation?.imageId &&
    typeof isolation?.imageId === "string" &&
    IMAGE_ID.test(isolation.imageId) &&
    typeof isolation?.containerId === "string" &&
    CONTAINER_ID.test(isolation.containerId) &&
    isolation?.networkMode === "none" &&
    isolation?.readonlyRoot === true &&
    isolation?.mountSource === video &&
    typeof isolation?.nonrootUser === "string" &&
    isolation.nonrootUser !== "0" && isolation.nonrootUser !== "0:0" &&
    network?.schemaVersion === 1 &&
    network?.hostDecoyPositive === true;
}

/** Rehash the exact sandbox receipt and media before exposing a new reference. */
export function validAdmittedReference(video: string): boolean {
  try {
    const dir = path.dirname(video);
    const source = readObject(path.join(dir, "reference-source.json"), 1024 * 1024);
    const admission = object(source?.admission);
    if (!admission || !validAdmission(admission, video, dir)) return false;
    const textRows = Array.isArray(source?.transcripts)
      ? source.transcripts
      : source?.transcript === null || source?.transcript === undefined
        ? []
        : [source.transcript];
    if (textRows.some((row) => verifyReferenceVttAdmission(row, dir) === null)) {
      return false;
    }
    const videoStat = fs.lstatSync(video);
    if (!videoStat.isFile() || videoStat.isSymbolicLink() ||
        videoStat.nlink !== 1 || videoStat.size !== admission.sizeBytes ||
        hashFile(video, Number(admission.sizeBytes)) !== admission.snapshotSha256) {
      return false;
    }
    const receiptPath = String(admission.receiptPath);
    const receiptBytes = readRegular(receiptPath, 4 * 1024 * 1024);
    if (!receiptBytes ||
        crypto.createHash("sha256").update(receiptBytes).digest("hex") !==
          admission.receiptSha256) return false;
    const receipt = object(JSON.parse(receiptBytes.toString("utf8")));
    return receipt !== null && receiptMatches(receipt, admission, video);
  } catch {
    return false;
  }
}
