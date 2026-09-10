/** Live schema2 mechanical selection under the actual readback owner. No opening/body/delivery approval. */
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import type { ProjectMutationLease } from "./project-mutation-lease";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { assertSourceColorOpeningReadbackOwner,
  type verifyCleanedSourceColorOpeningMediaUnderLease } from "./guided-source-color-readback";
import { readCommittedOpeningCleanup, readHistoricalOpeningCleanup, assertOpeningCleanupMetadata } from "./guided-opening-cleanup-store";
import { readHeldSourceColorOpeningResult } from "./guided-source-color-opening-result";
import { readSourceColorReadbackHistory, assertSourceColorReadbackHistoryMetadata } from "./guided-source-color-readback-history";
import { holdSelectionMedia, sourceColorSelectionReference } from "./guided-source-color-selection-read";
import { selectedOpeningRow, openingMediaDescriptors, openingSelectionFact } from "./guided-opening-selection";
import { readGuidedProposalReadiness } from "./guided-proposal-review-store";
import { writeGuidedObject } from "./guided-cut-v2-store";
import { createHumanCutIndex, observeHumanCutJob, saveHumanCutJobSnapshot } from "./human-cut-acceptance-store";
import { commitGuidedJob } from "./guided-cut-v2";
import { autoEditJobPath } from "./auto-edit-job-persistence";
import { capturePublication, assertPublication } from "./guided-source-color-cleanup-pending-commit";
import { retainGenerationClockObservation } from "./generation-clock-watermark";
import { snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";

export type VerifiedSourceColorOpening = Awaited<ReturnType<typeof verifyCleanedSourceColorOpeningMediaUnderLease>>;
export interface SourceColorSelectionInput { dir: string; lease: ProjectMutationLease; verified: VerifiedSourceColorOpening; remainingMs: () => number }
export const sourceColorSelectionDependencies = { readiness: readGuidedProposalReadiness };
const committed = new WeakMap<object, () => void>();
type Checkpoint = { started: number; remaining: number; observedAt: string };

function same(actual: unknown, expected: unknown): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error("Source-color selection original evidence changed");
}

/** Split original caller identity from the deliberately superseded current journal. */
function owner(input: SourceColorSelectionInput) {
  const original = { ...input, release: input.lease.release }, verified = original.verified;
  const liveInput = { dir: original.dir, lease: original.lease, remainingMs: original.remainingMs, expectedCleanupHash: verified.observed.cleanupHash };
  assertSourceColorOpeningReadbackOwner(verified, liveInput);
  const rows = { core: selectedOpeningRow(verified.selected.record.value, "core", verified.observed.held.claim.outputRoot),
    review: selectedOpeningRow(verified.selected.record.value, "review", verified.observed.held.claim.outputRoot) };
  const media = holdSelectionMedia(rows);
  const lease = cutPreviewLeaseGuard(original.dir, original.lease);
  const unchanged = () => {
    if (input.dir !== original.dir || input.lease !== original.lease || input.verified !== verified
        || input.remainingMs !== original.remainingMs || input.lease.release !== original.release) throw new Error("Source-color selection original owner changed");
  };
  const metadata = () => { unchanged(); lease(); assertSourceColorOpeningReadbackOwner(verified, liveInput); media(); unchanged(); };
  const check = (): Checkpoint => {
    metadata(); const began = performance.now(), remaining = original.remainingMs(); metadata();
    if (!Number.isSafeInteger(remaining) || remaining <= 0 || remaining > 1_500_000) throw new Error("Source-color selection original remainder is invalid");
    if (observeHumanCutJob(original.dir).sha256 !== verified.observed.sha256) throw new Error("Source-color selection journal changed since readback");
    metadata(); const elapsed = performance.now() - began;
    if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed >= remaining) throw new Error("Source-color selection original allowance expired");
    return { started: performance.now(), remaining: remaining - elapsed, observedAt: new Date().toISOString() };
  };
  return { original, verified, lease, rows, media, unchanged, metadata, check };
}
type Owner = ReturnType<typeof owner>;

function prepare(owner: Owner, controls: typeof sourceColorSelectionDependencies) {
  const { original: { dir }, verified } = owner, held = verified.observed.held;
  owner.check(); controls.readiness(dir); owner.check();
  const cleanup = readCommittedOpeningCleanup(dir); owner.check(); assertOpeningCleanupMetadata(cleanup);
  same([cleanup.sha256, cleanup.cleanupHash, cleanup.held.claimHash], [verified.observed.sha256, verified.observed.cleanupHash, held.claimHash]);
  const { rows, media } = owner, selectionQualifiedAt = new Date().toISOString();
  const fact = openingSelectionFact(verified, rows, selectionQualifiedAt, 2);
  if (selectionQualifiedAt < String(verified.receipt.value.createdAt)) throw new Error("Source-color selection predates actual readback");
  openingMediaDescriptors(dir, "0".repeat(64), rows); owner.check(); media();
  return { fact, rows, media };
}

