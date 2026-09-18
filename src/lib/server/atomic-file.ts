import {
  closeSync,
  fsyncSync,
  linkSync,
  openSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { randomUUID } from "node:crypto";
import path from "node:path";

export interface AtomicWriteOptions {
  mode?: number;
}

function fsyncParentSync(destination: string): void {
  const descriptor = openSync(path.dirname(path.resolve(destination)), "r");
  try {
    fsyncSync(descriptor);
  } finally {
    closeSync(descriptor);
  }
}

/** Replace one authority file without exposing a partial/truncated write. */
export function atomicWriteFileSync(
  destination: string,
  data: string | Buffer,
  options: AtomicWriteOptions = {},
): void {
  const temporary = `${destination}.${process.pid}.${randomUUID()}.tmp`;
  let descriptor: number | undefined;
  try {
    descriptor = openSync(temporary, "wx", options.mode ?? 0o600);
    writeFileSync(descriptor, data);
    fsyncSync(descriptor);
    closeSync(descriptor);
    descriptor = undefined;
    renameSync(temporary, destination);
    fsyncParentSync(destination);
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
    rmSync(temporary, { force: true });
  }
}

export function atomicWriteJsonSync(destination: string, value: unknown): void {
  atomicWriteFileSync(destination, `${JSON.stringify(value, null, 1)}\n`);
}

/** Publish a new authority file without replacing an existing identity. */
export function atomicCreateFileSync(
  destination: string,
  data: string | Buffer,
): void {
  const temporary = `${destination}.${process.pid}.${randomUUID()}.create`;
  let descriptor: number | undefined;
  try {
    descriptor = openSync(temporary, "wx", 0o600);
    writeFileSync(descriptor, data);
    fsyncSync(descriptor);
    closeSync(descriptor);
    descriptor = undefined;
    linkSync(temporary, destination);
    fsyncParentSync(destination);
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
    rmSync(temporary, { force: true });
  }
}

export function atomicCreateJsonSync(destination: string, value: unknown): void {
  atomicCreateFileSync(destination, `${JSON.stringify(value, null, 1)}\n`);
}
