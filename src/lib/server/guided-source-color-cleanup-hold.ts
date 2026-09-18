/** Exact cold reservation metadata, not process settlement or permission to release a lease.
 * The enclosing owner supplies its actual claim, authenticated process reference,
 * original protected deadline and original project/resource ownership guard.
 * No source, job, sidecar, tool, decoder, daemon or configuration file is opened.
 */
import fs from "node:fs";
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { exactKeys, objectValue, uuid } from "@/lib/producer/contracts/validation";
import { parseCurrentOpeningMediaInput, openingAbsolutePath } from "@/lib/producer/contracts/guided-opening-media-v1";
import { parseGuidedOpeningExecutionClaim } from "@/lib/producer/contracts/guided-opening-claim-v1";
import { parsePrepareGuidedOpeningRequest } from "@/lib/producer/contracts/guided-source-color-v1";
import { parseCurrentOpeningCleanupResult, type OpeningCleanupResultV2 } from "@/lib/producer/contracts/guided-opening-cleanup-v2";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { freezeSourceColorValue, snapshotSourceColorMetadata, sourceColorOpeningReference } from "./guided-source-color-staging-hold";
import { parseOpeningSourceColorProcessReference, type OpeningSourceColorProcessReference } from "./guided-source-color-process-binding";
import type { HeldOpeningClaim } from "./guided-opening-process";

export interface SourceColorCleanupHoldContext {
  held: HeldOpeningClaim; reference: OpeningSourceColorProcessReference; resourceDir: string;
  guard: () => void; remainingMs: () => number;
}
export interface HeldSourceColorCleanupReservation {
  readonly reference: OpeningSourceColorProcessReference; readonly containerNames: readonly string[];
  assertCurrent(): void; assertResult(value: OpeningCleanupResultV2): void;
}
export type SourceColorCleanupReservationJoin = Pick<SourceColorCleanupHoldContext, "held" | "reference">;
const originalReservations = new WeakMap<HeldSourceColorCleanupReservation, () => Buffer>();
const originalReservationMetadata = new WeakMap<HeldSourceColorCleanupReservation, () => void>();
const MAX_BYTES = 8 * 1024 * 1024;
const JOB_KEYS = ["sourceId", "jobId", "directory", "inputPath", "implementationPath", "launchClaimPath", "executionDir", "containerName"];

function same(actual: unknown, expected: unknown, label: string): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error(`Source color cleanup original ${label} changed`);
}
function fileIdentity(file: string): bigint[] {
  const stat = fs.lstatSync(file, { bigint: true });
  if (!stat.isFile() || stat.nlink !== BigInt(1)) throw new Error("Source color cleanup metadata must be regular and single-link");
  return [stat.dev, stat.ino, stat.mode, stat.uid, stat.nlink, stat.size, stat.mtimeNs, stat.ctimeNs];
}
function directoryIdentity(directory: string): bigint[] {
  const stat = fs.lstatSync(directory, { bigint: true });
  if (!stat.isDirectory() || fs.realpathSync(directory) !== directory) throw new Error("Source color cleanup parent is not canonical");
  return [stat.dev, stat.ino, stat.mode, stat.uid];
}
function metadata(context: SourceColorCleanupHoldContext) {
  const { held, reference, resourceDir } = context;
  return { claim: held.claim, claimPath: held.claimPath, claimSha256: held.claimSha256, claimHash: held.claimHash,
    submission: held.submission, producerDir: held.job.ctx.dir, reference, resourceDir };
}

