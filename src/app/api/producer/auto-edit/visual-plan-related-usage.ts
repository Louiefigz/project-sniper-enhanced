import { existsSync, lstatSync, readdirSync, realpathSync } from "node:fs";
import path from "node:path";
import { atomicWriteJsonSync } from "@/lib/server/atomic-file";
import { stableAuthorityHash } from "@/lib/server/auto-edit-authority-snapshot";
import { fileSha256 } from "@/lib/server/auto-edit-hash";
import { readApproval, type ApprovalRecord } from "@/lib/server/auto-edit-quality-artifacts";
import { nativeVisualUsageProjectsAcross } from
  "@/lib/server/native-visual-usage-memory";
import { selectedVisualUses, type RelatedUse, type VisualUsageProject } from
  "@/lib/server/visual-plan-related-use";
import { readBoundedAuthoringFile } from "./initial-authoring-capture";
import type { AutoEditCtx } from "./stream";
import type { VisualPlanProjectAuthority } from "./visual-plan-context";
import type { VisualPlanAuthorityPin } from "./visual-plan-word-authority";

const MAX_PROJECTS = 4096;
const WINDOW_PROJECTS = 8;
const MAX_PACKET_BYTES = 16 * 1024 * 1024;
const MAX_RELATED_USES = 128;
const MAX_LEGACY_PROJECT_READS = 64;

export type { RelatedUse } from "@/lib/server/visual-plan-related-use";

function object(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

function boundedJson(file: string): Record<string, unknown> | null {
  try {
    const bytes = readBoundedAuthoringFile(file, "approved planning packet", MAX_PACKET_BYTES);
    return object(JSON.parse(bytes.toString("utf8")));
  } catch {
    return null;
  }
}

function planningPacket(approval: ApprovalRecord): {
  packet: Record<string, unknown>; sha256: string;
} | null {
  const review = [...approval.planningReviews]
    .sort((left, right) => right.round - left.round)[0];
  if (!review) return null;
  const packet = boundedJson(review.packet.path);
  return packet ? { packet, sha256: review.packet.hash } : null;
}

function validatedProject(projectDir: string, mode: "short" | "long"): VisualUsageProject | null {
  const producerDir = path.join(projectDir, "producer");
  const approval = readApproval(producerDir);
  if (!approval) return null;
  const observed = planningPacket(approval);
  const visual = object(observed?.packet.visualPlan);
  const content = object(visual?.content);
  const planSha256 = visual?.visualPlanSha256;
  const editPlan = object(object(observed?.packet.plan)?.content);
  const application = object(editPlan?.visualPlanApplication);
  if (!observed || !content || typeof planSha256 !== "string"
      || stableAuthorityHash(content) !== planSha256
      || object(content.project)?.mode !== mode
      || application?.visualPlan === undefined
      || object(application.visualPlan)?.visualPlanSha256 !== planSha256) return null;
  const uses = selectedVisualUses(content, planSha256);
  if (!uses) return null;
  return { projectId: path.basename(projectDir), approvedAt: approval.approvedAt,
    planSha256, applicationSha256: stableAuthorityHash(application),
    packetSha256: observed.sha256, uses };
}

function currentProject(ctx: AutoEditCtx): string | null {
  const current = realpathSync(path.dirname(ctx.dir));
  const projectRecord = path.join(current, "project.json");
  if (!existsSync(projectRecord) || lstatSync(projectRecord).isSymbolicLink()
      || !lstatSync(projectRecord).isFile()) return null;
  return current;
}

function candidateProjects(ctx: AutoEditCtx): string[] {
  const current = currentProject(ctx);
  if (!current) return [];
  const root = realpathSync(path.dirname(current));
  const rows = readdirSync(root, { withFileTypes: true });
  if (rows.length > MAX_PROJECTS) throw new Error("related visual usage project scan exceeds its bound");
  const projects = rows.flatMap((entry) => {
    if (!entry.isDirectory() || entry.isSymbolicLink()) return [];
    const project = path.join(root, entry.name);
    try {
      return realpathSync(project) === current ? [] : [realpathSync(project)];
    } catch { return []; }
  });
  return projects.sort((left, right) => legacyOrder(right).localeCompare(legacyOrder(left))
    || left.localeCompare(right));
}

function legacyOrder(project: string): string {
  const file = path.join(project, "producer", ".sniper-qc-approved.json");
  try {
    const metadata = lstatSync(file);
    if (metadata.isSymbolicLink() || !metadata.isFile()) return "0000000000000";
    return String(Math.trunc(metadata.mtimeMs)).padStart(13, "0");
  } catch { return "0000000000000"; }
}

function priorProjects(
  ctx: AutoEditCtx,
  mode: "short" | "long",
): { projects: VisualUsageProject[]; includesNative: boolean } {
  const current = currentProject(ctx);
  const candidates = candidateProjects(ctx);
  const native = nativeVisualUsageProjectsAcross(
    [...(current ? [current] : []), ...candidates], mode,
  );
  const rows = [...native, ...candidates.slice(0, MAX_LEGACY_PROJECT_READS).flatMap((project) => {
    try {
      const value = validatedProject(project, mode);
      return value ? [value] : [];
    } catch { return []; }
  })].sort((left, right) => right.approvedAt.localeCompare(left.approvedAt)
    || left.projectId.localeCompare(right.projectId));
  const unique = new Map<string, VisualUsageProject>();
  for (const row of rows) {
    const identity = `${row.planSha256}:${row.applicationSha256}`;
    if (!unique.has(identity)) unique.set(identity, row);
  }
  return { projects: [...unique.values()].slice(0, WINDOW_PROJECTS),
    includesNative: native.length > 0 };
}

/** Freeze validated prior visual allocations, or an explicit empty ledger. */
export function prepareVisualRelatedUsageAuthority(
  ctx: AutoEditCtx,
  project: VisualPlanProjectAuthority,
  destination: string,
): { pin: VisualPlanAuthorityPin; relatedUsage: RelatedUse[] } {
  const prior = priorProjects(ctx, project.mode), projects = prior.projects;
  const relatedUsage = projects.flatMap((item) => item.uses).slice(0, MAX_RELATED_USES);
  const core = { schemaVersion: 1 as const, kind: "visual-plan-related-usage-authority" as const,
    mode: project.mode, windowProjects: WINDOW_PROJECTS,
    source: projects.length ? (prior.includesNative ? "validated-current-projects" as const
      : "validated-approved-projects" as const)
      : "explicit-empty-controller-ledger" as const,
    projectCount: projects.length, projects, relatedUsage };
  const value = { ...core, digest: stableAuthorityHash(core) };
  atomicWriteJsonSync(destination, value);
  const sha256 = fileSha256(destination);
  if (!sha256 || !existsSync(destination) || lstatSync(destination).isSymbolicLink()) {
    throw new Error("related visual usage authority was not materialized");
  }
  return { pin: { schemaVersion: 1, path: realpathSync(destination), sha256,
    digest: value.digest }, relatedUsage };
}
