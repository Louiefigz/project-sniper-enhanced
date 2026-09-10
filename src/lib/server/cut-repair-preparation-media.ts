import {
  copyFileSync,
  existsSync,
  lstatSync,
  mkdirSync,
  realpathSync,
  renameSync,
  rmSync,
} from "node:fs";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { objectValue } from "@/lib/producer/contracts/validation";
import { fileSha256 } from "./auto-edit-hash";
import {
  assertContentAddressedFileSync,
  writeContentAddressedFileSync,
} from "./content-addressed-file";
import { producerAuthorityPaths } from "./producer-authority-files";

interface PreparedMediaIdentity {
  producerDir: string;
  path: string;
  hash: string;
  extension: ".mov" | ".mp4";
}

function realDirectory(directory: string): void {
  if (!existsSync(directory)) mkdirSync(directory, { mode: 0o700 });
  const stat = lstatSync(directory);
  if (!stat.isDirectory() || stat.isSymbolicLink()
      || realpathSync(directory) !== directory) {
    throw new Error("cut repair prepared media path must be a real directory");
  }
}

function stagingRoot(producerDir: string): string {
  const producer = realpathSync(producerDir);
  if (producer !== path.resolve(producerDir)) {
    throw new Error("cut repair producer path must be canonical");
  }
  return path.join(producer, ".sniper-cut-repair-staging");
}

function ensureStagingTree(producerDir: string, directory: string): void {
  const root = stagingRoot(producerDir);
  const relative = path.relative(root, directory);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error("cut repair prepared media directory escaped staging");
  }
  realDirectory(root);
  let cursor = root;
  for (const part of relative.split(path.sep)) {
    cursor = path.join(cursor, part);
    realDirectory(cursor);
  }
}

/** Validate the lexical controller-owned path even when bytes need restoring. */
export function preparedStagingPath(
  producerDir: string,
  candidatePath: string,
  label: string,
): string {
  if (!path.isAbsolute(candidatePath)) {
    throw new Error(`${label} path is not absolute`);
  }
  const candidate = path.resolve(candidatePath);
  const root = stagingRoot(producerDir);
  if (candidate !== candidatePath
      || !candidate.startsWith(`${root}${path.sep}`)) {
    throw new Error(`${label} escaped controller staging`);
  }
  return candidate;
}

export function receiptMediaPath(
  producerDir: string,
  receipt: Record<string, unknown>,
): string {
  const output = objectValue(receipt.output, "prepared media output");
  if (typeof output.path !== "string") {
    throw new Error("prepared media output path is absent");
  }
  return preparedStagingPath(
    producerDir, output.path, "prepared media output");
}

/** Capture one already-proved private media file by its immutable digest. */
export function storePreparedMediaSync(input: PreparedMediaIdentity): void {
  const candidate = preparedStagingPath(
    input.producerDir, input.path, "prepared media");
  const paths = producerAuthorityPaths(input.producerDir);
  writeContentAddressedFileSync(
    paths.objects.media, candidate, input.hash, input.extension);
}

/** Restore one private media file without accepting path or byte substitution. */
export function restorePreparedMediaSync(input: PreparedMediaIdentity): void {
  const destination = preparedStagingPath(
    input.producerDir, input.path, "prepared media");
  const paths = producerAuthorityPaths(input.producerDir);
  assertContentAddressedFileSync(
    paths.objects.media, input.hash, input.extension);
  if (existsSync(destination)) {
    const stat = lstatSync(destination);
    if (!stat.isFile() || stat.isSymbolicLink()
        || realpathSync(destination) !== destination
        || fileSha256(destination) !== input.hash) {
      throw new Error("prepared staging media was tampered");
    }
    return;
  }
  ensureStagingTree(input.producerDir, path.dirname(destination));
  const source = path.join(
    paths.objects.media, `${input.hash}${input.extension}`);
  const temporary = `${destination}.${randomUUID()}.tmp`;
  try {
    copyFileSync(source, temporary);
    if (fileSha256(temporary) !== input.hash) {
      throw new Error("prepared media restore changed bytes");
    }
    renameSync(temporary, destination);
  } finally {
    rmSync(temporary, { force: true });
  }
}
