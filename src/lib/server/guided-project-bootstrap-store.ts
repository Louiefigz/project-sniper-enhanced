/** New-only intake and diagnostic records. No adoption, rollback, or retry of partial projects. */
import path from "node:path";
import { mkdirSync, realpathSync, lstatSync } from "node:fs";
import { workspaceRoot } from "@/app/api/_lib/workspace";
import { readCutPreviewObject, observeCutPreviewFile, assertCutPreviewDirectory } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { exactKeys, uuid, isoDate, stringValue } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { atomicCreateJsonSync } from "./atomic-file";
import { parseGuidedProjectRequest, assertExistingCutContext, type GuidedProjectRequest } from "./guided-project-bootstrap-contract";
import type { AutoEditJob } from "./auto-edit-job-types";

export const BOOTSTRAP_INTAKE = ".sniper-guided-project-bootstrap.json";
export const BOOTSTRAP_FAILURE = ".sniper-guided-project-failure.json";
export const BOOTSTRAP_UNKNOWN = ".sniper-guided-project-cleanup-unknown.json";

export function bootstrapSeedPath(dir: string): string {
  return path.join(dir, ".sniper-guided-project-initial-plan.json");
}

export function bootstrapProjectPath(id: string): string {
  uuid(id, "idempotencyKey");
  const workspace = realpathSync(workspaceRoot({ initialize: false }));
  assertCutPreviewDirectory(workspace);
  return path.join(workspace, `guided-${id}`);
}

/** Atomic mkdir is the singleton fence; EEXIST never means permission to launch. */
export function createBootstrapProject(request: GuidedProjectRequest, token: string, receivedAt = new Date().toISOString()) {
  parseGuidedProjectRequest(request);
  isoDate(receivedAt, "bootstrap receivedAt");
  if (Date.parse(receivedAt) > Date.now()) throw new Error("Bootstrap receivedAt cannot be future");
  const root = bootstrapProjectPath(request.idempotencyKey), dir = path.join(root, "producer");
  mkdirSync(root, { mode: 0o700 });
  const record = { schemaVersion: 1, kind: "guided-project-bootstrap-intake", producerDir: dir,
    request, requestHash: canonicalJsonSha256(request), token, receivedAt };
  atomicCreateJsonSync(path.join(root, BOOTSTRAP_INTAKE), record);
  mkdirSync(dir, { mode: 0o700 });
  return { root, dir, record };
}

export function readBootstrapIntake(dir: string) {
  const root = path.dirname(dir);
  assertCutPreviewDirectory(root);
  const held = readCutPreviewObject(path.join(root, BOOTSTRAP_INTAKE)), row = held.value;
  const keys = ["schemaVersion", "kind", "producerDir", "request", "requestHash", "token", "receivedAt"];
  exactKeys(row, keys, keys, "bootstrap intake");
  const request = parseGuidedProjectRequest(row.request);
  stringValue(row.token, "bootstrap token", 200); isoDate(row.receivedAt, "bootstrap receivedAt");
  if (row.schemaVersion !== 1 || row.kind !== "guided-project-bootstrap-intake"
      || row.producerDir !== dir || root !== bootstrapProjectPath(request.idempotencyKey)
      || row.requestHash !== canonicalJsonSha256(request)) throw new Error("Bootstrap intake identity changed");
  return { ...held, request, token: row.token as string, requestHash: row.requestHash as string };
}

export function assertBootstrapJob(job: AutoEditJob): ReturnType<typeof readBootstrapIntake> {
  assertExistingCutContext(job.ctx);
  const policy = job.ctx.existingCutCandidate ?? job.ctx.authoredCut;
  if (!policy || job.reviewSavedPlan || job.attempts !== 1) throw new Error("Guided bootstrap is not new-only");
  const held = readBootstrapIntake(job.ctx.dir), request = held.request;
  const matching = request.operation === "bootstrap-existing-cut"
    ? job.ctx.existingCutCandidate?.inputPlanSha256 === request.candidate.sha256
    : job.ctx.authoredCut?.preparationStartedAt === held.value.receivedAt;
  if (!matching || policy.requestHash !== held.requestHash
      || (job.artifactToken ?? job.token) !== held.token || job.ctx.manifestPath !== request.manifest.path
      || job.ctx.transcriptsDir !== path.dirname(request.manifest.path)
      || job.ctx.planPath !== path.join(job.ctx.dir, "edit_plan.json")) throw new Error("Bootstrap job no longer binds its exact intake");
  return held;
}

/** Cheap current metadata bytes, not repeated multi-GB source verification. */
export function assertBootstrapBytes(job: AutoEditJob): void {
  const held = assertBootstrapJob(job);
  const refs = held.request.operation === "author-cut"
    ? [held.request.manifest, { path: bootstrapSeedPath(job.ctx.dir), sha256: job.ctx.authoredCut!.initialPlanSha256 }]
    : [held.request.candidate, held.request.manifest,
      { path: job.ctx.planPath, sha256: job.ctx.existingCutCandidate!.savedPlanSha256 }];
  for (const ref of refs) {
    if (observeCutPreviewFile(ref.path, 16 * 1024 * 1024).sha256 !== ref.sha256) {
      throw new Error("Bootstrap original candidate, saved candidate, seed or manifest changed");
    }
  }
}

export function retainBootstrapFailure(dir: string, error: unknown, cleanup: { verified: boolean; forcedStop: boolean }): void {
  const details = { schemaVersion: 1, kind: "guided-project-bootstrap-failure", producerDir: dir,
    recordedAt: new Date().toISOString(), message: String(error).slice(0, 1200),
    cleanupVerified: cleanup.verified, forcedStop: cleanup.forcedStop,
    retryable: false, cutAccepted: false, approvalGranted: false };
  // Unknown is monotonic and separately retained; a first clean failure cannot suppress later uncertainty.
  if (!cleanup.verified) retainFailureFact(path.join(path.dirname(dir), BOOTSTRAP_UNKNOWN), details);
  retainFailureFact(path.join(path.dirname(dir), BOOTSTRAP_FAILURE), details);
}

function retainFailureFact(file: string, details: Record<string, unknown>): void {
  try { atomicCreateJsonSync(file, details); }
  catch (cause) { if ((cause as NodeJS.ErrnoException).code !== "EEXIST") throw cause; }
}

export function bootstrapCleanupUnknown(dir: string): boolean {
  try { lstatSync(path.join(path.dirname(dir), BOOTSTRAP_UNKNOWN)); return true; }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return false; throw error; }
}

/** Any marker, including malformed or linked evidence, blocks rather than selecting a last-good fact. */
export function assertNoBootstrapFailure(dir: string): void {
  if (bootstrapCleanupUnknown(dir)) throw new Error("Bootstrap cleanup remains unknown; no acceptance or relaunch is authorized");
  try { lstatSync(path.join(path.dirname(dir), BOOTSTRAP_FAILURE)); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return; throw error; }
  throw new Error("Bootstrap failure or uncertain cleanup is retained; no acceptance or relaunch is authorized");
}
