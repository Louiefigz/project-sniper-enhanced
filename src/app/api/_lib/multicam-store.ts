import { existsSync, unlinkSync } from "fs";
import { randomUUID } from "crypto";

interface Entry {
  zipPath: string;
  filename: string;
  createdAt: number;
}

const TTL_MS = 60 * 60 * 1000;

const store = new Map<string, Entry>();

function cleanup() {
  const now = Date.now();
  for (const [id, entry] of store) {
    if (now - entry.createdAt > TTL_MS) {
      if (existsSync(entry.zipPath)) {
        try { unlinkSync(entry.zipPath); } catch {}
      }
      store.delete(id);
    }
  }
}

export function register(zipPath: string, filename: string): string {
  cleanup();
  const id = randomUUID();
  store.set(id, { zipPath, filename, createdAt: Date.now() });
  return id;
}

export function take(id: string): Entry | null {
  const entry = store.get(id);
  if (!entry) return null;
  store.delete(id);
  return entry;
}
