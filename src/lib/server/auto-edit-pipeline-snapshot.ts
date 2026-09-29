import { createHash } from "node:crypto";
import {
  closeSync,
  constants as fsConstants,
  existsSync,
  fstatSync,
  lstatSync,
  openSync,
  readFileSync,
  readdirSync,
} from "node:fs";
import path from "node:path";
import type {
  AutoEditPipelineAuthority,
  PipelineAuthorityFile,
} from "@/app/api/producer/auto-edit/stream";

const SHA256 = /^[0-9a-f]{64}$/;
const MAX_LOCK_BYTES = 8 * 1024 * 1024;
const MAX_PIPELINE_FILE_BYTES = 512 * 1024 * 1024;

export interface PipelineLock {
  schemaVersion: 1;
  state: "pinned";
  runId: string;
  digest: string;
  files: PipelineAuthorityFile[];
}

function readSingleLinkFile(file: string, maximum: number): Buffer {
  let fd: number | null = null;
  try {
    fd = openSync(file, fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW);
    const stat = fstatSync(fd);
    if (!stat.isFile() || stat.nlink !== 1 || stat.size > maximum) {
      throw new Error(`Pinned Producer pipeline file is not isolated: ${file}`);
    }
    return readFileSync(fd);
  } finally {
    if (fd !== null) closeSync(fd);
  }
}

/** Read the lock through one no-follow file descriptor. */
export function readPipelineLock(authority: AutoEditPipelineAuthority): PipelineLock {
  if (!path.isAbsolute(authority.lockPath) || !existsSync(authority.lockPath)) {
    throw new Error("Pinned Producer pipeline lock is missing");
  }
  const value: unknown = JSON.parse(
    readSingleLinkFile(authority.lockPath, MAX_LOCK_BYTES).toString("utf8"),
  );
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Pinned Producer pipeline lock is invalid");
  }
  const lock = value as PipelineLock;
  const valid = lock.schemaVersion === 1 && lock.state === "pinned"
    && typeof lock.runId === "string" && SHA256.test(lock.digest)
    && Array.isArray(lock.files);
  if (!valid) throw new Error("Pinned Producer pipeline lock is invalid");
  return lock;
}

function expectedDirectories(files: PipelineAuthorityFile[]): Set<string> {
  const directories = new Set<string>([""]);
  for (const row of files) {
    let current = path.posix.dirname(row.path);
    while (current !== ".") {
      directories.add(current);
      current = path.posix.dirname(current);
    }
  }
  return directories;
}

function assertClosedTree(root: string, files: PipelineAuthorityFile[]): void {
  const expectedFiles = new Set(files.map((row) => row.path));
  const directories = expectedDirectories(files);
  const visit = (directory: string, relative = ""): void => {
    for (const name of readdirSync(directory).sort()) {
      const logical = relative ? `${relative}/${name}` : name;
      const item = path.join(directory, name);
      const stat = lstatSync(item);
      if (stat.isSymbolicLink() || (!stat.isFile() && !stat.isDirectory())) {
        throw new Error(`Pinned Producer pipeline has unsafe entry: ${logical}`);
      }
      if (stat.isFile() && stat.nlink !== 1) {
        throw new Error(`Pinned Producer pipeline has hardlinked file: ${logical}`);
      }
      if (stat.isFile() && !expectedFiles.has(logical)) {
        throw new Error(`Pinned Producer pipeline has unlisted file: ${logical}`);
      }
      if (stat.isDirectory() && !directories.has(logical)) {
        throw new Error(`Pinned Producer pipeline has unlisted directory: ${logical}`);
      }
      if (stat.isDirectory()) visit(item, logical);
    }
  };
  visit(root);
}

/** Require a closed regular-file tree and verify every listed byte hash. */
export function verifyPipelineSnapshot(
  authority: AutoEditPipelineAuthority,
  files: PipelineAuthorityFile[],
): void {
  assertClosedTree(authority.snapshotRoot, files);
  const seen = new Set<string>();
  for (const row of files) {
    const valid = row && typeof row.path === "string" && row.path
      && !row.path.startsWith("/") && !row.path.split("/").includes("..")
      && typeof row.hash === "string" && SHA256.test(row.hash) && !seen.has(row.path);
    if (!valid) throw new Error("Pinned Producer pipeline receipt is invalid");
    seen.add(row.path);
    const copy = path.join(authority.snapshotRoot, ...row.path.split("/"));
    const actual = existsSync(copy)
      ? createHash("sha256").update(
        readSingleLinkFile(copy, MAX_PIPELINE_FILE_BYTES),
      ).digest("hex") : null;
    if (actual !== row.hash) {
      throw new Error(`Pinned Producer pipeline copy was changed: ${row.path}`);
    }
  }
}
