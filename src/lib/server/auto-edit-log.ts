import {
  closeSync,
  constants,
  existsSync,
  lstatSync,
  openSync,
  readSync,
  statSync,
  writeSync,
} from "fs";
import path from "path";

const MAX_LOG_BYTES = 1_000_000;
const NO_FOLLOW = constants.O_NOFOLLOW ?? 0;

export function autoEditLogPath(dir: string): string {
  return path.join(dir.replace(/\/$/, ""), ".sniper-auto-edit.log");
}

function assertRegularLog(logPath: string): void {
  if (!existsSync(logPath)) return;
  const stat = lstatSync(logPath);
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw new Error(`Refusing non-regular Auto Edit log: ${logPath}`);
  }
}

export function boundAutoEditLog(logPath: string): void {
  assertRegularLog(logPath);
  if (!existsSync(logPath) || statSync(logPath).size <= MAX_LOG_BYTES) return;
  const readFd = openSync(logPath, constants.O_RDONLY | NO_FOLLOW);
  const size = statSync(logPath).size;
  const tail = Buffer.alloc(MAX_LOG_BYTES);
  try { readSync(readFd, tail, 0, tail.length, size - tail.length); } finally { closeSync(readFd); }
  const writeFd = openSync(logPath, constants.O_WRONLY | constants.O_TRUNC | NO_FOLLOW);
  try { writeSync(writeFd, tail); } finally { closeSync(writeFd); }
}

/** Always append (never truncate): each attempt writes a boundary header so
 * a fresh Retry preserves the prior attempt's trail for diagnosis. */
export function prepareAutoEditLog(logPath: string, attempt: number): number {
  assertRegularLog(logPath);
  boundAutoEditLog(logPath);
  const flags = constants.O_WRONLY | constants.O_CREAT | constants.O_APPEND | NO_FOLLOW;
  const fd = openSync(logPath, flags, 0o600);
  writeSync(fd, `\n[SNIPER:auto-edit-worker] ===== attempt ${attempt} started ${new Date().toISOString()} =====\n`);
  return fd;
}
