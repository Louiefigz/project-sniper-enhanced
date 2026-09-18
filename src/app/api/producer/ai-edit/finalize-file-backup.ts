import { lstatSync, readFileSync, rmSync } from "node:fs";
import { atomicWriteFileSync } from "@/lib/server/atomic-file";

export interface FileBackup {
  path: string;
  previous: Buffer | null;
}

/** Capture exact sidecar bytes without following a non-regular authority node. */
export function backupFile(filePath: string): FileBackup {
  try {
    const stat = lstatSync(filePath);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.nlink !== 1) {
      throw new Error(`sidecar backup target is not one safe regular file: ${filePath}`);
    }
    return { path: filePath, previous: readFileSync(filePath) };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return { path: filePath, previous: null };
    }
    throw error;
  }
}

export function restoreFile(backup: FileBackup | null): void {
  if (!backup) return;
  if (backup.previous) atomicWriteFileSync(backup.path, backup.previous);
  else rmSync(backup.path, { force: true });
}

/** Run every recovery step even when an earlier cleanup action fails. */
export function runRecoveryActions(actions: Array<() => void>): unknown {
  let failure: unknown;
  for (const action of actions) {
    try {
      action();
    } catch (error) {
      failure ??= error;
    }
  }
  return failure;
}
