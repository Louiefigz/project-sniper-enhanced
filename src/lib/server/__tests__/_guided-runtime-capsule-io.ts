/** TEST-only bounded byte observations. No approval, runtime selection, or process launch. */
import { createHash } from "node:crypto";
import { constants, closeSync, fstatSync, fsyncSync, lstatSync, openSync, readSync,
  realpathSync, writeSync, type BigIntStats } from "node:fs";
import path from "node:path";

export type CapsuleGuard = () => void;
export interface CapsuleFile {
  path: string; sha256: string; sizeBytes: number;
  identity: { device: string; inode: string; mode: string; links: string; modifiedNs: string; changedNs: string };
}
export const SOURCE_BYTES = 512 * 1024 * 1024;
export const FILE_BYTES = 1024 * 1024 * 1024;
const CHUNK_BYTES = 1024 * 1024;

export function byteHash(value: Buffer): string {
  return createHash("sha256").update(value).digest("hex");
}

export function canonicalDirectory(value: string): string {
  if (!value || !path.isAbsolute(value) || path.normalize(value) !== value || /[\\\0\r\n]/u.test(value)
      || realpathSync(value) !== value || !lstatSync(value).isDirectory()) {
    throw new Error("TEST capsule requires a canonical existing directory");
  }
  return value;
}

export function logicalPath(value: string): string {
  if (!value || value.length > 4096 || /[\\\0\r\n]/u.test(value) || path.isAbsolute(value)
      || value.split("/").some((part) => !part || part === "." || part === "..")) {
    throw new Error("TEST capsule source path is unsafe");
  }
  return value;
}

function sameIdentity(left: BigIntStats, right: BigIntStats): boolean {
  return ["dev", "ino", "mode", "nlink", "size", "mtimeNs", "ctimeNs"].every((key) =>
    left[key as keyof BigIntStats] === right[key as keyof BigIntStats]);
}

function identity(info: BigIntStats): CapsuleFile["identity"] {
  return { device: String(info.dev), inode: String(info.ino), mode: String(info.mode), links: String(info.nlink),
    modifiedNs: String(info.mtimeNs), changedNs: String(info.ctimeNs) };
}

/** Cheap final race guard only AFTER the same file was byte-observed in this verification. */
export function assertFileIdentity(row: CapsuleFile, guard: CapsuleGuard): void {
  guard(); const directories = parents(row.path), info = lstatSync(row.path, { bigint: true });
  if (!info.isFile() || info.nlink !== BigInt(1) || Number(info.size) !== row.sizeBytes
      || JSON.stringify(identity(info)) !== JSON.stringify(row.identity)) throw new Error("TEST capsule held file identity changed");
  assertParents(directories); guard();
}

function parents(file: string): Array<[string, bigint, bigint]> {
  const result: Array<[string, bigint, bigint]> = [];
  for (let current = path.dirname(file); ; current = path.dirname(current)) {
    const info = lstatSync(current, { bigint: true });
    if (!info.isDirectory() || info.isSymbolicLink()) throw new Error("TEST capsule parent is linked or non-directory");
    result.push([current, info.dev, info.ino]);
    if (path.dirname(current) === current) return result;
  }
}

function assertParents(rows: Array<[string, bigint, bigint]>): void {
  for (const [file, device, inode] of rows) {
    const info = lstatSync(file, { bigint: true });
    if (!info.isDirectory() || info.isSymbolicLink() || info.dev !== device || info.ino !== inode) {
      throw new Error("TEST capsule parent identity changed");
    }
  }
}

function streamChunks(input: { fd: number; expectedSize: number; limit: number; guard: CapsuleGuard; visit: (bytes: Buffer) => void }) {
  const buffer = Buffer.alloc(CHUNK_BYTES), hash = createHash("sha256"); let count = 0;
  for (;;) {
    input.guard(); const size = readSync(input.fd, buffer, 0, buffer.length, null);
    if (size === 0) break;
    count += size;
    if (count > input.expectedSize || count > input.limit) throw new Error("TEST capsule file grew");
    const bytes = buffer.subarray(0, size); hash.update(bytes); input.visit(bytes);
  }
  return { count, sha256: hash.digest("hex") };
}

/** O_NONBLOCK prevents FIFO opens from hanging; all reads use this same held descriptor. */
export function visitFile(file: string, limit: number, guard: CapsuleGuard,
  visit: (bytes: Buffer) => void): CapsuleFile {
  guard();
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > FILE_BYTES || path.resolve(file) !== file) {
    throw new Error("TEST capsule file observation is unbounded");
  }
  const directories = parents(file), before = lstatSync(file, { bigint: true });
  if (!before.isFile() || before.isSymbolicLink() || before.nlink !== BigInt(1) || before.size < BigInt(0) || before.size > BigInt(limit)) {
    throw new Error("TEST capsule needs one bounded regular file, not a link");
  }
  const fd = openSync(file, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    if (!sameIdentity(before, fstatSync(fd, { bigint: true }))) throw new Error("TEST capsule open identity changed");
    const { count, sha256 } = streamChunks({ fd, expectedSize: Number(before.size), limit, guard, visit });
    assertParents(directories); guard();
    if (count !== Number(before.size) || !sameIdentity(before, fstatSync(fd, { bigint: true }))
        || !sameIdentity(before, lstatSync(file, { bigint: true }))) throw new Error("TEST capsule file changed while reading");
    return { path: file, sha256, sizeBytes: count, identity: identity(before) };
  } finally { closeSync(fd); }
}

export function observeFile(file: string, limit: number, guard: CapsuleGuard): CapsuleFile {
  return visitFile(file, limit, guard, () => {});
}

export function boundedBytes(file: string, limit: number, guard: CapsuleGuard): { file: CapsuleFile; bytes: Buffer } {
  const chunks: Buffer[] = [];
  const held = visitFile(file, limit, guard, (bytes) => chunks.push(Buffer.from(bytes)));
  return { file: held, bytes: Buffer.concat(chunks) };
}

function writeAll(fd: number, bytes: Buffer, guard: CapsuleGuard): void {
  let offset = 0;
  while (offset < bytes.length) {
    guard(); const written = writeSync(fd, bytes, offset, bytes.length - offset);
    if (written < 1) throw new Error("TEST capsule write made no progress");
    offset += written;
  }
}

/** New-only streaming copy; failure is retained, never overwritten or silently removed. */
export function copyFileHeld(expected: CapsuleFile, destination: string, guard: CapsuleGuard): CapsuleFile {
  const directories = parents(destination);
  const fd = openSync(destination, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o400);
  try {
    const actual = visitFile(expected.path, Math.max(1, expected.sizeBytes), guard, (bytes) => writeAll(fd, bytes, guard));
    if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error("TEST capsule source differs from inventory");
    fsyncSync(fd); assertParents(directories); guard();
  } finally { closeSync(fd); }
  const copied = observeFile(destination, Math.max(1, expected.sizeBytes), guard);
  if (copied.sha256 !== expected.sha256 || copied.sizeBytes !== expected.sizeBytes) throw new Error("TEST capsule copied bytes differ");
  return copied;
}

export function writeNewBytes(destination: string, bytes: Buffer, guard: CapsuleGuard): void {
  guard(); const directories = parents(destination);
  const fd = openSync(destination, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o400);
  try { writeAll(fd, bytes, guard); fsyncSync(fd); assertParents(directories); guard(); }
  finally { closeSync(fd); }
  const parent = openSync(path.dirname(destination), constants.O_RDONLY | constants.O_NOFOLLOW);
  try { fsyncSync(parent); assertParents(directories); guard(); }
  finally { closeSync(parent); }
}
