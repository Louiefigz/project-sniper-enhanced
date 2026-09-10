import { createHash, randomUUID } from "node:crypto";
import {
  closeSync,
  cpSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  openSync,
  readdirSync,
  readFileSync,
  renameSync,
  rmSync,
} from "node:fs";
import path from "node:path";

export type PromotionNodeState =
  | { kind: "missing" }
  | { kind: "file"; sha256: string; size: number }
  | { kind: "directory"; sha256: string };

export interface PromotionDurabilityHooks {
  afterFileSync?: (filePath: string) => void;
  afterDirectorySync?: (directory: string) => void;
}

function missing(error: unknown): boolean {
  return (error as NodeJS.ErrnoException).code === "ENOENT";
}

export function nodePresent(filePath: string): boolean {
  try {
    lstatSync(filePath);
    return true;
  } catch (error) {
    if (missing(error)) return false;
    throw error;
  }
}

function fileState(filePath: string): PromotionNodeState {
  const bytes = readFileSync(filePath);
  return {
    kind: "file",
    sha256: createHash("sha256").update(bytes).digest("hex"),
    size: bytes.length,
  };
}

function directoryState(directory: string): PromotionNodeState {
  const digest = createHash("sha256");
  for (const name of readdirSync(directory).sort()) {
    const state = nodeState(path.join(directory, name));
    digest.update(name).update("\0").update(JSON.stringify(state)).update("\0");
  }
  return { kind: "directory", sha256: digest.digest("hex") };
}

export function nodeState(filePath: string): PromotionNodeState {
  let stat;
  try {
    stat = lstatSync(filePath);
  } catch (error) {
    if (missing(error)) return { kind: "missing" };
    throw error;
  }
  if (stat.isSymbolicLink()) {
    throw new Error(`promotion path cannot be a symlink: ${filePath}`);
  }
  if (stat.isFile()) return fileState(filePath);
  if (stat.isDirectory()) return directoryState(filePath);
  throw new Error(`promotion path must be a file or directory: ${filePath}`);
}

export function sameNodeState(
  left: PromotionNodeState,
  right: PromotionNodeState,
): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function syncFile(
  filePath: string,
  hooks: PromotionDurabilityHooks = {},
): void {
  const descriptor = openSync(filePath, "r");
  try {
    fsyncSync(descriptor);
    hooks.afterFileSync?.(filePath);
  } finally {
    closeSync(descriptor);
  }
}

export function syncDirectory(
  directory: string,
  hooks: PromotionDurabilityHooks = {},
): void {
  const descriptor = openSync(directory, "r");
  try {
    fsyncSync(descriptor);
    hooks.afterDirectorySync?.(directory);
  } finally {
    closeSync(descriptor);
  }
}

export function syncFileAndParent(
  filePath: string,
  hooks: PromotionDurabilityHooks = {},
): void {
  syncFile(filePath, hooks);
  syncDirectory(path.dirname(filePath), hooks);
}

function syncTree(filePath: string): void {
  const stat = lstatSync(filePath);
  if (stat.isSymbolicLink()) {
    throw new Error(`promotion copy contains a symlink: ${filePath}`);
  }
  if (stat.isFile()) {
    syncFile(filePath);
    return;
  }
  if (!stat.isDirectory()) {
    throw new Error(`promotion copy contains a special node: ${filePath}`);
  }
  for (const name of readdirSync(filePath)) {
    syncTree(path.join(filePath, name));
  }
  syncDirectory(filePath);
}

function directoryChain(
  durableAncestor: string,
  directory: string,
): string[] {
  const root = path.resolve(durableAncestor);
  const target = path.resolve(directory);
  const relative = path.relative(root, target);
  if (relative === ".." || relative.startsWith(`..${path.sep}`)
      || path.isAbsolute(relative)) {
    throw new Error("promotion directory escapes its durable ancestor");
  }
  const result = [root];
  for (const part of relative.split(path.sep).filter(Boolean)) {
    result.push(path.join(result.at(-1)!, part));
  }
  return result;
}

export function ensureDurableDirectory(
  directory: string,
  durableAncestor: string,
  hooks: PromotionDurabilityHooks = {},
): void {
  const chain = directoryChain(durableAncestor, directory);
  for (const [index, current] of chain.entries()) {
    if (!nodePresent(current)) {
      if (index === 0) {
        throw new Error("promotion durable ancestor is missing");
      }
      mkdirSync(current, { mode: 0o700 });
    }
    const stat = lstatSync(current);
    if (!stat.isDirectory() || stat.isSymbolicLink()) {
      throw new Error(`promotion recovery root is not a directory: ${current}`);
    }
    syncDirectory(current, hooks);
    if (index > 0) syncDirectory(chain[index - 1]!, hooks);
  }
}

export function removeNodeDurable(filePath: string): void {
  if (!nodePresent(filePath)) return;
  rmSync(filePath, { recursive: true, force: true });
  syncDirectory(path.dirname(filePath));
}

function replaceFromTemporary(temporary: string, destination: string): void {
  removeNodeDurable(destination);
  renameSync(temporary, destination);
  syncDirectory(path.dirname(destination));
}

export function copyNodeDurable(
  source: string,
  destination: string,
  temporary?: string,
): void {
  const staging = temporary
    ?? path.join(path.dirname(destination), `.promotion-${randomUUID()}.tmp`);
  removeNodeDurable(staging);
  cpSync(source, staging, {
    recursive: true,
    force: false,
    errorOnExist: true,
  });
  syncTree(staging);
  replaceFromTemporary(staging, destination);
}

export function restoreNodeDurable(
  backup: string | null,
  destination: string,
  oldState: PromotionNodeState,
  temporary: string,
): void {
  if (oldState.kind === "missing") {
    removeNodeDurable(destination);
    removeNodeDurable(temporary);
    return;
  }
  if (!backup || !sameNodeState(nodeState(backup), oldState)) {
    throw new Error(`promotion backup is missing or torn: ${destination}`);
  }
  copyNodeDurable(backup, destination, temporary);
  if (!sameNodeState(nodeState(destination), oldState)) {
    throw new Error(`promotion backup did not restore exactly: ${destination}`);
  }
}
