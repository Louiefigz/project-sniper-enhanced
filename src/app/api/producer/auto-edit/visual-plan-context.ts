import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { pythonInterpreter, runtimeScriptsDir } from "../../_lib/spawn-python";
import { gateBundleOperatorIntent } from "./planning-gates";
import { authoringWorkDir, ordinaryVisualPlanRequired, type AutoEditCtx } from "./stream";
import { executablePipelineRoot } from
  "@/lib/server/auto-edit-pipeline-authority";
import { atomicWriteJsonSync } from "@/lib/server/atomic-file";
import {
  autoEditTranscriptDigest,
  stableAuthorityHash,
} from "@/lib/server/auto-edit-authority-snapshot";
import {
  prepareVisualTranscriptAuthority,
  type VisualPlanAuthorityPin,
} from "./visual-plan-word-authority";
import { prepareVisualRelatedUsageAuthority, type RelatedUse } from
  "./visual-plan-related-usage";
import { prepareVisualMediaAuthority } from "./visual-plan-media-authority";

const MAX_PLAN_BYTES = 4 * 1024 * 1024;
const SHA256 = /^[a-f0-9]{64}$/;

export interface VisualPlanProjectAuthority {
  mode: "short" | "long";
  aspect: "9:16" | "16:9";
  durationFrames: number;
  fps: { numerator: 30; denominator: 1 };
  intentSha256: string;
  acceptedProgramSha256: string;
  transcriptSha256: string;
}

export interface VisualPlanContext {
  schemaVersion: 1;
  kind: "route-neutral-visual-plan-context";
  requiredVersion: 1;
  project: VisualPlanProjectAuthority;
  catalogPin: Record<string, unknown>;
  transcriptAuthority: VisualPlanAuthorityPin;
  mediaAuthority: VisualPlanAuthorityPin;
  relatedUsageAuthority: VisualPlanAuthorityPin;
  relatedUsage: RelatedUse[];
}

export function visualPlanContextPath(
  ctx: Pick<AutoEditCtx, "dir" | "authoringDir">,
): string {
  return path.join(authoringWorkDir(ctx), "VISUAL-PLAN-CONTEXT.json");
}

export function visualPlanCatalogAuthorityPath(
  ctx: Pick<AutoEditCtx, "dir" | "authoringDir">,
): string {
  return path.join(authoringWorkDir(ctx), "CATALOG-AUTHORITY.json");
}

export function visualPlanTranscriptAuthorityPath(
  ctx: Pick<AutoEditCtx, "dir" | "authoringDir">,
): string {
  return path.join(authoringWorkDir(ctx), "TRANSCRIPT-AUTHORITY.json");
}

export function visualPlanMediaAuthorityPath(
  ctx: Pick<AutoEditCtx, "dir" | "authoringDir">,
): string {
  return path.join(authoringWorkDir(ctx), "MEDIA-AUTHORITY.json");
}

export function visualPlanRelatedUsageAuthorityPath(
  ctx: Pick<AutoEditCtx, "dir" | "authoringDir">,
): string {
  return path.join(authoringWorkDir(ctx), "RELATED-USAGE-AUTHORITY.json");
}

function planObject(ctx: AutoEditCtx): Record<string, unknown> {
  const bytes = readFileSync(ctx.planPath);
  if (bytes.length < 2 || bytes.length > MAX_PLAN_BYTES) {
    throw new Error("accepted edit plan exceeds the bounded visual-plan context read");
  }
  const value: unknown = JSON.parse(bytes.toString("utf8"));
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("accepted edit plan must be an object");
  }
  return value as Record<string, unknown>;
}

function durationFrames(plan: Record<string, unknown>): number {
  const cuts = Array.isArray(plan.cutTrack) ? plan.cutTrack : [];
  const seconds = cuts.reduce((total, value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return total;
    const row = value as Record<string, unknown>;
    const start = Number(row.start), end = Number(row.end), speed = Number(row.speed ?? 1);
    return Number.isFinite(start) && Number.isFinite(end) && speed > 0 && end > start
      ? total + (end - start) / speed : total;
  }, 0);
  return Math.max(1, Math.round(seconds * 30));
}

