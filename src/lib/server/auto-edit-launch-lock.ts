import {
  lstatSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "fs";
import path from "path";
import { randomUUID } from "crypto";
import { processAlive } from "./process-liveness";

const INVALID_GRACE_MS = 30_000;
const MAX_LEASE_MS = 120_000;

interface LeaseRecord {
  pid: number;
  nonce: string;
  createdAt: string;
}

export interface AutoEditLaunchLease {
  release: () => void;
}

function leaseDir(dir: string): string {
  return path.join(dir.replace(/\/$/, ""), ".sniper-auto-edit-launch.lock");
}

function metadataPath(dir: string): string {
  return path.join(dir, "owner.json");
}

function readLease(dir: string): LeaseRecord | null {
  try {
    const value = JSON.parse(readFileSync(metadataPath(dir), "utf8")) as Partial<LeaseRecord>;
    return typeof value.pid === "number" && typeof value.nonce === "string"
      ? value as LeaseRecord
      : null;
  } catch {
    return null;
  }
}

function acquireDirectory(dir: string, record: LeaseRecord): boolean {
  try { mkdirSync(dir, { mode: 0o700 }); } catch { return false; }
  writeFileSync(metadataPath(dir), `${JSON.stringify(record)}\n`, { flag: "wx", mode: 0o600 });
  return true;
}

function staleLease(dir: string): boolean {
  const stat = lstatSync(dir);
  if (!stat.isDirectory()) throw new Error(`Refusing non-directory Auto Edit lease: ${dir}`);
  const age = Date.now() - stat.mtimeMs;
  const owner = readLease(dir);
  if (age > MAX_LEASE_MS) return true;
  if (!owner) return age > INVALID_GRACE_MS;
  return !processAlive(owner.pid);
}

export function acquireAutoEditLaunchLease(dir: string): AutoEditLaunchLease | null {
  const target = leaseDir(dir);
  const record = { pid: process.pid, nonce: randomUUID(), createdAt: new Date().toISOString() };
  for (let attempt = 0; attempt < 2; attempt += 1) {
    if (acquireDirectory(target, record)) {
      return {
        release: () => {
          if (readLease(target)?.nonce === record.nonce) rmSync(target, { recursive: true, force: true });
        },
      };
    }
    try {
      if (!staleLease(target)) return null;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") continue;
      throw error;
    }
    rmSync(target, { recursive: true, force: true });
  }
  return null;
}
