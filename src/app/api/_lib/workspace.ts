import fs from "fs";
import os from "os";
import path from "path";
import type {
  IntentCapabilityDecision,
  IntentCapabilityResolution,
} from "@/lib/producer/intent-capabilities";
import type { ProjectIntent } from "@/lib/producer/intent-presets";
import { atomicWriteJsonSync } from "@/lib/server/atomic-file";

// WORKSPACE + PROVENANCE — the shared project layout every tool writes into:
//   <workspaceRoot>/<slug>/           project root, owns project.json
//     project.json                    {origin, history[], sourceMode?, intent?}
//     source/                         footage copies + asset_manifest.json + transcripts
//     segments/                       SEGMENTER exports (one mp4 per segment)
//     clipper/                        CLIPPER fcpxml copies
//     producer/                       render out dir (edit_plan.json, base/final.mp4)
// Stages beyond the origin are DERIVED FROM DISK (project-status route) — the
// project.json history is a provenance log, never the source of truth.

export type ProjectOrigin = "segmenter" | "clipper" | "raw";

export interface HistoryEntry {
  stage: string;
  at: string; // ISO timestamp
}

export interface ProjectJson {
  origin: ProjectOrigin;
  history: HistoryEntry[];
  sourceMode?: "referenced"; // >2GB footage left in place (absent = copied)
  /** Effective intent consumed by Auto Edit; retained for legacy readers. */
  intent?: ProjectIntent;
  /** Exact request before deterministic manifest-capability reconciliation. */
  requestedIntent?: ProjectIntent;
  /** Explicit effective intent after capability reconciliation. */
  resolvedIntent?: ProjectIntent;
  /** Human-readable, deterministic changes or blockers applied to the request. */
  intentDecisions?: IntentCapabilityDecision[];
}

const CONFIG_DIR = path.join(os.homedir(), ".project-sniper");
const CONFIG = path.join(CONFIG_DIR, "config.json");
const DEFAULT_ROOT = path.join(os.homedir(), "ProjectSniper");

/** Workspace root from ~/.project-sniper/config.json — created with the default on first read. */
export function workspaceRoot(): string {
  if (!fs.existsSync(CONFIG)) {
    fs.mkdirSync(CONFIG_DIR, { recursive: true });
    fs.writeFileSync(CONFIG, JSON.stringify({ workspaceRoot: DEFAULT_ROOT }, null, 1));
    return DEFAULT_ROOT;
  }
  const cfg = JSON.parse(fs.readFileSync(CONFIG, "utf-8")) as { workspaceRoot?: unknown };
  if (typeof cfg.workspaceRoot !== "string" || !path.isAbsolute(cfg.workspaceRoot)) {
    throw new Error(`${CONFIG} has no absolute "workspaceRoot"`);
  }
  return cfg.workspaceRoot;
}

/** kebab-case a footage basename (extension stripped) for use as a project slug. */
export function slugify(name: string): string {
  const base = name.replace(/\.[A-Za-z0-9]+$/, "");
  const slug = base
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug || "project";
}

/** yyyymmdd stamp for project slugs. */
export function dateStamp(d: Date = new Date()): string {
  return d.toISOString().slice(0, 10).replace(/-/g, "");
}

/**
 * Create a new project root `<workspaceRoot>/<slug>-<yyyymmdd>` (de-duped with
 * a -2/-3… suffix) and return its path. The directory is created.
 */
export function createProjectRoot(footageName: string): string {
  const root = workspaceRoot();
  const base = `${slugify(footageName)}-${dateStamp()}`;
  let candidate = path.join(root, base);
  for (let n = 2; fs.existsSync(candidate); n++) {
    candidate = path.join(root, `${base}-${n}`);
  }
  fs.mkdirSync(candidate, { recursive: true });
  return candidate;
}

export function projectJsonPath(projectRoot: string): string {
  return path.join(projectRoot, "project.json");
}

