import {
  closeSync,
  constants,
  createReadStream,
  createWriteStream,
  fstatSync,
  openSync,
  type BigIntStats,
} from "node:fs";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { pipeline } from "node:stream/promises";

interface SourceIdentity {
  dev: bigint;
  ino: bigint;
  size: bigint;
  mtimeNs: bigint;
  ctimeNs: bigint;
}

export interface StableCopySource {
  source: string;
  relative: string;
  size: number;
  identity: SourceIdentity;
}

function identity(stat: BigIntStats): SourceIdentity {
  return {
    dev: stat.dev,
    ino: stat.ino,
    size: stat.size,
    mtimeNs: stat.mtimeNs,
    ctimeNs: stat.ctimeNs,
  };
}

function sameIdentity(stat: BigIntStats, expected: SourceIdentity): boolean {
  return stat.isFile() && stat.nlink === BigInt(1) &&
    stat.dev === expected.dev && stat.ino === expected.ino &&
    stat.size === expected.size && stat.mtimeNs === expected.mtimeNs &&
    stat.ctimeNs === expected.ctimeNs;
}

function closeDescriptor(descriptor: number): void {
  try {
    closeSync(descriptor);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EBADF") throw error;
  }
}

export function stableCopySource(
  source: string,
  relative: string,
  stat: BigIntStats,
): StableCopySource {
  return { source, relative, size: Number(stat.size), identity: identity(stat) };
}

export async function copyStableSource(
  entry: StableCopySource,
  destination: string,
  onChunk: (bytes: number) => void,
  signal: AbortSignal,
): Promise<void> {
  await mkdir(path.dirname(destination), { recursive: true });
  const descriptor = openSync(
    entry.source, constants.O_RDONLY | constants.O_NONBLOCK | (constants.O_NOFOLLOW ?? 0),
  );
  try {
    if (!sameIdentity(fstatSync(descriptor, { bigint: true }), entry.identity)) {
      throw new Error(`Source file changed before copy: ${entry.source}`);
    }
    const reader = createReadStream(
      entry.source, { fd: descriptor, autoClose: false },
    );
    reader.on("data", (chunk) => {
      try { onChunk(Buffer.byteLength(chunk)); }
      catch (error) { reader.destroy(error instanceof Error ? error : new Error(String(error))); }
    });
    await pipeline(
      reader, createWriteStream(destination, { flags: "wx" }), { signal },
    );
    if (!sameIdentity(fstatSync(descriptor, { bigint: true }), entry.identity)) {
      throw new Error(`Source file changed during copy: ${entry.source}`);
    }
  } finally {
    closeDescriptor(descriptor);
  }
}
