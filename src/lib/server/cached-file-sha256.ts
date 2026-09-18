import { createHash } from "node:crypto";
import {
  closeSync,
  openSync,
  readSync,
  realpathSync,
  statSync,
} from "node:fs";

interface CacheRow {
  signature: string;
  hash: string;
}

const CACHE = new Map<string, CacheRow>();
const MAX_ROWS = 64;

function signature(filePath: string): string {
  const stat = statSync(filePath, { bigint: true });
  return [stat.dev, stat.ino, stat.size, stat.mtimeNs, stat.ctimeNs].join(":");
}

function hashFile(filePath: string): string {
  const hash = createHash("sha256");
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  const descriptor = openSync(filePath, "r");
  try {
    for (;;) {
      const count = readSync(descriptor, buffer, 0, buffer.length, null);
      if (!count) break;
      hash.update(buffer.subarray(0, count));
    }
  } finally {
    closeSync(descriptor);
  }
  return hash.digest("hex");
}

/** Cache a chunked SHA-256 only while the file's full inode/stat identity matches. */
export function cachedFileSha256(filePath: string): string {
  const canonical = realpathSync(filePath);
  const current = signature(canonical);
  const cached = CACHE.get(canonical);
  if (cached?.signature === current) return cached.hash;
  const hash = hashFile(canonical);
  const after = signature(canonical);
  if (after !== current) throw new Error(`File changed while hashing: ${canonical}`);
  CACHE.set(canonical, { signature: after, hash });
  while (CACHE.size > MAX_ROWS) CACHE.delete(CACHE.keys().next().value!);
  return hash;
}
