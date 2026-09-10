/** Additive private all-source staging; no route, worker, transform or approval activation. */
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { isDeepStrictEqual } from "node:util";
import { parseGuidedOpeningExecutionClaim } from "@/lib/producer/contracts/guided-opening-claim-v1";
import { parseCurrentOpeningMediaInput } from "@/lib/producer/contracts/guided-opening-media-v1";
import { assertGuidedSourceColorCoverage } from "@/lib/producer/contracts/guided-source-color-v1";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { POLICY, privateDirectory, sourceInventoryUnderGuard } from "./grade-observation-store";
import type { SourceColorExpectation, SourceColorFileRef } from "./guided-source-color-expectations";
import { SourceColorStagingRead, assertSourceColorStagingMetadata, freezeSourceColorValue, sourceColorOpeningReference, type SourceColorStagingContext } from "./guided-source-color-staging-hold";
import { GUIDED_SOURCE_COLOR_TS_FILES } from "./guided-source-color-cleanup-pins";
import { beginSourceColorPrelaunchStaging, finishSourceColorPrelaunchStaging, type SourceColorPrelaunchOwner } from "./guided-source-color-prelaunch-owner";

/** Additive required pins; legacy standalone observation inventories are unchanged.
 * The controller must ALSO compare these files to its original pipeline lock
 * and actual current implementation before enabling the new request version.
 */
export { GUIDED_SOURCE_COLOR_TS_FILES } from "./guided-source-color-cleanup-pins";

interface PlannedSourceColorJob {
  sourceId: string; jobId: string; directory: string; inputPath: string;
  implementationPath: string; launchClaimPath: string; executionDir: string; containerName: string;
}
export interface StagedSourceColorJob extends PlannedSourceColorJob {
  input: SourceColorFileRef; implementation: SourceColorFileRef; launchClaim: SourceColorFileRef;
}
export interface StagedSourceColorInput {
  readonly scope: "staged-source-color-input-not-observation-transform-or-approval";
  readonly input: SourceColorFileRef; readonly reservation: SourceColorFileRef;
  readonly jobs: readonly StagedSourceColorJob[];
  readonly executable: false; readonly gradeApplicable: false; readonly deliveryApproved: false;
  assertCurrent(): void;
  /** Prospective directories only, before worker handoff; not a launch/clock capability. */
  assertUnstarted(): void;
}
const actualStaging = new WeakMap<StagedSourceColorInput, SourceColorStagingContext>();

/** Actual completed staging metadata only, not a constructor/DTO, work clock, lease or launch capability. */
export function assertStagedSourceColorMetadata(context: SourceColorStagingContext, staged: StagedSourceColorInput): void {
  if (actualStaging.get(staged) !== context) throw new Error("Source color metadata requires its actual completed staging result");
  assertSourceColorStagingMetadata(context, staged.assertCurrent);
}