/** Capture all three original file/parent identities before the first owner callback. */
class ReservationRead {
  private readonly original;
  private readonly fixed;
  private readonly files = new Map<string, bigint[]>();
  private readonly parents = new Map<string, bigint[]>();
  constructor(readonly context: SourceColorCleanupHoldContext) {
    this.original = { held: context.held, reference: context.reference, guard: context.guard, remainingMs: context.remainingMs };
    this.fixed = snapshotSourceColorMetadata(metadata(context));
    for (const file of [context.reference.reservation.path, context.held.claimPath, context.held.claim.inputPath]) this.capture(file);
  }
  private capture(file: string): void {
    openingAbsolutePath(file); this.files.set(file, fileIdentity(file));
    for (let directory = path.dirname(file);;) {
      const identity = directoryIdentity(directory), previous = this.parents.get(directory);
      if (previous) same(identity, previous, "parent during capture");
      this.parents.set(directory, identity);
      const parent = path.dirname(directory); if (parent === directory) return;
      directory = parent;
    }
  }
  private unchanged(): void {
    const c = this.context, o = this.original;
    if (c.held !== o.held || c.reference !== o.reference || c.guard !== o.guard || c.remainingMs !== o.remainingMs) {
      throw new Error("Source color cleanup original caller identity changed");
    }
    same(metadata(c), this.fixed, "claim/request/reference");
  }
  check = (): void => {
    this.unchanged(); this.original.guard();
    const remaining = this.original.remainingMs();
    if (!Number.isFinite(remaining) || remaining <= 0 || remaining > 300_000) throw new Error("Source color cleanup original protected deadline is invalid");
    this.checkMetadata();
  };
  checkMetadata = (): void => {
    this.unchanged();
    for (const [directory, identity] of this.parents) same(directoryIdentity(directory), identity, "parent");
    for (const [file, identity] of this.files) same(fileIdentity(file), identity, "file");
    this.unchanged();
  };
  read(file: string, hash: string, maximum: number): { value: unknown; sizeBytes: number; bytes: Buffer } {
    if (!this.files.has(file)) throw new Error("Source color cleanup cannot discover additional files");
    this.check(); const observed = observeCutPreviewFile(file, maximum, true, this.check);
    if (observed.sha256 !== hash) throw new Error("Source color cleanup original raw SHA differs");
    const value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(observed.bytes));
    this.check(); return { value, sizeBytes: observed.sizeBytes, bytes: observed.bytes };
  }
}

function originalOpening(context: SourceColorCleanupReservationJoin) {
  const { claim, claimPath, claimSha256, claimHash, job } = context.held;
  parseGuidedOpeningExecutionClaim(claim);
  const execution = path.join(job.ctx.dir, "guided-v2-operations", claim.requestId, "executions", claim.executionId);
  if (claimPath !== path.join(execution, "execution-claim.json") || claim.inputPath !== path.join(execution, "media-input/input.json")
      || claim.outputRoot !== path.join(execution, "media-output") || claimSha256 !== claimHash) {
    throw new Error("Source color cleanup requires its exact original claimed execution");
  }
  return sourceColorOpeningReference({ opening: context.held });
}
function plannedJob(value: unknown, producerDir: string) {
  const row = objectValue(value, "source color reserved job"); exactKeys(row, JOB_KEYS, JOB_KEYS, "source color reserved job");
  const jobId = uuid(row.jobId, "grade jobId");
  if (jobId[14] !== "4" || typeof row.sourceId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/u.test(row.sourceId)) {
    throw new Error("Source color cleanup reserved source/job identifier differs");
  }
  const directory = path.join(producerDir, ".sniper-grade-observations", jobId), containerName = `sniper-grade-observation-${jobId.replaceAll("-", "")}`;
  same(row, { sourceId: row.sourceId, jobId, directory, inputPath: path.join(directory, "input.json"),
    implementationPath: path.join(directory, "implementation.json"), launchClaimPath: path.join(directory, "launch-claim.json"),
    executionDir: path.join(directory, "execution"), containerName }, "reserved job paths/name");
  return { sourceId: row.sourceId, containerName };
}
/** Pure original-claim/full-request/name join only; archive readers authenticate their own raw bytes. */
export function sourceColorCleanupReservationNames(value: unknown, context: SourceColorCleanupReservationJoin): string[] {
  const row = objectValue(value, "source color reservation"), keys = ["schemaVersion", "kind", "scope", "producerDir", "opening",
    "sourceColorHash", "sidecarPath", "ownerPid", "runtime", "jobs"];
  exactKeys(row, keys, keys, "source color reservation");
  const request = parsePrepareGuidedOpeningRequest(context.held.submission), { reference, held } = context;
  if (request.schemaVersion !== 2 || request.idempotencyKey !== held.claim.requestId || request.expectedJournalHash !== held.claim.beforeJournalHash
      || !Number.isSafeInteger(row.ownerPid) || Number(row.ownerPid) < 1 || Number(row.ownerPid) > 2 ** 31 - 1
      || !Array.isArray(row.jobs) || !row.jobs.length || row.jobs.length > 128) throw new Error("Source color cleanup request or reservation is malformed");
  same(row, { schemaVersion: 2, kind: "guided-source-color-reservation", scope: "reserved-grade-container-names-not-process-settlement-or-cleanup",
    producerDir: held.job.ctx.dir, opening: originalOpening(context), sourceColorHash: canonicalJsonSha256(request.sourceColor),
    sidecarPath: reference.input.path, ownerPid: row.ownerPid, runtime: held.claim.runtime, jobs: row.jobs }, "reservation bindings");
  if (row.sourceColorHash !== reference.sourceColorHash) throw new Error("Source color cleanup process request differs");
  const jobs = row.jobs.map(item => plannedJob(item, held.job.ctx.dir)), ids = jobs.map(job => job.sourceId), names = jobs.map(job => job.containerName);
  same([...ids].sort(), Object.keys(request.sourceColor.declarations).sort(), "complete reserved source coverage");
  if (new Set(names).size !== names.length) throw new Error("Source color cleanup repeats a reserved container name");
  return names;
}

