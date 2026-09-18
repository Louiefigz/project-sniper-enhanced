import {
  closeSync,
  lstatSync,
  openSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "fs";
import { randomUUID } from "crypto";

const RETRIES = 200;
const WAIT_MS = 10;
const STALE_LOCK_MS = 30_000;
const HARD_LOCK_MAX_MS = 120_000;
const waiter = new Int32Array(new SharedArrayBuffer(4));

interface LockRecord {
  pid: number;
  nonce: string;
}

function pause(): void {
  Atomics.wait(waiter, 0, 0, WAIT_MS);
}

function lockRecord(lockPath: string): LockRecord | null {
  try {
    if (!lstatSync(lockPath).isFile()) return null;
    const value = JSON.parse(readFileSync(lockPath, "utf8")) as Partial<LockRecord>;
    return typeof value.pid === "number" && typeof value.nonce === "string"
      ? value as LockRecord
      : null;
  } catch {
    return null;
  }
}

function pidAlive(pid: number): boolean {
  try { process.kill(pid, 0); return true; } catch { return false; }
}

function acquire(lockPath: string, record: LockRecord): boolean {
  let fd: number;
  try { fd = openSync(lockPath, "wx", 0o600); } catch { return false; }
  try { writeFileSync(fd, `${JSON.stringify(record)}\n`); } finally { closeSync(fd); }
  return true;
}

function release(lockPath: string, record: LockRecord): void {
  if (lockRecord(lockPath)?.nonce === record.nonce) rmSync(lockPath, { force: true });
}

export function withAutoEditJobLock<T>(jobPath: string, operation: () => T): T {
  const lockPath = `${jobPath}.lock`;
  const record = { pid: process.pid, nonce: randomUUID() };
  for (let attempt = 0; attempt < RETRIES; attempt += 1) {
    if (acquire(lockPath, record)) {
      try { return operation(); } finally { release(lockPath, record); }
    }
    let stat: ReturnType<typeof lstatSync>;
    try { stat = lstatSync(lockPath); } catch { pause(); continue; }
    if (stat.isSymbolicLink()) throw new Error(`Refusing symbolic-link Auto Edit lock: ${lockPath}`);
    const owner = lockRecord(lockPath);
    const age = Date.now() - stat.mtimeMs;
    const stale = age > STALE_LOCK_MS;
    if (age > HARD_LOCK_MAX_MS || (owner && !pidAlive(owner.pid)) || (!owner && stale)) {
      rmSync(lockPath, { force: true });
      continue;
    }
    pause();
  }
  throw new Error(`Timed out acquiring Auto Edit job lock: ${lockPath}`);
}
