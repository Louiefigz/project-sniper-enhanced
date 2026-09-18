import {
  closeSync,
  constants,
  fsyncSync,
  linkSync,
  lstatSync,
  openSync,
  readFileSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import {
  captureProcessIdentity,
  durableProcessAlive,
  processAlive,
  type ProcessIdentity,
  validProcessIdentity,
} from "./process-liveness";

const INVALID_GRACE_MS = 30_000;
const LOCK_NAME = ".sniper-project-mutation.lock";
const RECOVERY_NAME = ".sniper-project-mutation.recovery";
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;

interface LeaseRecord {
  pid: number;
  identity?: ProcessIdentity;
  nonce: string;
  operation: string;
  createdAt: string;
}
export interface ProjectMutationLease {
  release: () => void;
}
export interface ProjectMutationConflict {
  operation?: string;
  createdAt?: string;
  stale?: boolean;
}
export type ProjectMutationLeaseResult =
  | { lease: ProjectMutationLease; conflict?: never }
  | { lease?: never; conflict: ProjectMutationConflict };

function projectPath(projectRoot: string, name: string): string {
  return path.join(projectRoot.replace(/\/$/, ""), name);
}

function ownerPath(projectRoot: string, nonce: string): string {
  return projectPath(projectRoot, `.sniper-project-mutation.owner-${nonce}.json`);
}

function validRecord(value: unknown): value is LeaseRecord {
  if (!value || typeof value !== "object") return false;
  const row = value as Partial<LeaseRecord>;
  const keys = Object.keys(row);
  const timestamp = typeof row.createdAt === "string"
    ? Date.parse(row.createdAt)
    : Number.NaN;
  const identityKeys = row.identity && typeof row.identity === "object"
    ? Object.keys(row.identity)
    : [];
  return keys.every((key) =>
    ["pid", "identity", "nonce", "operation", "createdAt"].includes(key))
    && keys.length === 5
    && Number.isInteger(row.pid) && Number(row.pid) > 0
    && typeof row.nonce === "string" && UUID_PATTERN.test(row.nonce)
    && typeof row.operation === "string"
    && row.operation === row.operation.trim()
    && row.operation.length > 0 && row.operation.length <= 500
    && Number.isFinite(timestamp)
    && new Date(timestamp).toISOString() === row.createdAt
    && timestamp <= Date.now() + 60_000
    && validProcessIdentity(row.identity)
    && row.identity.pid === row.pid
    && identityKeys.every((key) =>
      ["pid", "bootSession", "startToken"].includes(key))
    && (!row.identity.bootSession
      || row.identity.bootSession.length <= 500)
    && (!row.identity.startToken
      || row.identity.startToken.length <= 500);
}

function readRecord(file: string): LeaseRecord | null {
  try {
    const stat = lstatSync(file);
    if (!stat.isFile() || stat.isSymbolicLink()) return null;
    const descriptor = openSync(file, constants.O_RDONLY | constants.O_NOFOLLOW);
    try {
      const value = JSON.parse(readFileSync(descriptor, "utf8")) as unknown;
      return validRecord(value) ? value : null;
    } finally {
      closeSync(descriptor);
    }
  } catch {
    return null;
  }
}

function readLegacyRecord(dir: string): Partial<LeaseRecord> | null {
  try {
    const value = JSON.parse(
      readFileSync(path.join(dir, "owner.json"), "utf8"),
    ) as Partial<LeaseRecord>;
    return Number.isInteger(value.pid) && typeof value.operation === "string"
      ? value
      : null;
  } catch {
    return null;
  }
}

function sameInode(left: string, right: string): boolean {
  try {
    const a = lstatSync(left);
    const b = lstatSync(right);
    return a.isFile() && b.isFile() && a.dev === b.dev && a.ino === b.ino;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return false;
    throw error;
  }
}

function syncParent(file: string): void {
  const descriptor = openSync(path.dirname(path.resolve(file)), constants.O_RDONLY);
  try {
    fsyncSync(descriptor);
  } finally {
    closeSync(descriptor);
  }
}

function ownerAlive(record: LeaseRecord): boolean {
  return durableProcessAlive(record.pid, record.identity, record.createdAt, {
    maxHeartbeatAgeMs: Number.MAX_SAFE_INTEGER,
  });
}
function hasDurableStartIdentity(record: LeaseRecord): boolean {
  return typeof record.identity?.startToken === "string"
    && /^(?:linux-ticks:[0-9]+|ps:.+)$/u.test(record.identity.startToken);
}
function writeOwner(file: string, record: LeaseRecord): void {
  const descriptor = openSync(
    file,
    constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW,
    0o600,
  );
  try {
    writeFileSync(descriptor, `${JSON.stringify(record)}\n`);
    fsyncSync(descriptor);
  } finally {
    closeSync(descriptor);
  }
  syncParent(file);
}

function unlinkIfSame(file: string, identity: string): void {
  if (sameInode(file, identity)) {
    try { unlinkSync(file); } catch {}
  }
}

function clearDetachedRecovery(projectRoot: string, lock: string): void {
  const recovery = projectPath(projectRoot, RECOVERY_NAME);
  if (sameInode(recovery, lock)) return;
  const record = readRecord(recovery);
  const owner = record ? ownerPath(projectRoot, record.nonce) : "";
  const ownerMatches = !!owner && sameInode(owner, recovery);
  if (ownerMatches) {
    try { unlinkSync(owner); } catch {}
  }
  try { unlinkSync(recovery); } catch {}
}

function releaseLease(projectRoot: string, record: LeaseRecord): void {
  const lock = projectPath(projectRoot, LOCK_NAME);
  const owner = ownerPath(projectRoot, record.nonce);
  unlinkIfSame(lock, owner);
  try { unlinkSync(owner); } catch {}
  syncParent(lock);
}

function claimExactDeadOwner(projectRoot: string, lock: string): boolean {
  const observed = readRecord(lock);
  if (!observed || !hasDurableStartIdentity(observed) || ownerAlive(observed)) {
    return false;
  }
  const recovery = projectPath(projectRoot, RECOVERY_NAME);
  try {
    linkSync(lock, recovery);
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code === "EEXIST") return false;
    throw error;
  }
  if (!sameInode(lock, recovery)) return false;
  const claimed = readRecord(recovery);
  const owner = claimed ? ownerPath(projectRoot, claimed.nonce) : "";
  if (!claimed || claimed.nonce !== observed.nonce
      || !hasDurableStartIdentity(claimed) || ownerAlive(claimed)
      || !sameInode(owner, recovery)) {
    unlinkIfSame(recovery, lock);
    return false;
  }
  unlinkIfSame(lock, recovery);
  try { unlinkSync(owner); } catch {}
  try { unlinkSync(recovery); } catch {}
  syncParent(lock);
  return true;
}

