/** Explicit all-source process transport, not a launch, cleanup or grade capability.
 * The controller must supply its actual claimed execution, retained full request,
 * original budget/project guard and acquired resource. No file discovery occurs.
 */
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { exactKeys, objectValue, sha256 } from "@/lib/producer/contracts/validation";
import { openingAbsolutePath } from "@/lib/producer/contracts/guided-opening-media-v1";
import { parsePrepareGuidedOpeningRequest, type PrepareGuidedOpeningV2 } from "@/lib/producer/contracts/guided-source-color-v1";
import type { GuidedOpeningExecutionClaimV1 } from "@/lib/producer/contracts/guided-opening-claim-v1";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { freezeSourceColorValue, snapshotSourceColorMetadata,
  sourceColorOpeningReference, type SourceColorStagingContext } from "./guided-source-color-staging-hold";
import type { SourceColorFileRef } from "./guided-source-color-expectations";
import { assertStagedSourceColorMetadata, type StagedSourceColorInput } from "./guided-source-color-staging";
import type { HeldOpeningClaim } from "./guided-opening-process";

const SCOPE = "explicit-staged-input-not-observation-cleanup-or-approval";
const MAX_BYTES = 8 * 1024 * 1024;
const processMetadataReads = new WeakMap<object, () => void>();
export interface OpeningSourceColorProcessReference {
  schemaVersion: 1; kind: "guided-opening-source-color-process-input"; scope: typeof SCOPE;
  input: SourceColorFileRef; reservation: SourceColorFileRef; sourceColorHash: string;
}
export interface OpeningSourceColorProcessContext {
  staging: SourceColorStagingContext; staged: StagedSourceColorInput; submission: PrepareGuidedOpeningV2;
}

function fileReference(value: unknown, expectedPath: string): SourceColorFileRef {
  const row = objectValue(value, "source color process file"), keys = ["path", "sha256", "sizeBytes"];
  exactKeys(row, keys, keys, "source color process file");
  openingAbsolutePath(row.path); sha256(row.sha256, "source color raw file SHA");
  if (row.path !== expectedPath || !Number.isSafeInteger(row.sizeBytes) || Number(row.sizeBytes) < 1 || Number(row.sizeBytes) > MAX_BYTES) {
    throw new Error("Source color process file differs from its exact path or byte bound");
  }
  return row as unknown as SourceColorFileRef;
}

/** Closed recorded reference only. Reading this JSON does not authenticate its caller or prove settlement. */
export function parseOpeningSourceColorProcessReference(value: unknown,
  claim: GuidedOpeningExecutionClaimV1, resourceDir: string): OpeningSourceColorProcessReference {
  const row = objectValue(value, "source color process reference"), keys = ["schemaVersion", "kind", "scope", "input", "reservation", "sourceColorHash"];
  exactKeys(row, keys, keys, "source color process reference"); openingAbsolutePath(resourceDir);
  if (row.schemaVersion !== 1 || row.kind !== "guided-opening-source-color-process-input" || row.scope !== SCOPE) {
    throw new Error("Source color process reference version or scope differs");
  }
  fileReference(row.input, path.join(path.dirname(claim.outputRoot), "source-color/input.json"));
  fileReference(row.reservation, path.join(resourceDir, "active.json")); sha256(row.sourceColorHash, "sourceColorHash");
  return row as unknown as OpeningSourceColorProcessReference;
}

function expectedRecords(context: OpeningSourceColorProcessContext, reference: OpeningSourceColorProcessReference) {
  const { staging: c, staged } = context, opening = sourceColorOpeningReference(c);
  const jobs = staged.jobs.map(({ input: _input, implementation: _implementation, launchClaim: _claim, ...job }) => {
    void _input; void _implementation; void _claim; return job;
  });
  return {
    input: { schemaVersion: 1, kind: "guided-source-color-input", scope: "private-source-observation-not-transform-or-approval",
      opening, producerDir: c.producerDir, sourceColor: c.sourceColor, expected: c.expectations.parents,
      reservation: reference.reservation, jobs: staged.jobs, executable: false, gradeApplicable: false, deliveryApproved: false },
    reservation: { schemaVersion: 2, kind: "guided-source-color-reservation",
      scope: "reserved-grade-container-names-not-process-settlement-or-cleanup", producerDir: c.producerDir,
      opening, sourceColorHash: reference.sourceColorHash, sidecarPath: reference.input.path,
      ownerPid: process.pid, runtime: c.opening.claim.runtime, jobs },
  };
}

function metadata(context: OpeningSourceColorProcessContext) {
  const { staging: c, staged, submission } = context;
  return { opening: c.opening, sourceColor: c.sourceColor, producerDir: c.producerDir, parents: c.expectations.parents,
    resourceDir: c.resource.resource, submission, scope: staged.scope, jobs: staged.jobs, input: staged.input,
    reservation: staged.reservation, executable: staged.executable, gradeApplicable: staged.gradeApplicable,
    deliveryApproved: staged.deliveryApproved };
}