/** Publish only new metadata. Failed pre-CAS publication is retained, never silently overwritten or retried. */
function publications(owner: Owner, prepared: ReturnType<typeof prepare>) {
  const { original: { dir }, verified } = owner, selectionHash = writeGuidedObject(dir, prepared.fact);
  const fact = capturePublication(path.join(dir, ".sniper-authority-v1/objects/receipts", `${selectionHash}.json`), selectionHash);
  owner.check(); prepared.media(); saveHumanCutJobSnapshot(dir, verified.observed);
  const snapshot = capturePublication(path.join(dir, "human-cut-job-snapshots", `${verified.observed.sha256}.json`), verified.observed.sha256);
  const record = { ...prepared.fact, selectionHash }, file = path.join(path.dirname(verified.receipt.path), "selection.json");
  owner.check(); createHumanCutIndex(file, record);
  const raw = readCutPreviewObject(file); same(raw.value, record);
  const index = capturePublication(file, raw.sha256);
  const metadata = () => { assertPublication(fact); assertPublication(snapshot); assertPublication(index); prepared.media(); };
  owner.check(); metadata(); return { selectionHash, metadata };
}

/** Historical proof is established before CAS while the original current readback is still valid. */
function history(owner: Owner, prepared: ReturnType<typeof prepare>) {
  const before = readHistoricalOpeningCleanup(owner.original.dir, owner.verified.observed.sha256); owner.check();
  const selected = readHeldSourceColorOpeningResult({ held: before.held, guard: () => { owner.check(); } });
  const held = readSourceColorReadbackHistory({ cleanup: before, selected, reference: sourceColorSelectionReference(prepared.fact),
    guard: () => { owner.check(); } });
  assertSourceColorReadbackHistoryMetadata(held); return held;
}

function selectedJob(owner: Owner, prepared: ReturnType<typeof prepare>, selectionHash: string) {
  const job = owner.verified.observed.job, at = prepared.fact.selectionQualifiedAt;
  return { ...job, updatedAt: at, guidedHandoffV2: { ...job.guidedHandoffV2!, openingMediaSelectionHash: selectionHash },
    message: "Exact private opening media is selected for mechanical review playback. No opening, body or final is approved.",
    nextEventId: job.nextEventId + 1, events: [...job.events, { id: job.nextEventId, at,
      payload: { event: "opening_media_selected", executionId: prepared.fact.executionId, selectionHash,
        cleanupHash: prepared.fact.cleanupHash, openingApproved: false, deliveryApproved: false } }].slice(-256) };
}

function tail(checkpoint: Checkpoint | undefined): void {
  if (!checkpoint) throw new Error("Source-color selection CAS omitted the original clock guard");
  const elapsed = performance.now() - checkpoint.started;
  if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed >= checkpoint.remaining || new Date().toISOString() < checkpoint.observedAt) {
    throw new Error("Source-color selection CAS tail expired; selection may be committed, retain all evidence");
  }
}

/** Exact same owner only. Post-CAS failure never writes retroactive readback failure or releases either lease. */
export function selectSourceColorOpeningMedia(input: SourceColorSelectionInput) {
  const controls = { ...sourceColorSelectionDependencies }, live = owner(input), prepared = prepare(live, controls);
  const published = publications(live, prepared), retained = history(live, prepared);
  const job = selectedJob(live, prepared, published.selectionHash), fixedJob = snapshotSourceColorMetadata(job);
  const historical = () => { live.unchanged(); live.lease(); published.metadata(); assertSourceColorReadbackHistoryMetadata(retained); };
  let checkpoint: Checkpoint | undefined;
  const guard = () => {
    live.check(); historical(); same(job, fixedJob);
    const held = live.verified.observed.held;
    retainGenerationClockObservation({ dir: live.original.dir, origin: { clockHash: held.claim.clockHash, startedAt: held.claim.generationStartedAt },
      executionId: held.claim.executionId, observedAt: new Date().toISOString() }, live.metadata);
    checkpoint = live.check(); historical(); same(job, fixedJob);
  };
  commitGuidedJob({ beforeHash: live.verified.observed.sha256, job, guard });
  const current = observeHumanCutJob(live.original.dir); same(current.job, fixedJob);
  const journal = capturePublication(autoEditJobPath(live.original.dir), current.sha256);
  const value = Object.freeze({ selectionHash: published.selectionHash, fact: prepared.fact,
    mediaSelected: true as const, openingApproved: false as const, deliveryApproved: false as const });
  const fixed = snapshotSourceColorMetadata(value);
  const metadata = () => { same(value, fixed); historical(); assertPublication(journal); };
  metadata(); tail(checkpoint); committed.set(value, metadata); return value;
}

/** Authenticity is checked before any caller-visible version field can influence dispatch. */
export function isCommittedSourceColorSelection(value: object): boolean { return committed.has(value); }

/** No stale current readback or original work callbacks after the intentional CAS. */
export function assertCommittedSourceColorSelectionMetadata(value: object): void {
  const check = committed.get(value);
  if (!check) throw new Error("Source-color selection requires its actual committed metadata handle");
  check();
}