function originalOpening(read: SourceColorStagingRead) {
  const { opening, expectations, producerDir } = read.context;
  const claim = parseGuidedOpeningExecutionClaim(opening.claim);
  const execution = path.join(producerDir, "guided-v2-operations", claim.requestId, "executions", claim.executionId);
  if (opening.claimPath !== path.join(execution, "execution-claim.json")
      || claim.inputPath !== path.join(execution, "media-input/input.json") || claim.outputRoot !== path.join(execution, "media-output")) {
    throw new Error("Source color staging requires the exact claimed opening execution");
  }
  const inputRef = expectations.files.find(row => row.path === claim.inputPath);
  if (!inputRef || inputRef.sha256 !== claim.inputSha256 || expectations.scope !== "held-source-color-expectations-not-source-observation-or-approval") {
    throw new Error("Source color staging expectation belongs to another original input");
  }
  if (!isDeepStrictEqual(read.read(opening.claimPath, opening.claimSha256, 128 * 1024), claim)) {
    throw new Error("Source color opening claim differs from its actual raw record");
  }
  const input = parseCurrentOpeningMediaInput(read.read(claim.inputPath, claim.inputSha256, 128 * 1024));
  if (input.executionId !== claim.executionId || input.executionInputHash !== claim.executionInputHash) {
    throw new Error("Source color original opening input identity differs");
  }
  return { execution, snapshotRoot: input.pipeline.snapshotRoot };
}
function validateSources(read: SourceColorStagingRead): void {
  const { sourceColor, expectations } = read.context;
  assertGuidedSourceColorCoverage(sourceColor, expectations.sources.map(row => row.sourceId));
  for (const source of expectations.sources) {
    const selected = sourceColor.declarations[source.sourceId];
    if (source.profile !== selected.profile || !isDeepStrictEqual(source.declaration, selected.declaration)
        || selected.declaration.lightingGroups.at(-1)?.endFrame !== source.frameCount) {
      throw new Error("Source color staging declaration differs from its original full-source expectation");
    }
  }
}
function stagingInventory(read: SourceColorStagingRead, snapshotRoot: string) {
  const inventory = sourceInventoryUnderGuard(snapshotRoot, read.check), known = new Map(inventory.files.map(row => [row.path, row.sha256]));
  const pins = read.holdCodeBatch(GUIDED_SOURCE_COLOR_TS_FILES.map(relative => path.join(snapshotRoot, relative)));
  for (const row of pins) {
    const previous = known.get(row.path);
    if (previous !== undefined && previous !== row.sha256) throw new Error("Source color original inventory pin changed");
    known.set(row.path, row.sha256);
  }
  if (known.size > 4000) throw new Error("Source color implementation inventory exceeds its original file bound");
  read.check();
  return { files: [...known].sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
    .map(([file, sha256]) => ({ path: file, sha256 })) };
}
function planJobs(producerDir: string, sources: readonly SourceColorExpectation[]): PlannedSourceColorJob[] {
  return sources.map(source => {
    const jobId = randomUUID(), directory = path.join(producerDir, ".sniper-grade-observations", jobId);
    return { sourceId: source.sourceId, jobId, directory, inputPath: path.join(directory, "input.json"),
      implementationPath: path.join(directory, "implementation.json"), launchClaimPath: path.join(directory, "launch-claim.json"),
      executionDir: path.join(directory, "execution"), containerName: `sniper-grade-observation-${jobId.replaceAll("-", "")}` };
  });
}
function reserve(read: SourceColorStagingRead, jobs: PlannedSourceColorJob[], sidecarPath: string) {
  const { context } = read;
  const value = { schemaVersion: 2, kind: "guided-source-color-reservation",
    scope: "reserved-grade-container-names-not-process-settlement-or-cleanup", producerDir: context.producerDir,
    opening: sourceColorOpeningReference(context), sourceColorHash: canonicalJsonSha256(context.sourceColor), sidecarPath,
    ownerPid: process.pid, runtime: structuredClone(context.opening.claim.runtime), jobs };
  return read.publish(path.join(context.resource.resource, "active.json"), value);
}
function stageJob(read: SourceColorStagingRead, plan: PlannedSourceColorJob,
  source: SourceColorExpectation, inventory: ReturnType<typeof sourceInventoryUnderGuard>): StagedSourceColorJob {
  const { context } = read;
  read.check(); fs.mkdirSync(plan.directory, { mode: 0o700 }); read.holdDirectory(plan.directory);
  const implementation = read.publish(plan.implementationPath, inventory);
  const value = { schemaVersion: source.profile === null ? 1 : 2,
    policy: source.profile === null ? POLICY : "sniper-private-project-source-observation-v2", jobId: plan.jobId,
    producerDir: context.producerDir, sourceId: source.sourceId, declaration: structuredClone(source.declaration),
    ownerPid: process.pid, implementationSha256: implementation.sha256, expected: context.expectations.parents,
    ...(source.profile === null ? {} : { profile: source.profile }) };
  const input = read.publish(plan.inputPath, value);
  const launchClaim = read.publish(plan.launchClaimPath, { schemaVersion: 1, kind: "owned-grade-launch-claim",
    scope: "preclaimed-source-observation-not-recovery-or-approval", jobId: plan.jobId, inputPath: plan.inputPath,
    inputSha256: input.sha256, executionDir: plan.executionDir, sourcePath: source.sourcePath,
    sourceSha256: source.sourceSha256, frameCount: source.frameCount, profile: source.profile, containerName: plan.containerName,
    openingClaimPath: context.opening.claimPath, openingClaimSha256: context.opening.claimSha256,
    runtime: structuredClone(context.opening.claim.runtime) });
  // The actual owned Python launch must create this directory itself, once.
  requireAbsentExecution(plan.executionDir);
  return { ...plan, input, implementation, launchClaim };
}
function requireAbsentExecution(directory: string): void {
  try { fs.lstatSync(directory); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
    throw error;
  }
  throw new Error("Source color execution was created before its owned launch");
}

/** Reserve ALL possible names before job metadata. Failure retains every publication and lease.
 * The enclosing controller must authenticate process settlement and every reserved name's
 * absence before cleanup/release, including when a job or final sidecar was never created.
 * A returned object is preparation data only: Python admission and owned execution remain mandatory.
 */
export function stageGuidedSourceColor(context: SourceColorStagingContext, prelaunch?: SourceColorPrelaunchOwner): StagedSourceColorInput {
  const read = prelaunch ? beginSourceColorPrelaunchStaging(prelaunch, context) : new SourceColorStagingRead(context);
  read.holdDirectory(context.producerDir); read.holdDirectory(context.resource.resource);
  read.check(); validateSources(read);
  const original = originalOpening(read);
  // Capture once from the EXECUTED snapshot, using the original owner's budget callback.
  const inventory = stagingInventory(read, original.snapshotRoot);
  const jobs = planJobs(context.producerDir, context.expectations.sources);
  const directory = path.join(original.execution, "source-color"), sidecarPath = path.join(directory, "input.json");
  read.check(); fs.mkdirSync(directory, { mode: 0o700 }); read.holdDirectory(directory);
  privateDirectory(context.resource.resource);
  const reservation = reserve(read, jobs, sidecarPath);
  privateDirectory(path.join(context.producerDir, ".sniper-grade-observations"), true);
  const staged = jobs.map((job, index) => stageJob(read, job, context.expectations.sources[index], inventory));
  const input = read.publish(sidecarPath, { schemaVersion: 1, kind: "guided-source-color-input",
    scope: "private-source-observation-not-transform-or-approval", opening: sourceColorOpeningReference(context),
    producerDir: context.producerDir, sourceColor: context.sourceColor, expected: context.expectations.parents,
    reservation, jobs: staged, executable: false, gradeApplicable: false, deliveryApproved: false });
  const assertUnstarted = () => { read.check(); staged.forEach(job => requireAbsentExecution(job.executionDir)); };
  const result = freezeSourceColorValue({ scope: "staged-source-color-input-not-observation-transform-or-approval" as const,
    input, reservation, jobs: staged, executable: false as const, gradeApplicable: false as const,
    deliveryApproved: false as const, assertCurrent: read.check, assertUnstarted });
  assertUnstarted(); actualStaging.set(result, context);
  if (prelaunch) finishSourceColorPrelaunchStaging(prelaunch, context, result);
  return result;
}
