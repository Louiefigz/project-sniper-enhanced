import fs from "node:fs";
import path from "node:path";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import { acquireProjectMutationLease } from "@/lib/server/project-mutation-lease";
import { durableProcessAlive } from "@/lib/server/process-liveness";
import type { ColorJob, ColorStart } from "@/lib/producer/color-diagnostic";
import { guardProjectMutation, mutationProjectRoot } from "../../_lib/project-mutation";
import { workspaceRoot } from "../../_lib/workspace";
import { cutPreviewLeaseGuard } from "../auto-edit/cut-preview-lease";
import { ColorError, validateContexts } from "./request";
import { createRecord, descriptor, jobDir, newRequest, privateDir, readJson, readRequest, type JobTerminal } from "./files";
import { baseStatus, completedStatus } from "./projection";
import { runDiagnosticProcess, type ProcessResult } from "./process";

const OPERATION = "private color diagnostic (no grade or draft writes)";
function parentsCurrent(input: ColorStart): boolean {
  const observed = descriptor(input.dir);
  return observed.planHash === input.expectedPlanHash && observed.manifestHash === input.expectedManifestHash;
}
/** GET has no process launch, cleanup, reconciliation, or metadata writes. */
export function jobStatus(dir: string, id: string): ColorJob {
  const request = readRequest(dir, id), current = parentsCurrent(request.request);
  const file = path.join(jobDir(dir, id), "terminal.json");
  if (fs.existsSync(file)) return completedStatus(request, readJson(file) as unknown as JobTerminal, current);
  const base = baseStatus(request, current);
  const live = durableProcessAlive(request.owner.pid, request.owner, request.startedAt,
    { maxHeartbeatAgeMs: Number.MAX_SAFE_INTEGER });
  return live && base.elapsedMs <= 300_000 ? base : { ...base, state: "interrupted", error: "The diagnostic owner stopped or exceeded its lifecycle bound. Cleanup is unverified; retained private ownership requires operator recovery." };
}
function existing(input: ColorStart): ColorJob | null {
  const candidate = path.join(input.dir, ".sniper-color-jobs", input.jobId);
  if (!fs.existsSync(candidate)) return null;
  const request = readRequest(input.dir, input.jobId);
  if (canonicalJsonSha256(request.request) !== canonicalJsonSha256(input)) throw new ColorError("This token belongs to a different immutable request", 409);
  if (!parentsCurrent(input)) throw new ColorError("Saved parents changed; refresh sources and use a new diagnostic token", 409, "COLOR_PARENTS_CHANGED");
  return jobStatus(input.dir, input.jobId);
}
export interface ColorDependencies { run: (file: string) => Promise<ProcessResult> }
/** Reserve both shared project authority and one workspace-wide color resource. */
export async function startDiagnostic(input: ColorStart, dependencies: ColorDependencies = { run: runDiagnosticProcess }, timing = { wall: Date.now(), mono: performance.now() }): Promise<ColorJob | Response> {
  const replay = existing(input);
  if (replay) return replay;
  const project = guardProjectMutation({ projectRoot: mutationProjectRoot(input.dir), producerDir: input.dir, operation: OPERATION });
  if (project.response) return project.response;
  let releaseResource: (() => void) | undefined;
  let safeRelease = true;
  try {
    const assertLease = cutPreviewLeaseGuard(input.dir, project.lease);
    const resource = privateDir(path.join(fs.realpathSync(workspaceRoot()), ".sniper-color-resource"), true);
    const held = acquireProjectMutationLease(resource, OPERATION);
    if (!held.lease) throw new ColorError("The private color worker is busy", 409, "COLOR_RESOURCE_BUSY");
    releaseResource = held.lease.release;
    if (fs.existsSync(path.join(resource, "active.json"))) throw new ColorError("A prior color job has unverified cleanup. Do not restart it; operator recovery is required.", 409, "COLOR_RECOVERY_REQUIRED");
    const observed = descriptor(input.dir);
    if (!parentsCurrent(input)) throw new ColorError("Saved plan or sources changed; refresh first", 409, "COLOR_PARENTS_CHANGED");
    if (observed.blockers.length) throw new ColorError(observed.blockers.join(" "), 409, "COLOR_ADMISSION_REQUIRED");
    validateContexts(input.contexts, observed.sources);
    const request = newRequest(input, observed, timing.wall), directory = jobDir(input.dir, input.jobId, true);
    createRecord(path.join(directory, "request.json"), request);
    createRecord(path.join(resource, "active.json"), { jobId: input.jobId, dir: input.dir, requestDigest: request.digest, owner: request.owner });
    safeRelease = false;
    assertLease();
    let result: ProcessResult;
    try { result = await dependencies.run(path.join(directory, "request.json")); assertLease(); }
    catch { result = { diagnosticId: null, cleanupVerified: false, interrupted: true }; }
    const terminal = { ...result, requestDigest: request.digest, elapsedMs: Math.max(0, Math.round(performance.now() - timing.mono)) };
    createRecord(path.join(directory, "terminal.json"), terminal);
    const status = jobStatus(input.dir, input.jobId);
    if (result.cleanupVerified) { releaseClaim(resource, request.digest); safeRelease = true; }
    return status;
  } finally {
    if (safeRelease) { releaseResource?.(); project.lease.release(); }
  }
}
function releaseClaim(resource: string, digest: string): void {
  const file = path.join(resource, "active.json"), active = readJson(file);
  if (active.requestDigest !== digest) throw new ColorError("Color resource ownership changed; recovery is required", 409);
  fs.unlinkSync(file);
}
