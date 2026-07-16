import path from "node:path";
import { existsSync } from "node:fs";
import {
  autoEditJobPath,
  checkpointReached,
  fileSha256,
  readAutoEditJob,
} from "@/lib/server/auto-edit-job-store";
import { restoreAutoEditDoctrine } from "@/lib/server/auto-edit-doctrine";
import { restoreAutoEditPipeline } from "@/lib/server/auto-edit-pipeline-authority";
import { autoEditAuthoritySnapshot } from "@/lib/server/auto-edit-authority-snapshot";
import type { PlanningReviewEvidence } from "@/lib/server/auto-edit-quality-artifacts";
import type { AutoEditCtx } from "../auto-edit/stream";
import { collectPlanningReviewEvidence } from "../auto-edit/review-evidence";
import { findManifest, palmierRpc, palmierStatePath, readJsonObject } from "../palmier/_lib";
import { loadViewTarget } from "../palmier/view/target";
import type { PalmierViewTarget } from "../palmier/view/target";
import {
  readLiveBuildState,
  type LiveBuildQcFailure,
  type LiveBuildState,
} from "./state";

export class LiveBuildPreflightError extends Error {
  constructor(message: string, readonly code: string, readonly status = 409) {
    super(message);
  }
}

export interface LiveBuildPreflight {
  dir: string;
  planPath: string;
  planHash: string;
  manifestPath: string;
  doctrineHash: string;
  doctrineFiles: Record<string, string>;
  ctx: AutoEditCtx;
  planningReviews: PlanningReviewEvidence[];
  projectId: string;
  projectPath: string;
  timelineId: string;
  timelineFingerprint: string;
  timeline: Record<string, unknown>;
  priorSessionId?: string;
  qcFailure?: LiveBuildQcFailure;
}

interface PalmierReadback {
  projectId: string;
  projectPath: string;
  timeline: Record<string, unknown>;
}

interface ToolContent {
  content?: { type?: string; text?: string }[];
  isError?: boolean;
}

