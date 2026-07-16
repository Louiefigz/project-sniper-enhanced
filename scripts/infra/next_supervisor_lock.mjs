import { randomUUID } from "node:crypto";
import {
  linkSync,
  readFileSync,
  rmSync,
  statSync,
  utimesSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";

const LOCK_STARTUP_GRACE_MS = 2_000;
const LOCK_STALE_MS = 5 * 60_000;
export const LOCK_HEARTBEAT_MS = 30_000;

function pidAlive(pid) {
  if (!Number.isInteger(pid) || pid < 1) return false;
  try { process.kill(pid, 0); return true; } catch { return false; }
}

function lockSnapshot(lockPath) {
  try {
    const stat = statSync(lockPath);
    const pid = Number.parseInt(readFileSync(lockPath, "utf8").trim(), 10);
    return { pid, ageMs: Math.max(0, Date.now() - stat.mtimeMs) };
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}

function createLockAtomically(lockPath, pid) {
  const temporary = `${lockPath}.${pid}.${randomUUID()}.tmp`;
  writeFileSync(temporary, `${pid}\n`, { mode: 0o600 });
  try {
    linkSync(temporary, lockPath);
    return true;
  } catch (error) {
    if (error?.code === "EEXIST") return false;
    throw error;
  } finally {
    rmSync(temporary, { force: true });
  }
}

export function supervisorLockPath(root, port) {
  const key = createHash("sha256").update(`${root}\0${port}`).digest("hex").slice(0, 20);
  return path.join(os.tmpdir(), `project-sniper-next-${key}.pid`);
}

export function acquireSupervisorLock(lockPath, pid = process.pid) {
  for (let attempt = 0; attempt < 4; attempt += 1) {
    if (createLockAtomically(lockPath, pid)) return;
    const lock = lockSnapshot(lockPath);
    if (!lock) continue;
    if (!Number.isInteger(lock.pid) && lock.ageMs < LOCK_STARTUP_GRACE_MS) {
      throw new Error("Another Project Sniper supervisor is acquiring this port");
    }
    if (pidAlive(lock.pid) && lock.ageMs < LOCK_STALE_MS) {
      throw new Error(`Another Project Sniper supervisor (PID ${lock.pid}) owns this port`);
    }
    rmSync(lockPath, { force: true });
  }
  throw new Error("Could not acquire the Project Sniper supervisor lock");
}

export function heartbeatSupervisorLock(lockPath, pid = process.pid) {
  try {
    const lock = lockSnapshot(lockPath);
    if (!lock || lock.pid !== pid) return false;
    const now = new Date();
    utimesSync(lockPath, now, now);
    return true;
  } catch {
    return false;
  }
}

export function releaseSupervisorLock(lockPath, pid = process.pid) {
  try {
    if (lockSnapshot(lockPath)?.pid === pid) rmSync(lockPath, { force: true });
  } catch {}
}
