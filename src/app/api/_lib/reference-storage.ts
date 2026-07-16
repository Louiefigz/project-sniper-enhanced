import fs from "fs";
import path from "path";

export function atomicWriteJson(file: string, value: unknown): void {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temp = `${file}.${process.pid}.${Date.now().toString(36)}.tmp`;
  try {
    fs.writeFileSync(temp, JSON.stringify(value, null, 2) + "\n", { flag: "wx" });
    fs.renameSync(temp, file);
  } finally {
    try { if (fs.existsSync(temp)) fs.unlinkSync(temp); } catch {}
  }
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
