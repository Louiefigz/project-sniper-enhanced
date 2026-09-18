import { createHash, randomUUID } from "node:crypto";
import {
  closeSync,
  constants,
  existsSync,
  fstatSync,
  fsyncSync,
  linkSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync,
  type BigIntStats,
} from "node:fs";
import path from "node:path";
import { canonicalJson } from "./auto-edit-hash";
import { atomicWriteFileSync, atomicWriteJsonSync } from "./atomic-file";
import { writeContentAddressedJsonSync } from "./content-addressed-json";

const AUTHORITY_DIR = ".sniper-authority-v1";
const SHA256 = /^[0-9a-f]{64}$/u;
const PUBLICATION_WAIT = new Int32Array(new SharedArrayBuffer(4));

export interface ProducerAuthorityPaths {
  root: string;
  activeHead: string;
  approvedHead: string;
  objects: {
    revisions: string;
    plans: string;
    requests: string;
    batches: string;
    receipts: string;
    graphs: string;
    projections: string;
    cutRepairs: string;
    media: string;
  };
  advances: string;
  idempotency: string;
  intents: string;
  sagas: string;
}

function fsyncDirectory(directory: string): void {
  const descriptor = openSync(directory, "r");
  try {
    fsyncSync(descriptor);
  } finally {
    closeSync(descriptor);
  }
}

function createDirectory(directory: string): void {
  try {
    mkdirSync(directory, { mode: 0o700 });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
  }
}

function ensureRealDirectory(directory: string): void {
  if (!existsSync(directory)) createDirectory(directory);
  const stat = lstatSync(directory);
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error(`authority path must be a real directory: ${directory}`);
  }
}

function canonicalProducerDirectory(producerDir: string): string {
  const lexical = path.resolve(producerDir);
  const stat = lstatSync(lexical);
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error("producer authority root must be a real directory");
  }
  const canonical = realpathSync(lexical);
  if (canonical !== lexical) {
    throw new Error("producer authority root must use its canonical path");
  }
  return canonical;
}

export function producerAuthorityPaths(
  producerDir: string,
): ProducerAuthorityPaths {
  const producer = canonicalProducerDirectory(producerDir);
  const root = path.join(producer, AUTHORITY_DIR);
  const objectRoot = path.join(root, "objects");
  const paths: ProducerAuthorityPaths = {
    root,
    activeHead: path.join(root, "ACTIVE_HEAD"),
    approvedHead: path.join(root, "APPROVED_HEAD"),
    objects: {
      revisions: path.join(objectRoot, "revisions"),
      plans: path.join(objectRoot, "plans"),
      requests: path.join(objectRoot, "requests"),
      batches: path.join(objectRoot, "batches"),
      receipts: path.join(objectRoot, "receipts"),
      graphs: path.join(objectRoot, "graphs"),
      projections: path.join(objectRoot, "projections"),
      cutRepairs: path.join(objectRoot, "cut-repairs"),
      media: path.join(objectRoot, "media"),
    },
    advances: path.join(root, "advances"),
    idempotency: path.join(root, "idempotency"),
    intents: path.join(root, "intents"),
    sagas: path.join(root, "sagas"),
  };
  [
    root,
    objectRoot,
    ...Object.values(paths.objects),
    paths.advances,
    paths.idempotency,
    paths.intents,
    paths.sagas,
  ].forEach(ensureRealDirectory);
  return paths;
}

function assertRegularFile(filePath: string): void {
  const stat = lstatSync(filePath);
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw new Error(`authority record must be a regular file: ${filePath}`);
  }
}

function sameIdentity(left: BigIntStats, right: BigIntStats): boolean {
  return left.isFile() && right.isFile()
    && left.nlink === BigInt(1) && right.nlink === BigInt(1)
    && left.dev === right.dev && left.ino === right.ino
    && left.size === right.size && left.mtimeNs === right.mtimeNs
    && left.ctimeNs === right.ctimeNs;
}

function pathHasIdentity(filePath: string, expected: BigIntStats): boolean {
  try {
    return sameIdentity(lstatSync(filePath, { bigint: true }), expected);
  } catch {
    return false;
  }
}