/** Retain both original live staging and full submitted clauses BEFORE any caller callback. */
function liveGuard(context: OpeningSourceColorProcessContext) {
  const original = { staging: context.staging, staged: context.staged, submission: context.submission,
    guard: context.staging.guard, resource: context.staging.resource, assertResource: context.staging.resource.assertResource,
    current: context.staged.assertCurrent, unstarted: context.staged.assertUnstarted };
  const fixed = snapshotSourceColorMetadata(metadata(context));
  const unchanged = () => {
    if (context.staging !== original.staging || context.staged !== original.staged || context.submission !== original.submission
        || context.staging.guard !== original.guard || context.staging.resource !== original.resource
        || context.staging.resource.assertResource !== original.assertResource || context.staged.assertCurrent !== original.current
        || context.staged.assertUnstarted !== original.unstarted || !isDeepStrictEqual(metadata(context), fixed)) {
      throw new Error("Source color process lost its original staging or complete request");
    }
  };
  const check = (unstarted = false) => {
    unchanged(); original.guard(); original.assertResource();
    if (unstarted) original.unstarted(); else original.current();
    unchanged();
  };
  return { check, metadata: () => { unchanged(); assertStagedSourceColorMetadata(original.staging, original.staged); unchanged(); } };
}

function assertRequest(context: OpeningSourceColorProcessContext): void {
  const request = parsePrepareGuidedOpeningRequest(context.submission), { staging: c, staged } = context;
  if (request.schemaVersion !== 2 || request.idempotencyKey !== c.opening.claim.requestId
      || request.expectedJournalHash !== c.opening.claim.beforeJournalHash
      || !isDeepStrictEqual(request.sourceColor, c.sourceColor)
      || staged.scope !== "staged-source-color-input-not-observation-transform-or-approval"
      || staged.executable !== false || staged.gradeApplicable !== false || staged.deliveryApproved !== false) {
    throw new Error("Source color process cannot drop or substitute its original submitted clauses");
  }
}

function readExact(ref: SourceColorFileRef, guard: () => void): unknown {
  const observed = observeCutPreviewFile(ref.path, MAX_BYTES, true, guard);
  if (observed.sha256 !== ref.sha256 || observed.sizeBytes !== ref.sizeBytes) throw new Error("Source color process raw bytes changed");
  return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(observed.bytes));
}

/** Hold exact existing publications for the future versioned process intent/argv.
 * No worker, lease, directory, clock or completion object is created. The caller
 * must still recheck its SAME original remaining budget immediately before work.
 */
export function holdOpeningSourceColorProcess(context: OpeningSourceColorProcessContext) {
  const lifetime = liveGuard(context), guard = lifetime.check; guard(true); assertRequest(context);
  const reference = freezeSourceColorValue(parseOpeningSourceColorProcessReference({ schemaVersion: 1,
    kind: "guided-opening-source-color-process-input", scope: SCOPE, input: structuredClone(context.staged.input),
    reservation: structuredClone(context.staged.reservation), sourceColorHash: canonicalJsonSha256(context.submission.sourceColor) },
  context.staging.opening.claim, context.staging.resource.resource));
  const expected = structuredClone(expectedRecords(context, reference));
  for (const key of ["input", "reservation"] as const) {
    if (!isDeepStrictEqual(readExact(reference[key], guard), expected[key])) throw new Error("Source color process publications differ from original staged metadata");
  }
  guard(true);
  const result = Object.freeze({ reference, assertCurrent: () => guard(), assertUnstarted: () => guard(true) });
  processMetadataReads.set(result, lifetime.metadata); return result;
}

/** Exact original binding metadata only; no work, stop, cleanup, clock or lease authority is conferred. */
export function assertOpeningSourceColorProcessMetadata(value: ReturnType<typeof holdOpeningSourceColorProcess>): void {
  const check = processMetadataReads.get(value);
  if (!check) throw new Error("Source color process metadata requires its actual original binding");
  check();
}

/** Read only an already journal-authenticated intent's additional request binding.
 * This does not read the reservation, prove worker settlement, or supply a live
 * staging handle. Historical records retain their original recorded namespace.
 */
export function sourceColorFromOpeningProcessIntent(intent: Record<string, unknown>, held: HeldOpeningClaim) {
  if (intent.schemaVersion !== 3) {
    if (held.submission?.schemaVersion === 2 || Object.hasOwn(intent, "sourceColor")) {
      throw new Error("Legacy opening process cannot drop or carry source-color execution clauses");
    }
    return null;
  }
  const request = parsePrepareGuidedOpeningRequest(held.submission);
  if (request.schemaVersion !== 2) throw new Error("Source-color process requires the actual retained full V2 submission");
  const raw = objectValue(intent.sourceColor, "source color process reference");
  const reservation = objectValue(raw.reservation, "source color process reservation");
  const resourceDir = path.dirname(openingAbsolutePath(reservation.path));
  if (path.basename(resourceDir) !== ".sniper-color-resource") throw new Error("Source color recorded resource namespace differs");
  const reference = parseOpeningSourceColorProcessReference(raw, held.claim, resourceDir);
  if (reference.sourceColorHash !== canonicalJsonSha256(request.sourceColor)
      || request.idempotencyKey !== held.claim.requestId || request.expectedJournalHash !== held.claim.beforeJournalHash) {
    throw new Error("Source color process differs from its original full request and claim");
  }
  return freezeSourceColorValue(structuredClone(reference));
}
