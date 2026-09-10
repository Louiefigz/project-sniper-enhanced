import fs from "fs";
import os from "os";
import path from "path";
import { workspaceOverride } from "./workspace";

// PROJECT BROWSER registry — a JSON file at ~/.project-sniper/projects.json
// mapping render out-dirs to titles, so the producer page can list "Recent
// edits" across sessions. Upserted by the flow render route on completion and
// by the editor when it opens a dir; read by GET /api/producer/projects.
// Entries with kind:"reference" are polished study videos registered under
// <workspaceRoot>/_references/ — listed by the References section, never by
// Recent edits.

export type EntryKind = "reference"; // absent = a project (render out dir)

export interface ProjectEntry {
  dir: string;
  title: string;
  updatedAt: string; // ISO — last upsert (render finished / editor opened)
  kind?: EntryKind;
}

export interface ProjectListing extends ProjectEntry {
  exists: boolean;
  mtime: number | null; // dir mtime (ms) when it exists
}

function registryPath(): string {
  const isolated = workspaceOverride();
  return path.join(isolated ?? os.homedir(), ".project-sniper", "projects.json");
}

function readRegistry(): ProjectEntry[] {
  const file = registryPath();
  if (!fs.existsSync(file)) return [];
  const parsed = JSON.parse(fs.readFileSync(file, "utf-8")) as unknown;
  if (!Array.isArray(parsed)) throw new Error(`${file} is not a JSON array`);
  return parsed.filter(
    (e): e is ProjectEntry =>
      !!e && typeof e === "object" && typeof (e as ProjectEntry).dir === "string",
  );
}

function writeRegistry(entries: ProjectEntry[]): void {
  const file = registryPath();
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(entries, null, 1));
}

/** Upsert one entry (keyed by dir); bumps updatedAt so it sorts to the top. */
export function upsertProject(dir: string, title: string, kind?: EntryKind): void {
  const clean = dir.replace(/\/$/, "");
  const entries = readRegistry().filter((e) => e.dir !== clean);
  entries.push({
    dir: clean,
    title: title || path.basename(clean),
    updatedAt: new Date().toISOString(),
    ...(kind ? { kind } : {}),
  });
  writeRegistry(entries);
}

/** Remove one project from the registry (the dir itself is never touched). */
export function removeProject(dir: string): void {
  const clean = dir.replace(/\/$/, "");
  writeRegistry(readRegistry().filter((e) => e.dir !== clean));
}

function probe(entries: ProjectEntry[]): ProjectListing[] {
  return entries
    .sort((a, b) => (a.updatedAt < b.updatedAt ? 1 : -1))
    .map((e) => {
      try {
        const st = fs.statSync(e.dir);
        return { ...e, exists: st.isDirectory(), mtime: st.mtimeMs };
      } catch {
        return { ...e, exists: false, mtime: null };
      }
    });
}

/** All registered projects, newest-first, with an existence + mtime probe. */
export function listProjects(): ProjectListing[] {
  return probe(readRegistry().filter((e) => e.kind !== "reference"));
}

/** All registered reference videos (kind:"reference"), newest-first. */
export function listReferences(): ProjectListing[] {
  return probe(readRegistry().filter((e) => e.kind === "reference"));
}
