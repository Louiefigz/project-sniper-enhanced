import {
  closeSync,
  fsyncSync,
  openSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { randomUUID } from "node:crypto";

export interface AtomicWriteOptions {
  mode?: number;
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
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
    rmSync(temporary, { force: true });
  }
}

export function atomicWriteJsonSync(destination: string, value: unknown): void {
  atomicWriteFileSync(destination, `${JSON.stringify(value, null, 1)}\n`);
}