function resultClaim(value: OpeningCleanupResultV2, held: HeldOpeningClaim): void {
  same({ claimPath: value.claimPath, claimSha256: value.claimSha256, inputSha256: value.inputSha256,
    outputRoot: value.outputRoot, executionId: value.executionId, orders: value.graphics.map(row => row.order) },
  { claimPath: held.claimPath, claimSha256: held.claimSha256, inputSha256: held.claim.inputSha256,
    outputRoot: held.claim.outputRoot, executionId: held.claim.executionId, orders: held.claim.selectedGraphicOrders }, "cleanup result full claim");
}

/** Pure full-claim/reference/name join; caller separately retains actual output and ownership evidence. */
export function assertSourceColorCleanupResult(value: OpeningCleanupResultV2, context: SourceColorCleanupReservationJoin,
  names: readonly string[]): void {
  const result = parseCurrentOpeningCleanupResult(value);
  if (result.schemaVersion !== 2) throw new Error("Source color cleanup cannot accept legacy graphics-only completion");
  resultClaim(result, context.held);
  same(result.sourceColor.reservation, context.reference.reservation, "cleanup result raw reference");
  same(result.sourceColor.sourceColorHash, context.reference.sourceColorHash, "cleanup result request");
  same(result.sourceColor.batch.jobs.map(job => job.containerName), names, "cleanup result complete ordered names");
}

/** No lease is acquired/released and no process state is inferred by this metadata hold. */
export function holdSourceColorCleanupReservation(context: SourceColorCleanupHoldContext): HeldSourceColorCleanupReservation {
  const read = new ReservationRead(context); read.check();
  const { held, reference } = context;
  if (path.basename(context.resourceDir) !== ".sniper-color-resource") throw new Error("Source color cleanup resource namespace differs");
  parseOpeningSourceColorProcessReference(reference, held.claim, context.resourceDir);
  same(read.read(held.claimPath, held.claimSha256, 128 * 1024).value, held.claim, "raw claim");
  const input = parseCurrentOpeningMediaInput(read.read(held.claim.inputPath, held.claim.inputSha256, 128 * 1024).value);
  if (input.executionId !== held.claim.executionId || input.executionInputHash !== held.claim.executionInputHash) throw new Error("Source color cleanup original input differs");
  const raw = read.read(reference.reservation.path, reference.reservation.sha256, MAX_BYTES);
  same(raw.sizeBytes, reference.reservation.sizeBytes, "reservation raw size");
  const names = freezeSourceColorValue(sourceColorCleanupReservationNames(raw.value, context));
  const fixed = freezeSourceColorValue(structuredClone(reference)); read.check();
  const result = Object.freeze({ reference: fixed, containerNames: names, assertCurrent: read.check,
    assertResult: (value: OpeningCleanupResultV2) => {
      const original = structuredClone(value);
      read.check(); same(value, original, "cleanup result before validation");
      assertSourceColorCleanupResult(value, { held, reference: fixed }, names);
      read.check(); same(value, original, "cleanup result after validation");
    } });
  originalReservations.set(result, () => { read.check(); const bytes = Buffer.from(raw.bytes); read.check(); return bytes; });
  originalReservationMetadata.set(result, read.checkMetadata);
  return result;
}

/** Copy only the original raw metadata of an actual live hold. No JSON/duck-typed hold can supply it.
 * The caller must still publish new-only and authenticate the archive before
 * any retirement; possessing bytes is never settlement or release authority.
 */
export function copySourceColorCleanupReservation(held: HeldSourceColorCleanupReservation): Buffer {
  const copy = originalReservations.get(held);
  if (!copy) throw new Error("Source color reservation copy requires the actual original metadata hold");
  return copy();
}

/** Final original metadata sweep only, with no caller callbacks or new authority.
 * An enclosing owner must first check its actual lease/clock and charge this
 * sweep to that SAME remainder. This cannot substitute for assertCurrent.
 */
export function assertSourceColorCleanupReservationMetadata(held: HeldSourceColorCleanupReservation): void {
  const check = originalReservationMetadata.get(held);
  if (!check) throw new Error("Source color reservation metadata requires the actual original metadata hold");
  check();
}
