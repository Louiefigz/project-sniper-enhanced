import crypto from "node:crypto";
import fs, { type BigIntStats } from "node:fs";
import path from "node:path";
import {
  atomicCreateFileSync,
} from "@/lib/server/atomic-file";
import { ReferenceMediaError } from "./reference-intake-policy";

export const MAX_REFERENCE_VTT_BYTES = 32 * 1024 * 1024;
const POLICY = "sniper-reference-text-admission-v1";
const RECEIPT_DIR = ".sniper-reference-text-admission";
const SHA256 = /^[0-9a-f]{64}$/u;

export interface ReferenceTextAdmission {
  schemaVersion: 1;
  policy: typeof POLICY;
  path: string;
  sha256: string;
  sizeBytes: number;
  receiptPath: string;
  receiptSha256: string;
}

function sameIdentity(left: BigIntStats, right: BigIntStats): boolean {
  return left.isFile() && right.isFile() &&
    left.nlink === BigInt(1) && right.nlink === BigInt(1) &&
    left.dev === right.dev && left.ino === right.ino &&
    left.size === right.size && left.mtimeNs === right.mtimeNs &&
    left.ctimeNs === right.ctimeNs;
}

function samePath(file: string, expected: BigIntStats): boolean {
  try {
    return sameIdentity(
      fs.lstatSync(file, { bigint: true }),
      expected,
    );
  } catch {
    return false;
  }
}

function writeAll(descriptor: number, bytes: Buffer, size: number): void {
  let offset = 0;
  while (offset < size) {
    const written = fs.writeSync(
      descriptor, bytes, offset, size - offset, null,
    );
    if (written <= 0) throw new Error("reference transcript write stalled");
    offset += written;
  }
}

function openSource(source: string): { descriptor: number; before: BigIntStats } {
  let descriptor = -1;
  try {
    descriptor = fs.openSync(
      source, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0),
    );
    const before = fs.fstatSync(descriptor, { bigint: true });
    if (!before.isFile() || before.nlink !== BigInt(1) ||
        before.size > BigInt(MAX_REFERENCE_VTT_BYTES)) {
      fs.closeSync(descriptor);
      descriptor = -1;
      throw new ReferenceMediaError(
        `unsafe reference transcript: ${path.basename(source)}`,
      );
    }
    return { descriptor, before };
  } catch (error) {
    if (descriptor >= 0) fs.closeSync(descriptor);
    if (error instanceof ReferenceMediaError) throw error;
    throw new ReferenceMediaError(
      `unsafe reference transcript: ${path.basename(source)}`,
    );
  }
}

function copyBytes(
  sourceFd: number,
  destinationFd: number,
  size: bigint,
): string {
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  const hash = crypto.createHash("sha256");
  let remaining = size;
  while (remaining > BigInt(0)) {
    const requested = Number(
      remaining < BigInt(buffer.length) ? remaining : BigInt(buffer.length),
    );
    const read = fs.readSync(sourceFd, buffer, 0, requested, null);
    if (!read) throw new Error("reference transcript was truncated");
    writeAll(destinationFd, buffer, read);
    hash.update(buffer.subarray(0, read));
    remaining -= BigInt(read);
  }
  if (fs.readSync(sourceFd, buffer, 0, 1, null)) {
    throw new Error("reference transcript grew while copying");
  }
  return hash.digest("hex");
}

function exactReceipt(
  destination: string,
  sha256: string,
  sizeBytes: number,
): { bytes: Buffer; document: Record<string, unknown> } {
  const document = {
    schemaVersion: 1,
    policy: POLICY,
    path: path.resolve(destination),
    sha256,
    sizeBytes,
  };
  return {
    document,
    bytes: Buffer.from(`${JSON.stringify(document, null, 1)}\n`),
  };
}

function storeReceipt(
  destination: string,
  sha256: string,
  sizeBytes: number,
): Pick<ReferenceTextAdmission, "receiptPath" | "receiptSha256"> {
  const receipt = exactReceipt(destination, sha256, sizeBytes);
  const receiptSha256 = crypto.createHash("sha256")
    .update(receipt.bytes).digest("hex");
  const root = path.dirname(path.resolve(destination));
  const dir = path.join(root, RECEIPT_DIR);
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  const info = fs.lstatSync(dir);
  if (!info.isDirectory() || info.isSymbolicLink()) {
    throw new ReferenceMediaError("reference text receipt store is unsafe");
  }
  const receiptPath = path.join(dir, `${receiptSha256}.json`);
  try {
    atomicCreateFileSync(receiptPath, receipt.bytes);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST" ||
        !fs.readFileSync(receiptPath).equals(receipt.bytes)) {
      throw error;
    }
  }
  return { receiptPath, receiptSha256 };
}

function openDestination(
  source: string,
  destination: string,
  sourceIdentity: BigIntStats,
): number {
  if (path.resolve(source) === path.resolve(destination)) {
    if (!samePath(source, sourceIdentity)) {
      throw new Error("reference transcript changed while validating");
    }
    throw new Error("reference transcript destination must be a new file");
  }
  return fs.openSync(
    destination,
    fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL |
      (fs.constants.O_NOFOLLOW ?? 0),
    0o600,
  );
}

