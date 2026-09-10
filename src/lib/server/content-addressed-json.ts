import { createHash, randomUUID } from "node:crypto";
import {
  closeSync,
  fsyncSync,
  linkSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import { canonicalJson } from "./auto-edit-hash";

export interface ContentAddressedJsonResult {
  hash: string;
  path: string;
  reused: boolean;
}

function sha256(bytes: Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function fsyncDirectory(directory: string): void {
  const descriptor = openSync(directory, "r");
  try {
    fsyncSync(descriptor);
  } finally {
    closeSync(descriptor);
  }
}

function ensureRealDirectory(directory: string): void {
  const parent = lstatSync(path.dirname(directory));
  if (!parent.isDirectory() || parent.isSymbolicLink()) {
    throw new Error("content-addressed authority parent must be a real directory");
  }
  try {
    mkdirSync(directory, { mode: 0o700 });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
  }
  const stat = lstatSync(directory);
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error("content-addressed authority directory must be a real directory");
  }
}

function assertExisting(destination: string, expected: Buffer): void {
  const stat = lstatSync(destination);
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw new Error("content-addressed authority is not a regular file");
  }
  const actual = readFileSync(destination);
  if (!actual.equals(expected)) {
    throw new Error("content-addressed authority bytes conflict with their hash path");
  }
}

function linkAuthority(
  temporary: string,
  destination: string,
  directory: string,
  bytes: Buffer,
): boolean {
  try {
    linkSync(temporary, destination);
    fsyncDirectory(directory);
    return false;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
    assertExisting(destination, bytes);
    return true;
  }
}

/** Publish canonical JSON once without permitting an existing hash path to change. */
export function writeContentAddressedJsonSync(
  directory: string,
  value: unknown,
): ContentAddressedJsonResult {
  const bytes = Buffer.from(canonicalJson(value), "utf8");
  const hash = sha256(bytes);
  ensureRealDirectory(directory);
  const destination = path.join(directory, `${hash}.json`);
  const temporary = path.join(directory, `.${hash}.${randomUUID()}.tmp`);
  let descriptor: number | undefined;
  try {
    descriptor = openSync(temporary, "wx", 0o600);
    writeFileSync(descriptor, bytes);
    fsyncSync(descriptor);
    closeSync(descriptor);
    descriptor = undefined;
    const reused = linkAuthority(temporary, destination, directory, bytes);
    return { hash, path: destination, reused };
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
    rmSync(temporary, { force: true });
    fsyncDirectory(directory);
  }
}
