import {
  lstatSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { processAlive } from "./process-liveness";

const INVALID_GRACE_MS = 30_000;

interface LeaseRecord {
  pid: number;
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
}

export type ProjectMutationLeaseResult =
  | { lease: ProjectMutationLease; conflict?: never }
  | { lease?: never; conflict: ProjectMutationConflict };

function leaseDir(projectRoot: string): string {
  return path.join(projectRoot.replace(/\/$/, ""), ".sniper-project-mutation.lock");
}

function metadataPath(dir: string): string {
  return path.join(dir, "owner.json");
}

function readLease(dir: string): LeaseRecord | null {
  try {
    const value = JSON.parse(readFileSync(metadataPath(dir), "utf8")) as Partial<LeaseRecord>;
    return typeof value.pid === "number"
      && typeof value.nonce === "string"
      && typeof value.operation === "string"
      ? value as LeaseRecord
      : null;
  } catch {
    return null;
  }
}

function acquireDirectory(dir: string, record: LeaseRecord): boolean {
  try { mkdirSync(dir, { mode: 0o700 }); } catch { return false; }
  try {
    writeFileSync(metadataPath(dir), `${JSON.stringify(record)}\n`, { flag: "wx", mode: 0o600 });
    return true;
  } catch (error) {
    rmSync(dir, { recursive: true, force: true });
    throw error;
  }
}

function staleLease(dir: string): boolean {
  const stat = lstatSync(dir);
  if (!stat.isDirectory()) throw new Error(`Refusing non-directory project mutation lease: ${dir}`);
  const owner = readLease(dir);
  if (!owner) return Date.now() - stat.mtimeMs > INVALID_GRACE_MS;
  return !processAlive(owner.pid);
}

function releaseLease(dir: string, record: LeaseRecord): void {
  if (readLease(dir)?.nonce === record.nonce) rmSync(dir, { recursive: true, force: true });
}

/** One fail-fast writer lease shared by every mutation surface for a project. */
export function acquireProjectMutationLease(
  projectRoot: string,
  operation: string,
): ProjectMutationLeaseResult {
  const target = leaseDir(projectRoot);
  const record = { pid: process.pid, nonce: randomUUID(), operation, createdAt: new Date().toISOString() };
  for (let attempt = 0; attempt < 2; attempt += 1) {
    if (acquireDirectory(target, record)) {
      return { lease: { release: () => releaseLease(target, record) } };
    }
    try {
      if (!staleLease(target)) {
        const owner = readLease(target);
        return { conflict: { operation: owner?.operation, createdAt: owner?.createdAt } };
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") continue;
      throw error;
    }
    rmSync(target, { recursive: true, force: true });
  }
  return { conflict: {} };
}
