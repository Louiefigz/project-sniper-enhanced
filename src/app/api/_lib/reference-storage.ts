import fs from "fs";
import path from "path";
import { atomicWriteJsonSync } from "@/lib/server/atomic-file";

export function atomicWriteJson(file: string, value: unknown): void {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  atomicWriteJsonSync(file, value);
}

export function readIgnoredIds(referenceRoot: string): Set<string> {
  const file = path.join(referenceRoot, ".ignored-references.json");
  try {
    const value = JSON.parse(fs.readFileSync(file, "utf8")) as unknown;
    return new Set(Array.isArray(value) ? value.filter((id): id is string => typeof id === "string") : []);
  } catch {
    return new Set();
  }
}

export function addIgnoredIds(referenceRoot: string, ids: string[]): void {
  const current = readIgnoredIds(referenceRoot);
  ids.forEach((id) => current.add(id));
  atomicWriteJson(path.join(referenceRoot, ".ignored-references.json"), [...current].sort());
}