/** Read <root>/project.json, or null when absent (untagged legacy project). */
export function readProjectJson(projectRoot: string): ProjectJson | null {
  const p = projectJsonPath(projectRoot);
  if (!fs.existsSync(p)) return null;
  const parsed = JSON.parse(fs.readFileSync(p, "utf-8")) as ProjectJson;
  if (!parsed || typeof parsed.origin !== "string") {
    throw new Error(`${p} has no "origin"`);
  }
  return { ...parsed, history: Array.isArray(parsed.history) ? parsed.history : [] };
}

export function writeProjectJson(projectRoot: string, data: ProjectJson): void {
  atomicWriteJsonSync(projectJsonPath(projectRoot), data);
}

/** Set the operator's edit intent on <root>/project.json (which must exist). */
export function setProjectIntent(projectRoot: string, intent: ProjectIntent): void {
  const current = readProjectJson(projectRoot);
  if (!current) throw new Error(`no project.json in ${projectRoot}`);
  writeProjectJson(projectRoot, {
    ...current,
    intent,
    requestedIntent: intent,
    resolvedIntent: intent,
    intentDecisions: [],
  });
}

/** Persist requested and effective intent separately; blockers clear execution authority. */
export function setProjectIntentResolution(
  projectRoot: string,
  resolution: IntentCapabilityResolution,
): void {
  const current = readProjectJson(projectRoot);
  if (!current) throw new Error(`no project.json in ${projectRoot}`);
  writeProjectJson(projectRoot, resolvedProjectIntent(current, resolution));
}

function resolvedProjectIntent(
  current: ProjectJson,
  resolution: IntentCapabilityResolution,
): ProjectJson {
  const next: ProjectJson = { ...current,
    requestedIntent: resolution.requestedIntent,
    intentDecisions: resolution.decisions };
  if (resolution.resolvedIntent) {
    next.intent = resolution.resolvedIntent;
    next.resolvedIntent = resolution.resolvedIntent;
    return next;
  }
  delete next.intent;
  delete next.resolvedIntent;
  return next;
}

/** Persist intent authority and its provenance as one atomic project.json commit. */
export function recordProjectIntentResolution(
  projectRoot: string,
  resolution: IntentCapabilityResolution,
  stage: string,
): void {
  const current = readProjectJson(projectRoot);
  if (!current) throw new Error(`no project.json in ${projectRoot}`);
  const next = resolvedProjectIntent(current, resolution);
  next.history = [...next.history, { stage, at: new Date().toISOString() }];
  writeProjectJson(projectRoot, next);
}

/** Append one provenance entry to <root>/project.json (which must exist). */
export function appendHistory(projectRoot: string, stage: string): void {
  const current = readProjectJson(projectRoot);
  if (!current) throw new Error(`no project.json in ${projectRoot}`);
  current.history = [...current.history, { stage, at: new Date().toISOString() }];
  writeProjectJson(projectRoot, current);
}

/**
 * Locate the project root for a dir the registry knows about. The dir is
 * either the project root itself (segmenter/clipper entries) or the project's
 * producer/ dir. Legacy out-dirs outside the workspace layout return null.
 */
export function findProjectRoot(dir: string): string | null {
  const clean = dir.replace(/\/$/, "");
  if (fs.existsSync(projectJsonPath(clean))) return clean;
  const parent = path.dirname(clean);
  if (fs.existsSync(projectJsonPath(parent))) return parent;
  // Untagged workspace layout (pre-provenance projects): producer/ beside source/.
  if (path.basename(clean) === "producer" && fs.existsSync(path.join(parent, "source"))) {
    return parent;
  }
  return null;
}

/** Recursive byte size of a file or directory (for the ≤2GB copy rule). */
export function pathSizeBytes(p: string): number {
  const st = fs.statSync(p);
  if (st.isFile()) return st.size;
  if (!st.isDirectory()) return 0;
  return fs
    .readdirSync(p)
    .reduce((sum, name) => sum + pathSizeBytes(path.join(p, name)), 0);
}