function unlinkQuietly(file: string): void {
  try { fs.unlinkSync(file); } catch {}
}

/** Admit one stable VTT and return exact downstream-verifiable authority. */
export function admitReferenceVtt(
  source: string,
  destination: string,
): ReferenceTextAdmission {
  const opened = openSource(source);
  let destinationFd = -1;
  let destinationCreated = false;
  try {
    destinationFd = openDestination(source, destination, opened.before);
    destinationCreated = true;
    const sha256 = copyBytes(
      opened.descriptor, destinationFd, opened.before.size,
    );
    const after = fs.fstatSync(opened.descriptor, { bigint: true });
    if (!sameIdentity(opened.before, after) || !samePath(source, after)) {
      throw new Error("reference transcript changed while copying");
    }
    fs.fsyncSync(destinationFd);
    fs.closeSync(destinationFd);
    destinationFd = -1;
    const sizeBytes = Number(opened.before.size);
    return {
      schemaVersion: 1,
      policy: POLICY,
      path: path.resolve(destination),
      sha256,
      sizeBytes,
      ...storeReceipt(destination, sha256, sizeBytes),
    };
  } catch (error) {
    if (destinationFd >= 0) fs.closeSync(destinationFd);
    destinationFd = -1;
    if (destinationCreated) unlinkQuietly(destination);
    if (error instanceof ReferenceMediaError) throw error;
    throw new ReferenceMediaError((error as Error).message);
  } finally {
    fs.closeSync(opened.descriptor);
    if (destinationFd >= 0) fs.closeSync(destinationFd);
  }
}

/** Compatibility wrapper for callers that only need the admitted path. */
export function copyReferenceVtt(source: string, destination: string): string {
  return admitReferenceVtt(source, destination).path;
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function hashRegular(file: string, limit: number): string | null {
  let descriptor = -1;
  try {
    descriptor = fs.openSync(
      file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0),
    );
    const before = fs.fstatSync(descriptor, { bigint: true });
    if (!before.isFile() || before.nlink !== BigInt(1) ||
        before.size <= BigInt(0) || before.size > BigInt(limit)) return null;
    const hash = crypto.createHash("sha256");
    const buffer = Buffer.allocUnsafe(1024 * 1024);
    let size = fs.readSync(descriptor, buffer, 0, buffer.length, null);
    while (size) {
      hash.update(buffer.subarray(0, size));
      size = fs.readSync(descriptor, buffer, 0, buffer.length, null);
    }
    const after = fs.fstatSync(descriptor, { bigint: true });
    if (!sameIdentity(before, after) || !samePath(file, after)) return null;
    return hash.digest("hex");
  } catch {
    return null;
  } finally {
    if (descriptor >= 0) fs.closeSync(descriptor);
  }
}

/** Rehash one VTT plus its content-addressed receipt before downstream use. */
export function verifyReferenceVttAdmission(
  value: unknown,
  referenceDir: string,
): string | null {
  const row = record(value);
  if (!row || Object.keys(row).sort().join("\0") !== [
    "path", "policy", "receiptPath", "receiptSha256",
    "schemaVersion", "sha256", "sizeBytes",
  ].sort().join("\0")) return null;
  const root = path.resolve(referenceDir);
  const admittedPath = typeof row.path === "string" ? path.resolve(row.path) : "";
  const receiptPath = typeof row.receiptPath === "string"
    ? path.resolve(row.receiptPath) : "";
  const inside = path.dirname(admittedPath) === root;
  const expectedReceipt = path.join(
    root, RECEIPT_DIR, `${String(row.receiptSha256)}.json`,
  );
  let admittedSize = -1;
  try {
    admittedSize = fs.lstatSync(admittedPath).size;
  } catch {}
  if (row.schemaVersion !== 1 || row.policy !== POLICY || !inside ||
      path.extname(admittedPath).toLowerCase() !== ".vtt" ||
      typeof row.sha256 !== "string" || !SHA256.test(row.sha256) ||
      typeof row.receiptSha256 !== "string" ||
      !SHA256.test(row.receiptSha256) ||
      !Number.isSafeInteger(row.sizeBytes) || Number(row.sizeBytes) <= 0 ||
      Number(row.sizeBytes) > MAX_REFERENCE_VTT_BYTES ||
      admittedSize !== row.sizeBytes ||
      receiptPath !== expectedReceipt ||
      hashRegular(admittedPath, MAX_REFERENCE_VTT_BYTES) !== row.sha256) {
    return null;
  }
  const receiptHash = hashRegular(receiptPath, 1024 * 1024);
  if (receiptHash !== row.receiptSha256) return null;
  try {
    const receipt = record(JSON.parse(fs.readFileSync(receiptPath, "utf8")));
    const expected = exactReceipt(
      admittedPath, String(row.sha256), Number(row.sizeBytes),
    ).document;
    return receipt && JSON.stringify(receipt) === JSON.stringify(expected)
      ? admittedPath : null;
  } catch {
    return null;
  }
}
