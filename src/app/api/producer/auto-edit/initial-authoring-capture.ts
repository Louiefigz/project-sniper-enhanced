import {
  closeSync,
  constants,
  fstatSync,
  openSync,
  readSync,
} from "node:fs";

interface OpenFileState {
  dev: number;
  ino: number;
  size: number;
  mtimeMs: number;
  ctimeMs: number;
  nlink: number;
}

function fileState(descriptor: number): OpenFileState & { regular: boolean } {
  const stat = fstatSync(descriptor);
  return {
    dev: stat.dev, ino: stat.ino, size: stat.size,
    mtimeMs: stat.mtimeMs, ctimeMs: stat.ctimeMs, nlink: stat.nlink,
    regular: stat.isFile(),
  };
}

function sameFile(left: OpenFileState, right: OpenFileState): boolean {
  return left.dev === right.dev && left.ino === right.ino
    && left.size === right.size && left.mtimeMs === right.mtimeMs
    && left.ctimeMs === right.ctimeMs && left.nlink === right.nlink;
}

function exactBytes(descriptor: number, size: number, label: string): Buffer {
  const bytes = Buffer.alloc(size);
  let offset = 0;
  while (offset < bytes.length) {
    const count = readSync(descriptor, bytes, offset, bytes.length - offset, offset);
    if (count < 1) throw new Error(`${label} changed during controller capture`);
    offset += count;
  }
  return bytes;
}

/** Read one no-follow, single-link file into controller memory. */
export function readBoundedAuthoringFile(
  source: string,
  label: string,
  maxBytes: number,
): Buffer {
  let descriptor: number | undefined;
  try {
    descriptor = openSync(source, constants.O_RDONLY | constants.O_NOFOLLOW);
    const before = fileState(descriptor);
    if (!before.regular || before.nlink !== 1 || before.size < 2
        || before.size > maxBytes) {
      throw new Error(`${label} must be one bounded single-link regular file`);
    }
    const bytes = exactBytes(descriptor, before.size, label);
    if (!sameFile(before, fileState(descriptor))) {
      throw new Error(`${label} changed during controller capture`);
    }
    return bytes;
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
  }
}