function readStableFileSync(filePath: string): Buffer {
  assertRegularFile(filePath);
  const descriptor = openSync(
    filePath,
    constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0),
  );
  try {
    const before = fstatSync(descriptor, { bigint: true });
    if (!pathHasIdentity(filePath, before)) {
      throw new Error(`authority record changed while open: ${filePath}`);
    }
    const bytes = readFileSync(descriptor);
    const after = fstatSync(descriptor, { bigint: true });
    if (BigInt(bytes.length) !== before.size
        || !sameIdentity(before, after)
        || !pathHasIdentity(filePath, after)) {
      throw new Error(`authority record changed while read: ${filePath}`);
    }
    return bytes;
  } finally {
    closeSync(descriptor);
  }
}

function readPublishedCollision(filePath: string): Buffer {
  for (let attempt = 0; attempt < 25; attempt += 1) {
    try {
      return readStableFileSync(filePath);
    } catch (error) {
      const message = error instanceof Error ? error.message : "";
      const transient = message.includes("authority record changed while");
      if (!transient || attempt === 24) throw error;
      Atomics.wait(PUBLICATION_WAIT, 0, 0, 2);
    }
  }
  throw new Error("authority publication retry exhausted");
}

export function readAuthorityJsonSync(filePath: string): unknown {
  return JSON.parse(readStableFileSync(filePath).toString("utf8")) as unknown;
}

export function writeAuthorityObjectSync(
  directory: string,
  value: unknown,
): { hash: string; path: string; reused: boolean } {
  return writeContentAddressedJsonSync(directory, value);
}

function linkAuthority(
  temporary: string,
  destination: string,
  bytes: Buffer,
): boolean {
  try {
    linkSync(temporary, destination);
    return false;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
    if (!readPublishedCollision(destination).equals(bytes)) {
      throw new Error(`immutable authority conflict at ${destination}`);
    }
    return true;
  }
}

/** Publish immutable canonical JSON at a semantic key using an atomic hard link. */
export function publishImmutableAuthorityJsonSync(
  destination: string,
  value: unknown,
): { reused: boolean } {
  const bytes = Buffer.from(canonicalJson(value), "utf8");
  const directory = path.dirname(destination);
  ensureRealDirectory(directory);
  const temporary = path.join(
    directory,
    `.${path.basename(destination)}.${randomUUID()}.tmp`,
  );
  let descriptor: number | undefined;
  try {
    descriptor = openSync(temporary, "wx", 0o600);
    writeFileSync(descriptor, bytes);
    fsyncSync(descriptor);
    closeSync(descriptor);
    descriptor = undefined;
    return { reused: linkAuthority(
      temporary, destination, bytes) };
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
    rmSync(temporary, { force: true });
    fsyncDirectory(directory);
  }
}

export function writeMutableAuthorityJsonSync(
  destination: string,
  value: unknown,
): void {
  atomicWriteJsonSync(destination, value);
}

function readHeadSync(filePath: string, name: string): string | null {
  if (!existsSync(filePath)) return null;
  const value = readStableFileSync(filePath).toString("utf8");
  if (!/^[0-9a-f]{64}\n$/u.test(value)) {
    throw new Error(`${name} is malformed`);
  }
  return value.trim();
}

function writeHeadSync(filePath: string, name: string, revisionHash: string): void {
  if (!SHA256.test(revisionHash)) throw new Error(`${name} hash is malformed`);
  atomicWriteFileSync(filePath, `${revisionHash}\n`);
}

export function readActiveHeadSync(paths: ProducerAuthorityPaths): string | null {
  return readHeadSync(paths.activeHead, "ACTIVE_HEAD");
}

export function writeActiveHeadSync(paths: ProducerAuthorityPaths, hash: string): void {
  writeHeadSync(paths.activeHead, "ACTIVE_HEAD", hash);
}

export function readApprovedHeadSync(paths: ProducerAuthorityPaths): string | null {
  return readHeadSync(paths.approvedHead, "APPROVED_HEAD");
}

export function writeApprovedHeadSync(paths: ProducerAuthorityPaths, hash: string): void {
  writeHeadSync(paths.approvedHead, "APPROVED_HEAD", hash);
}

export function authorityKey(value: string): string {
  return createHash("sha256")
    .update("project-sniper-authority-key-v1\0")
    .update(value)
    .digest("hex");
}

export function assertObjectHashSync(directory: string, hash: string): unknown {
  if (!SHA256.test(hash)) throw new Error("authority object hash is malformed");
  const filePath = path.join(directory, `${hash}.json`);
  const bytes = readStableFileSync(filePath);
  const actual = createHash("sha256").update(bytes).digest("hex");
  if (actual !== hash) throw new Error(`authority object digest mismatch: ${hash}`);
  return JSON.parse(bytes.toString("utf8")) as unknown;
}
