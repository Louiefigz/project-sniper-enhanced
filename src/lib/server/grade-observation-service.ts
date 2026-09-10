import fs from "node:fs";
import path from "node:path";
import { guardProjectMutation, mutationProjectRoot } from "@/app/api/_lib/project-mutation";
import { pipelineRepositoryRoot } from "@/app/api/_lib/spawn-python";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { readBytes, sha } from "@/app/api/producer/studio/import/files";
import { acquireGradeObservationResource } from "./grade-observation-resource";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { runGradeProcess, type GradeInvocation, type GradeProcessResult } from "./grade-observation-process";
import { checkTime, createJob, object, parents, POLICY, readRecord, sourceInventory,
  validateRequest, writeRecord, type GradeObservationRequest } from "./grade-observation-store";

export interface PrivateGradeObservation {
  jobId: string; status: "complete" | "failed" | "interrupted"; cleanupVerified: boolean;
  elapsedMs: number; cleanupMs: number; decodedFrames: number | null; sourceId: string;
  error: string | null; gradeApplicable: false; deliveryApproved: false;
}
export interface GradeDependencies { run: (input: GradeInvocation) => Promise<GradeProcessResult> }
interface ObservationScope {
  resource: string; assertProject: () => void; assertResource: () => void; allowRelease: () => void;
}
interface ObservationContext { request: GradeObservationRequest; root: string; deadline: bigint; started: bigint }
const OPERATION = "private full-source color observation (no grade or draft writes)";

function verifiedResult(job: ReturnType<typeof createJob>, held: GradeProcessResult): Record<string, unknown> {
  if (!held.resultSha256) throw new Error("Observation child completion is unverified");
  const file = path.join(job.directory, "observation.json");
  if (sha(readBytes(file, 8 * 1024 * 1024)) !== held.resultSha256) throw new Error("Observation changed after live child return");
  const value = readRecord(file), { artifactHash, ...body } = value;
  if (artifactHash !== canonicalJsonSha256(body) || value.schemaVersion !== 1 || value.policy !== POLICY
      || value.jobId !== job.input.jobId || value.inputSha256 !== job.inputHash
      || value.cleanupVerified !== held.cleanupVerified || value.status !== held.status
      || value.gradeApplicable !== false || value.deliveryApproved !== false) throw new Error("Observation parent/result bindings are invalid");
  if (sha(readBytes(path.join(job.directory, "input.json"), 128 * 1024)) !== job.inputHash) throw new Error("Observation immutable input changed");
  return value;
}
function releaseClaim(resource: string, inputHash: string): void {
  const file = path.join(resource, "active.json");
  if (readRecord(file).requestDigest !== inputHash) throw new Error("Observation resource claim changed; recovery is required");
  fs.unlinkSync(file);
}
/** Internal opt-in adapter only. No route, automatic execution, sampled-result upgrade or UI release. */
export async function observeProjectSource(raw: GradeObservationRequest,
  dependencies: GradeDependencies = { run: runGradeProcess }): Promise<PrivateGradeObservation | Response> {
  const started = process.hrtime.bigint(), deadline = started + BigInt(120_000_000_000);
  const request = validateRequest(raw), root = fs.realpathSync(pipelineRepositoryRoot());
  const project = guardProjectMutation({ projectRoot: mutationProjectRoot(request.dir), producerDir: request.dir, operation: OPERATION });
  if (project.response) return project.response;
  let releaseResource: (() => void) | undefined, safeRelease = true;
  try {
    const assertProject = cutPreviewLeaseGuard(request.dir, project.lease);
    const { resource, lease, assertResource } = acquireGradeObservationResource(OPERATION);
    releaseResource = lease.release;
    const scope = { resource, assertProject, assertResource, allowRelease: () => { safeRelease = true; } };
    return await executeObservation({ request, root, deadline, started }, dependencies, scope, () => { safeRelease = false; });
  } finally { if (safeRelease) { releaseResource?.(); project.lease.release(); } }
}