async function tool(
  name: string,
  args: Record<string, unknown>,
  sessionId: string | null,
  id: number,
): Promise<Record<string, unknown>> {
  const response = await palmierRpc(
    "tools/call", { name, arguments: args }, sessionId, id, 5_000,
  );
  const result = (response.result ?? {}) as ToolContent;
  const text = (result.content ?? []).filter((row) => row.type === "text")
    .map((row) => row.text ?? "").join("");
  if (result.isError) throw new Error(`${name}: ${text || "tool error"}`);
  const value: unknown = JSON.parse(text || "{}");
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${name}: Palmier returned a non-object result`);
  }
  return value as Record<string, unknown>;
}

async function activePalmierReadback(): Promise<PalmierReadback> {
  const init = await palmierRpc("initialize", {
    protocolVersion: "2025-06-18", capabilities: {},
    clientInfo: { name: "sniper-live-build-preflight", version: "1.0" },
  }, null, 1, 5_000);
  await palmierRpc("notifications/initialized", {}, init.sessionId, null, 5_000);
  const projects = await tool("get_projects", {}, init.sessionId, 2);
  const rows = Array.isArray(projects.projects)
    ? projects.projects as Record<string, unknown>[] : [];
  const active = rows.find((row) => row.isActive === true);
  const fallback = projects.active && typeof projects.active === "object"
    ? projects.active as Record<string, unknown> : null;
  const projectId = typeof active?.id === "string" ? active.id
    : typeof fallback?.id === "string" ? fallback.id : "";
  const projectPath = typeof active?.path === "string" ? active.path
    : typeof fallback?.path === "string" ? fallback.path : "";
  if (!projectId || !projectPath) throw new Error("Palmier has no active project identity");
  return { projectId, projectPath, timeline: await tool("get_timeline", {
    captionDetail: true,
  }, init.sessionId, 3) };
}

function approvedPlan(dir: string): {
  planPath: string;
  planHash: string;
  manifestPath: string;
  doctrineHash: string;
  doctrineFiles: Record<string, string>;
  ctx: AutoEditCtx;
  planningReviews: PlanningReviewEvidence[];
  priorSessionId?: string;
} {
  const planPath = path.join(dir, "edit_plan.json");
  const planHash = fileSha256(planPath);
  const manifestPath = findManifest(dir);
  const job = readAutoEditJob(autoEditJobPath(dir));
  if (!planHash || !manifestPath || !existsSync(manifestPath)) {
    throw new LiveBuildPreflightError(
      "Prepare media and an edit plan before starting a Palmier live build.",
      "LIVE_BUILD_INPUT_MISSING",
    );
  }
  if (!job || !checkpointReached(job.checkpoint, "plan_reviewed")
      || job.reviewedPlanHash !== planHash || !job.ctx.doctrine || !job.ctx.pipeline) {
    throw new LiveBuildPreflightError(
      "The current edit_plan.json has not passed the deterministic gates and required independent planning reviews.",
      "LIVE_BUILD_PLAN_NOT_APPROVED",
    );
  }
  const doctrine = restoreAutoEditDoctrine(job.ctx.doctrine);
  restoreAutoEditPipeline(job.ctx.pipeline);
  const authority = autoEditAuthoritySnapshot(job.ctx);
  if (authority.planHash !== planHash
      || job.reviewedAuthorityDigest !== authority.digest
      || job.planningCleanPlanHash !== planHash
      || job.planningCleanAuthorityDigest !== authority.digest
      || (job.planningCleanRounds ?? 0) < (job.planningRoundsRequired ?? 1)) {
    throw new LiveBuildPreflightError(
      "The saved planning approval no longer matches the current plan, inputs, doctrine, and pipeline.",
      "LIVE_BUILD_PLAN_AUTHORITY_STALE",
    );
  }
  const planningReviews = collectPlanningReviewEvidence(job, authority);
  return {
    planPath, planHash, manifestPath,
    doctrineHash: doctrine.doctrineHash, doctrineFiles: doctrine.files,
    ctx: job.ctx, planningReviews,
    ...(job.ctx.brainSessionEstablished && job.ctx.brainSessionId
      ? { priorSessionId: job.ctx.brainSessionId } : {}),
  };
}

export function liveBuildParentTimeline(
  target: Pick<PalmierViewTarget, "kind" | "timelineId">,
  retained: LiveBuildState | null,
  resume: boolean,
): string {
  if (resume) {
    if (!retained || target.kind !== "pending-candidate"
        || target.timelineId !== retained.candidateTimelineId) {
      throw new LiveBuildPreflightError(
        "The retained live-build candidate is not the current governed Palmier target.",
        "LIVE_BUILD_TARGET_UNSAFE",
      );
    }
    return retained.parentTimelineId;
  }
  if (!["working-draft", "working-head"].includes(target.kind)) {
    throw new LiveBuildPreflightError(
      "Resolve the current Palmier candidate or stale workspace before starting a live build.",
      "LIVE_BUILD_TARGET_UNSAFE",
    );
  }
  return target.timelineId;
}

function linkedTarget(
  dir: string,
  resume: boolean,
): { projectId: string; projectPath: string; timelineId: string } {
  const state = readJsonObject(palmierStatePath(dir));
  const target = loadViewTarget(dir);
  if ("error" in target) {
    throw new LiveBuildPreflightError(target.error, "LIVE_BUILD_WORKSPACE_MISSING");
  }
  if (state?.workspaceMode !== "managed-draft" || target.ownership !== "sniper") {
    throw new LiveBuildPreflightError(
      "Live build requires the Sniper-owned managed source workspace; Palmier-owned/manual heads need the candidate/adoption flow first.",
      "LIVE_BUILD_OWNERSHIP_UNSUPPORTED",
    );
  }
  const draft = state.draft && typeof state.draft === "object" && !Array.isArray(state.draft)
    ? state.draft as Record<string, unknown> : null;
  if (draft?.assetKind !== "source") {
    throw new LiveBuildPreflightError(
      "Live build requires an editable source bootstrap, not a saved-cut or flat mirror workspace.",
      "LIVE_BUILD_SOURCE_REQUIRED",
    );
  }
  const projectId = typeof state.projectId === "string" ? state.projectId : "";
  if (!projectId) {
    throw new LiveBuildPreflightError(
      "The managed Palmier project identity is missing.",
      "LIVE_BUILD_TARGET_UNSAFE",
    );
  }
  const retained = resume ? readLiveBuildState(dir) : null;
  const timelineId = liveBuildParentTimeline(target, retained, resume);
  return { projectId, projectPath: target.projectPath, timelineId };
}

/** Prove plan governance and exact active Palmier identity before model spawn. */
export async function preflightLiveBuild(
  dir: string,
  resume = false,
): Promise<LiveBuildPreflight> {
  const plan = approvedPlan(dir);
  const target = linkedTarget(dir, resume);
  let active: PalmierReadback;
  try { active = await activePalmierReadback(); } catch (error) {
    throw new LiveBuildPreflightError(
      `Palmier readback failed: ${(error as Error).message}`,
      "LIVE_BUILD_PALMIER_UNAVAILABLE", 502,
    );
  }
  if (active.projectId !== target.projectId
      || path.resolve(active.projectPath) !== path.resolve(target.projectPath)) {
    throw new LiveBuildPreflightError(
      "Palmier is showing a different project. Open the linked project or explicitly adopt the visible project before building.",
      "PALMIER_ACTIVE_PROJECT_MISMATCH",
    );
  }
  const retained = resume ? readLiveBuildState(dir) : null;
  const expectedTimelineId = retained?.candidateTimelineId ?? target.timelineId;
  if (active.timeline.id !== expectedTimelineId) {
    throw new LiveBuildPreflightError(
      resume
        ? "Palmier is showing a different timeline. Open the retained live-build candidate before resuming."
        : "Palmier is showing a different timeline. Open the linked working timeline before building.",
      "PALMIER_ACTIVE_TIMELINE_MISMATCH",
    );
  }
  const authority = readJsonObject(path.join(dir, "palmier.timeline-authority.json"));
  if (authority?.projectId !== target.projectId
      || authority.timelineId !== target.timelineId
      || typeof authority.fingerprint !== "string") {
    throw new LiveBuildPreflightError(
      "The saved Palmier working authority does not match the linked visible timeline.",
      "LIVE_BUILD_PARENT_AUTHORITY_STALE",
    );
  }
  return {
    dir, ...plan, ...target, timeline: active.timeline,
    timelineFingerprint: authority.fingerprint,
    ...(retained?.qcFailure ? { qcFailure: retained.qcFailure } : {}),
  };
}
