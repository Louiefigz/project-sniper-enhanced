import {
  existsSync, lstatSync, mkdirSync, readFileSync, readdirSync,
} from "node:fs";
import path from "node:path";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import { workspaceRoot } from "@/app/api/_lib/workspace";
import { COMPS_CATALOG } from "@/lib/producer/comps-catalog";
import { atomicWriteJsonSync } from "./atomic-file";
import { readApproval, type ApprovalRecord } from "./auto-edit-quality-artifacts";
import { canonicalJsonSha256, fileSha256 } from "./auto-edit-hash";
import { projectPalmierState } from "./project-palmier-state";

const WINDOW_PROJECTS = 8;
const MIN_OVERUSED_PROJECTS = 3;
const MIN_OVERUSED_SHARE = 0.5;

interface UsageProject {
  projectId: string;
  approvedAt: string;
  planHash: string;
  uses: Record<string, number>;
}

export interface TemplateUsageHistory {
  schemaVersion: 1;
  kind: "producer-template-usage-history";
  mode: "short" | "longform";
  windowProjects: number;
  projectCount: number;
  projects: UsageProject[];
  counts: Record<string, { uses: number; projects: number; lastUsedAt: string }>;
  overusedKinds: string[];
  policy: { minProjects: number; minProjectShare: number };
  digest: string;
}

export interface TemplateUsageAuthority {
  schemaVersion: 1;
  path: string;
  digest: string;
}

export interface BoundTemplateUsage {
  authority: TemplateUsageAuthority;
  history: TemplateUsageHistory;
}

export function validTemplateUsageAuthority(value: unknown): value is TemplateUsageAuthority {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as Partial<TemplateUsageAuthority>;
  return row.schemaVersion === 1 && typeof row.path === "string" && path.isAbsolute(row.path)
    && typeof row.digest === "string" && /^[0-9a-f]{64}$/.test(row.digest);
}

export interface TemplateUsageDependencies {
  approved?: (producerDir: string) => Pick<ApprovalRecord, "approvedAt" | "planHash"> | null;
  projectDirs?: (root: string) => string[];
}

function digest(value: unknown): string {
  return canonicalJsonSha256(value);
}