async function executeObservation(context: ObservationContext, dependencies: GradeDependencies,
  scope: ObservationScope, retain: () => void): Promise<PrivateGradeObservation> {
  const { request, root, deadline, started } = context;
  checkTime(deadline);
  const job = createJob(request, root, deadline);
  writeRecord(path.join(scope.resource, "active.json"), { jobId: job.input.jobId, dir: request.dir, requestDigest: job.inputHash });
  retain(); scope.assertProject(); scope.assertResource();
  let held: GradeProcessResult;
  try { held = await dependencies.run({ root, directory: job.directory, inputHash: job.inputHash, deadline }); }
  catch { held = { status: "interrupted", cleanupVerified: false, resultSha256: null, handshake: null }; }
  const result = collectResult({ job, held, context }, scope);
  result.elapsedMs = Number(process.hrtime.bigint() - started) / 1e6;
  persistObservationCandidate(result, { directory: job.directory, deadline, held });
  result.elapsedMs = Number(process.hrtime.bigint() - started) / 1e6;
  return result;
}

function collectResult(input: { job: ReturnType<typeof createJob>; held: GradeProcessResult; context: ObservationContext },
  scope: ObservationScope): PrivateGradeObservation {
  const { job, held, context: { request, root, deadline } } = input;
  const result: PrivateGradeObservation = { jobId: job.input.jobId, sourceId: request.sourceId, status: "interrupted",
    cleanupVerified: false, elapsedMs: 0, cleanupMs: 0, decodedFrames: null,
    error: "Observation completion or cleanup is unverified; retained private ownership requires recovery.", gradeApplicable: false, deliveryApproved: false };
  try {
    scope.assertProject(); scope.assertResource();
    // Only cleanup validation may continue after the work budget; it cannot publish success.
    const cleanupCheck = process.hrtime.bigint() + BigInt(5_000_000_000);
    if (canonicalJsonSha256(sourceInventory(root, cleanupCheck)) !== job.inventoryHash) throw new Error("Observation implementation changed");
    const value = verifiedResult(job, held);
    result.cleanupVerified = held.cleanupVerified;
    result.cleanupMs = typeof value.cleanupMs === "number" ? value.cleanupMs : 0;
    result.status = held.status;
    result.error = held.status === "failed" ? String((value.errors as unknown[])?.[0] ?? "Source observation failed") : null;
    if (held.cleanupVerified) { releaseClaim(scope.resource, job.inputHash); scope.allowRelease(); }
    if (held.status === "complete") completeResult(result, value, job, deadline);
  } catch (error) { result.status = "interrupted"; result.decodedFrames = null; result.error = String(error); }
  return result;
}

/** Durable candidates are never independently selectable as completed work. */
export function persistObservationCandidate(result: PrivateGradeObservation,
  context: { directory: string; deadline: bigint; held: GradeProcessResult },
  io = { write: writeRecord, check: checkTime }): void {
  try {
    if (result.status === "complete") io.check(context.deadline);
    io.write(path.join(context.directory, "server-result.json"), { ...result,
      status: "candidate-only", candidateStatus: result.status, selection: "live-return-only",
      liveResultSha256: context.held.resultSha256, handshake: context.held.handshake,
      privateProcessFailure: context.held.failure ?? null });
    if (result.status === "complete") io.check(context.deadline);
  } catch (error) {
    result.status = "interrupted"; result.decodedFrames = null; result.error = String(error);
  }
}
function completeResult(result: PrivateGradeObservation, value: Record<string, unknown>, job: ReturnType<typeof createJob>, deadline: bigint): void {
  checkTime(deadline);
  if (!result.cleanupVerified || canonicalJsonSha256(parents(job.input.producerDir)) !== canonicalJsonSha256(job.input.expected))
    throw new Error("Observation parents changed or exact cleanup is missing");
  const facts = object(value.observation), source = object(facts.source);
  if (source.sourceId !== job.input.sourceId || source.declarationSha256 !== canonicalJsonSha256(job.input.declaration)
      || facts.gradeApplicable !== false || facts.deliveryApproved !== false || facts.decodedFrameFlagsAvailable !== false
      || !Number.isSafeInteger(facts.decodedFrames) || Number(facts.decodedFrames) < 1 || facts.decodedFrames !== source.frameCount)
    throw new Error("Full-source observation result is not source/declaration/count bound");
  result.decodedFrames = facts.decodedFrames as number;
}
