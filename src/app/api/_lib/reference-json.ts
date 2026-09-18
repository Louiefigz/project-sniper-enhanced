import fs from "fs";
import path from "path";

const MAX_CACHE_ENTRIES = 64;
const MAX_CACHE_FILE_BYTES = 128 * 1024;
const MAX_CACHE_SOURCE_BYTES = 1024 * 1024;
const DEEP_STUDY_HEAD_BYTES = 64 * 1024;

interface CacheEntry {
  key: string;
  sourceBytes: number;
  value: unknown;
}

const jsonCache = new Map<string, CacheEntry>();
let cachedSourceBytes = 0;

function removeCached(file: string): void {
  const cached = jsonCache.get(file);
  if (!cached) return;
  cachedSourceBytes -= cached.sourceBytes;
  jsonCache.delete(file);
}

function trimCache(): void {
  while (jsonCache.size > MAX_CACHE_ENTRIES || cachedSourceBytes > MAX_CACHE_SOURCE_BYTES) {
    const oldest = jsonCache.keys().next().value as string | undefined;
    if (!oldest) return;
    removeCached(oldest);
  }
}

/** Parse JSON while retaining only a bounded LRU of small control documents. */
export function readReferenceJson<T>(file: string): T | null {
  const resolved = path.resolve(file);
  try {
    const stat = fs.statSync(resolved);
    const key = `${stat.dev}:${stat.ino}:${stat.size}:${stat.mtimeMs}:${stat.ctimeMs}`;
    const cached = jsonCache.get(resolved);
    if (cached?.key === key) {
      jsonCache.delete(resolved);
      jsonCache.set(resolved, cached);
      return cached.value as T;
    }
    removeCached(resolved);
    const value = JSON.parse(fs.readFileSync(resolved, "utf8")) as T;
    if (stat.size <= MAX_CACHE_FILE_BYTES) {
      jsonCache.set(resolved, { key, sourceBytes: stat.size, value });
      cachedSourceBytes += stat.size;
      trimCache();
    }
    return value;
  } catch {
    removeCached(resolved);
    return null;
  }
}

/** Read the generated study's leading video field without parsing its signal arrays. */
export function readDeepStudyVideo(file: string): string | null {
  try {
    const stat = fs.statSync(file);
    const size = Math.min(stat.size, DEEP_STUDY_HEAD_BYTES);
    const fd = fs.openSync(file, "r");
    const buffer = Buffer.allocUnsafe(size);
    try {
      fs.readSync(fd, buffer, 0, size, 0);
    } finally {
      fs.closeSync(fd);
    }
    const match = buffer.toString("utf8").match(/^\s*\{\s*"video"\s*:\s*("(?:\\.|[^"\\])*")/);
    if (match) {
      const value = JSON.parse(match[1]) as unknown;
      if (typeof value === "string") return value;
    }
    const payload = JSON.parse(fs.readFileSync(file, "utf8")) as { video?: unknown };
    return typeof payload.video === "string" ? payload.video : null;
  } catch {
    return null;
  }
}

/** Remove cached control documents owned by a hidden or removed reference. */
export function evictReferenceJsonUnder(dir: string): void {
  const resolved = path.resolve(dir);
  const prefix = `${resolved}${path.sep}`;
  for (const file of [...jsonCache.keys()]) {
    if (file === resolved || file.startsWith(prefix)) removeCached(file);
  }
}

/** Small diagnostic surface used by focused cache regression tests. */
export function referenceJsonCacheStats(): { entries: number; sourceBytes: number } {
  return { entries: jsonCache.size, sourceBytes: cachedSourceBytes };
}