function defaultProjectDirs(root: string): string[] {
  if (!existsSync(root)) return [];
  return readdirSync(root).sort().flatMap((name) => {
    const project = path.join(root, name);
    try {
      return lstatSync(project).isDirectory() && !lstatSync(project).isSymbolicLink()
        ? [project] : [];
    } catch { return []; }
  });
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

/** A Palmier-aware project may teach only while its approved Sniper mirror is current. */
function palmierMatchesApprovedPlan(producerDir: string, approvedPlanHash: string): boolean {
  const statePath = path.join(producerDir, "palmier.sync.json");
  if (!existsSync(statePath)) return true;
  try {
    if (projectPalmierState(producerDir).state !== "approved_mirror") return false;
    const state = objectValue(JSON.parse(readFileSync(statePath, "utf8")));
    const verification = objectValue(state?.verification);
    const parity = objectValue(state?.parity);
    const timelineId = state?.latestTimelineId;
    return state?.schemaVersion === 4
      && state.ownership === "sniper"
      && state.workspaceMode === "verified-mirror"
      && state.mirrorMode === "visual-master"
      && state.lastPushPlanHash === approvedPlanHash
      && typeof timelineId === "string" && timelineId.length > 0
      && parity?.mirrorReady === true
      && verification?.ok === true
      && verification.planHash === approvedPlanHash
      && verification.timelineId === timelineId;
  } catch { return false; }
}

function planUsage(
  producerDir: string,
  mode: string,
  approvedPlanHash: string,
): Record<string, number> | null {
  try {
    const planPath = path.join(producerDir, "edit_plan.json");
    if (fileSha256(planPath) !== approvedPlanHash) return null;
    const plan = JSON.parse(readFileSync(planPath, "utf8"));
    if (plan?.target?.mode !== mode || !Array.isArray(plan.graphicsTrack)) return null;
    const known = new Set(COMPS_CATALOG.map((item) => item.kind));
    const uses: Record<string, number> = {};
    for (const row of plan.graphicsTrack) {
      const kind = row && typeof row === "object" ? row.kind : null;
      if (typeof kind === "string" && known.has(kind)) uses[kind] = (uses[kind] ?? 0) + 1;
    }
    return uses;
  } catch { return null; }
}

function recentProjects(
  ctx: AutoEditCtx,
  root: string,
  deps: TemplateUsageDependencies,
): UsageProject[] {
  const current = path.resolve(path.dirname(ctx.dir));
  const approved = deps.approved ?? readApproval;
  const dirs = (deps.projectDirs ?? defaultProjectDirs)(root);
  return dirs.flatMap((project): UsageProject[] => {
    if (path.resolve(project) === current) return [];
    const producerDir = path.join(project, "producer");
    const approval = approved(producerDir);
    const uses = approval && palmierMatchesApprovedPlan(producerDir, approval.planHash)
      ? planUsage(producerDir, ctx.intent?.mode ?? "longform", approval.planHash) : null;
    return approval && uses ? [{ projectId: path.basename(project),
      approvedAt: approval.approvedAt, planHash: approval.planHash, uses }] : [];
  }).sort((left, right) => right.approvedAt.localeCompare(left.approvedAt)
    || left.projectId.localeCompare(right.projectId)).slice(0, WINDOW_PROJECTS);
}

function usageCounts(projects: UsageProject[]): TemplateUsageHistory["counts"] {
  const counts: TemplateUsageHistory["counts"] = {};
  for (const project of projects) {
    for (const [kind, uses] of Object.entries(project.uses)) {
      const prior = counts[kind] ?? { uses: 0, projects: 0, lastUsedAt: project.approvedAt };
      counts[kind] = { uses: prior.uses + uses, projects: prior.projects + 1,
        lastUsedAt: prior.lastUsedAt > project.approvedAt ? prior.lastUsedAt : project.approvedAt };
    }
  }
  return Object.fromEntries(Object.entries(counts).sort(([left], [right]) =>
    left.localeCompare(right)));
}

function buildHistory(ctx: AutoEditCtx, projects: UsageProject[]): TemplateUsageHistory {
  const counts = usageCounts(projects);
  const overusedKinds = Object.entries(counts).filter(([, item]) =>
    item.projects >= MIN_OVERUSED_PROJECTS
      && item.projects / Math.max(1, projects.length) >= MIN_OVERUSED_SHARE)
    .map(([kind]) => kind).sort();
  const core = {
    schemaVersion: 1 as const, kind: "producer-template-usage-history" as const,
    mode: ctx.intent?.mode === "short" ? "short" as const : "longform" as const,
    windowProjects: WINDOW_PROJECTS, projectCount: projects.length, projects, counts,
    overusedKinds,
    policy: { minProjects: MIN_OVERUSED_PROJECTS,
      minProjectShare: MIN_OVERUSED_SHARE },
  };
  return { ...core, digest: digest(core) };
}

export function templateUsageHistoryPath(ctx: AutoEditCtx, captureId?: string): string {
  const runId = (captureId ?? ctx.doctrine?.runId ?? ctx.pipeline?.runId ?? "unbound")
    .replace(/[^a-zA-Z0-9._-]/g, "_").slice(-96);
  return path.join(ctx.dir, ".sniper-learning", "runs", runId, "template-usage.json");
}

/** Persist once per run; resumes reuse the exact historical decision authority. */
export function prepareTemplateUsageHistory(
  ctx: AutoEditCtx,
  root = workspaceRoot(),
  deps: TemplateUsageDependencies = {},
  captureId?: string,
): TemplateUsageHistory {
  const destination = templateUsageHistoryPath(ctx, captureId);
  if (existsSync(destination)) {
    const saved = JSON.parse(readFileSync(destination, "utf8")) as TemplateUsageHistory;
    const { digest: found, ...core } = saved;
    if (found !== digest(core)) throw new Error("template usage history changed after capture");
    return saved;
  }
  const history = buildHistory(ctx, recentProjects(ctx, root, deps));
  mkdirSync(path.dirname(destination), { recursive: true, mode: 0o700 });
  atomicWriteJsonSync(destination, history);
  return history;
}

function authorityFor(destination: string, history: TemplateUsageHistory): TemplateUsageAuthority {
  return { schemaVersion: 1, path: destination, digest: history.digest };
}

/** Capture fresh authority before the writer launches. */
export function captureTemplateUsageAuthority(
  ctx: AutoEditCtx,
  root = workspaceRoot(),
  deps: TemplateUsageDependencies = {},
  captureId?: string,
): BoundTemplateUsage {
  const history = prepareTemplateUsageHistory(ctx, root, deps, captureId);
  return { history, authority: authorityFor(templateUsageHistoryPath(ctx, captureId), history) };
}

/** Restore the exact job-bound snapshot; never trust a newly computed digest. */
export function restoreTemplateUsageAuthority(
  ctx: AutoEditCtx,
  authority: TemplateUsageAuthority,
): BoundTemplateUsage {
  const expectedPath = templateUsageHistoryPath(ctx);
  if (!validTemplateUsageAuthority(authority) || authority.path !== expectedPath) {
    throw new Error("template usage authority envelope is invalid");
  }
  const history = prepareTemplateUsageHistory(ctx);
  if (history.digest !== authority.digest) {
    throw new Error("template usage history no longer matches its run authority");
  }
  return { history, authority };
}