function removeFailedOwner(owner: string, lock: string): void {
  try { unlinkSync(owner); } catch {}
  syncParent(lock);
}
function rollbackLinkedOwner(owner: string, lock: string): void {
  unlinkIfSame(lock, owner);
  try { unlinkSync(owner); } catch {}
  syncParent(lock);
}
function conflictFor(lock: string): ProjectMutationConflict {
  const record = readRecord(lock);
  if (record) {
    return {
      operation: record.operation,
      createdAt: record.createdAt,
      stale: !ownerAlive(record),
    };
  }
  const stat = lstatSync(lock);
  if (stat.isDirectory()) {
    const legacy = readLegacyRecord(lock);
    if (legacy) {
      return {
        operation: legacy.operation,
        createdAt: legacy.createdAt,
        stale: !processAlive(legacy.pid),
      };
    }
  }
  return { stale: Date.now() - stat.mtimeMs > INVALID_GRACE_MS };
}
function resolveAcquireConflict(projectRoot: string, lock: string): ProjectMutationLeaseResult | null {
  try {
    const stat = lstatSync(lock);
    if (stat.isFile() && claimExactDeadOwner(projectRoot, lock)) return null;
    return { conflict: conflictFor(lock) };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
}
function tryAcquire(
  projectRoot: string,
  lock: string,
  record: LeaseRecord,
): ProjectMutationLeaseResult | null {
  const owner = ownerPath(projectRoot, record.nonce);
  writeOwner(owner, record);
  try {
    linkSync(owner, lock);
  } catch (error) {
    removeFailedOwner(owner, lock);
    const code = (error as NodeJS.ErrnoException).code;
    if (code === "ENOENT") return null;
    if (code !== "EEXIST") throw error;
    return resolveAcquireConflict(projectRoot, lock);
  }
  try {
    clearDetachedRecovery(projectRoot, lock);
    syncParent(lock);
    return { lease: { release: () => releaseLease(projectRoot, record) } };
  } catch (error) {
    rollbackLinkedOwner(owner, lock);
    throw error;
  }
}
/** One fail-fast, exact-owner-recoverable writer lease shared by all surfaces. */
export function acquireProjectMutationLease(
  projectRoot: string,
  operation: string,
): ProjectMutationLeaseResult {
  const lock = projectPath(projectRoot, LOCK_NAME);
  const record: LeaseRecord = {
    pid: process.pid,
    identity: captureProcessIdentity(process.pid),
    nonce: randomUUID(),
    operation,
    createdAt: new Date().toISOString(),
  };
  if (!validRecord(record)) {
    throw new Error("project mutation operation/owner identity is invalid");
  }
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const result = tryAcquire(projectRoot, lock, record);
    if (result) return result;
  }
  return { conflict: {} };
}