/** Recompute the exact upstream authority the visual plan must copy. */
export function currentVisualPlanProjectAuthority(ctx: AutoEditCtx): VisualPlanProjectAuthority {
  const plan = planObject(ctx);
  const mode = ctx.intent?.mode;
  if (mode !== "short" && mode !== "longform") {
    throw new Error("visual-plan context requires stored short or longform intent");
  }
  const intent = gateBundleOperatorIntent(ctx.scope, ctx.intent);
  return {
    mode: mode === "short" ? "short" : "long",
    aspect: mode === "short" ? "9:16" : "16:9",
    durationFrames: durationFrames(plan),
    fps: { numerator: 30, denominator: 1 },
    intentSha256: stableAuthorityHash(intent),
    acceptedProgramSha256: stableAuthorityHash({
      cutTrack: plan.cutTrack ?? [],
      cutDecisions: plan.cutDecisions ?? null,
    }),
    transcriptSha256: autoEditTranscriptDigest(ctx),
  };
}

function catalogPin(ctx: AutoEditCtx): Record<string, unknown> {
  const authorityCtx = ctx.visualPlanPipeline
    ? { ...ctx, pipeline: ctx.visualPlanPipeline }
    : ctx;
  const executableRoot = authorityCtx.pipeline
    ? executablePipelineRoot(ctx.dir, authorityCtx.pipeline) : null;
  const cli = path.join(runtimeScriptsDir(), "producer/planner/visual_plan_cli.py");
  const raw = execFileSync(pythonInterpreter(), [
    "-B", cli, "catalog-authority", visualPlanCatalogAuthorityPath(ctx),
  ], { encoding: "utf8", timeout: 30_000, maxBuffer: 1024 * 1024,
    env: { NODE_ENV: "production", PYTHONDONTWRITEBYTECODE: "1", PYTHONUTF8: "1",
      ...(executableRoot
        ? { SNIPER_PIPELINE_ROOT: executableRoot }
        : {}) } });
  const value: unknown = JSON.parse(raw);
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("catalog-authority returned an invalid catalogPin");
  }
  const row = value as Record<string, unknown>;
  for (const key of ["indexSha256", "resourceIndexSha256", "sourceSetSha256"]) {
    if (typeof row[key] !== "string" || !SHA256.test(row[key])) {
      throw new Error(`catalog-authority returned invalid ${key}`);
    }
  }
  return row;
}

/** Materialize context after a caller has established that this edit requires it. */
export function materializeVisualPlanContextAuthority(ctx: AutoEditCtx): VisualPlanContext {
  const project = currentVisualPlanProjectAuthority(ctx);
  const transcriptAuthority = prepareVisualTranscriptAuthority(
    ctx, project, visualPlanTranscriptAuthorityPath(ctx),
  );
  const mediaAuthority = prepareVisualMediaAuthority(
    ctx, project, visualPlanMediaAuthorityPath(ctx),
  );
  const usage = prepareVisualRelatedUsageAuthority(
    ctx, project, visualPlanRelatedUsageAuthorityPath(ctx),
  );
  const value: VisualPlanContext = {
    schemaVersion: 1,
    kind: "route-neutral-visual-plan-context",
    requiredVersion: 1,
    project,
    catalogPin: catalogPin(ctx),
    transcriptAuthority,
    mediaAuthority,
    relatedUsageAuthority: usage.pin,
    relatedUsage: usage.relatedUsage,
  };
  atomicWriteJsonSync(visualPlanContextPath(ctx), value);
  return value;
}

/** Materialize controller-owned context before renderer selection. */
export function prepareVisualPlanContext(ctx: AutoEditCtx): VisualPlanContext | null {
  if (!ordinaryVisualPlanRequired(ctx)) return null;
  return materializeVisualPlanContextAuthority(ctx);
}

/** Recompute and compare context before every gate or delivery buyer. */
export function currentVisualPlanContext(ctx: AutoEditCtx): VisualPlanContext {
  const prepared = prepareVisualPlanContext(ctx);
  if (!prepared) throw new Error("route-neutral visual-plan context is not active");
  return prepared;
}
