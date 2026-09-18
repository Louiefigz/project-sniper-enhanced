import { randomUUID } from "node:crypto";
import {
  closeSync,
  copyFileSync,
  existsSync,
  fsyncSync,
  linkSync,
  lstatSync,
  mkdirSync,
  openSync,
  realpathSync,
  rmSync,
} from "node:fs";
import path from "node:path";
import { fileSha256 } from "./auto-edit-hash";

function realDirectory(directory: string): void {
  if (!existsSync(directory)) mkdirSync(directory, { mode: 0o700 });
  const stat = lstatSync(directory);
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error("content-addressed media directory must be real");
  }
}

function fsyncDirectory(directory: string): void {
  const descriptor = openSync(directory, "r");
  try {
    fsyncSync(descriptor);
  } finally {
    closeSync(descriptor);
  }
}

function stableRegularFile(filePath: string): {
  canonical: string;
  device: number;
  inode: number;
  size: number;
} {
  const stat = lstatSync(filePath);
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw new Error("content-addressed media source must be a regular file");
  }
  return {
    canonical: realpathSync(filePath),
    device: stat.dev,
    inode: stat.ino,
    size: stat.size,
  };
}

function assertSourceStable(
  filePath: string,
  expected: ReturnType<typeof stableRegularFile>,
): void {
  const actual = stableRegularFile(filePath);
  if (actual.canonical !== expected.canonical
      || actual.device !== expected.device || actual.inode !== expected.inode
      || actual.size !== expected.size) {
    throw new Error("content-addressed media source changed during capture");
  }
}

function existingMatches(destination: string, expectedHash: string): void {
  const stat = lstatSync(destination);
  if (!stat.isFile() || stat.isSymbolicLink()
      || fileSha256(destination) !== expectedHash) {
    throw new Error("content-addressed media conflicts with its hash path");
  }
}

function linkMedia(
  temporary: string,
  destination: string,
  directory: string,
  expectedHash: string,
): boolean {
  try {
    linkSync(temporary, destination);
    fsyncDirectory(directory);
    return false;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
    existingMatches(destination, expectedHash);
    return true;
  }
}

/** Copy a stable regular file into immutable hash-addressed authority storage. */
export function writeContentAddressedFileSync(
  directory: string,
  sourcePath: string,
  expectedHash: string,
  extension: string,
): { hash: string; path: string; reused: boolean } {
  const before = stableRegularFile(sourcePath);
  if (before.canonical !== path.resolve(sourcePath)) {
    throw new Error("content-addressed media source path must be canonical");
  }
  const observed = fileSha256(sourcePath);
  if (observed !== expectedHash) {
    throw new Error("proved media bytes do not match their receipt");
  }
  realDirectory(directory);
  const destination = path.join(directory, `${expectedHash}${extension}`);
  const temporary = path.join(directory, `.${expectedHash}.${randomUUID()}.tmp`);
  try {
    copyFileSync(sourcePath, temporary);
    if (fileSha256(temporary) !== expectedHash) {
      throw new Error("media changed while copied into authority storage");
    }
    assertSourceStable(sourcePath, before);
    const reused = linkMedia(
      temporary, destination, directory, expectedHash);
    return { hash: expectedHash, path: destination, reused };
  } finally {
    rmSync(temporary, { force: true });
    fsyncDirectory(directory);
  }
}

/** Reopen one stored media hash and reject substitution. */
export function assertContentAddressedFileSync(
  directory: string,
  hash: string,
  extension: string,
): void {
  existingMatches(path.join(directory, `${hash}${extension}`), hash);
}
