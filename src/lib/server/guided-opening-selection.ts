import path from "node:path";
import { lstatSync } from "node:fs";
import { exactKeys, objectValue, sha256, stringValue, uuid } from "@/lib/producer/contracts/validation";
import { openingAbsolutePath } from "@/lib/producer/contracts/guided-opening-media-v1";
import { parseOpeningMedia } from "@/lib/producer/guided-opening-media-client";
import type { GuidedOpeningMediaDescriptorV1 } from "@/lib/producer/contracts/guided-opening-status-v1";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { readCommittedOpeningCleanup, readHistoricalOpeningCleanup } from "./guided-opening-cleanup-store";
import { assertHeldOpeningResultUnchanged, readHeldOpeningResult } from "./guided-opening-result";
import { assertOpeningFailureAbsent, assertOpeningRecord } from "./guided-opening-process-activation";
import { readGuidedProposalReadiness } from "./guided-proposal-review-store";
import { readGuidedObject, strictGuidedTimestamp, writeGuidedObject } from "./guided-cut-v2-store";
import { createHumanCutIndex, observeHumanCutJob, saveHumanCutJobSnapshot } from "./human-cut-acceptance-store";
import { commitGuidedJob } from "./guided-cut-v2";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { retainGenerationClockObservation } from "./generation-clock-watermark";
import type { ProjectMutationLease } from "./project-mutation-lease";
import type { verifyCleanedOpeningMediaUnderLease } from "./guided-opening-readback";
import { selectSourceColorOpeningMedia, isCommittedSourceColorSelection, assertCommittedSourceColorSelectionMetadata,
  type VerifiedSourceColorOpening } from "./guided-source-color-selection";
import { readSourceColorSelection, assertSourceColorSelectionReadMetadata, historicalSourceColorSelection,
  selectionReadGuard, assertSelectionReadTime, isSourceColorSelectionRead } from "./guided-source-color-selection-read";

export const OPENING_SELECTION_SCOPE = "mechanical-playback-selection-not-opening-body-or-delivery-approval" as const;
export const OPENING_RANGES = ["core", "review"] as const;
export type OpeningRange = typeof OPENING_RANGES[number];
type Verified = Awaited<ReturnType<typeof verifyCleanedOpeningMediaUnderLease>>;
export interface SelectedOpeningRow extends Omit<GuidedOpeningMediaDescriptorV1, "url"> { path: string }

function integer(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || Number(value) < 0) throw new Error(`Opening ${label} must be a nonnegative integer`);
  return Number(value);
}

/** The worker muxes each range to `<range>.mp4`, except that an IDENTICAL core/context range reuses core.mp4
 * (guided_opening_mux.mux_ranges). Accept that reuse only when both rows and both authority spans are the same. */
function sharedCoreArtifact(record: Record<string, unknown>, file: string): boolean {
  if (path.basename(file) !== "core.mp4") return false;
  const media = objectValue(record.media, "opening media"), authority = objectValue(record.authority, "opening authority");
  const core = objectValue(media.core, "opening core media"), review = objectValue(media.review, "opening review media");
  const spans = [objectValue(authority.core, "opening core range"), objectValue(authority.review, "opening review range")];
  return core.path === review.path && core.sha256 === review.sha256 && core.sizeBytes === review.sizeBytes
    && spans[0].startFrame === spans[1].startFrame && spans[0].endFrameExclusive === spans[1].endFrameExclusive;
}

/** One fixed private range artifact, described from the held worker record only; no fresh media hashing here. */
export function selectedOpeningRow(record: Record<string, unknown>, range: OpeningRange, outputRoot: string): SelectedOpeningRow {
  const row = objectValue(objectValue(record.media, "opening media")[range], `opening ${range} media`);
  const authority = objectValue(record.authority, "opening authority"), target = objectValue(authority.target, "opening target");
  const span = objectValue(authority[range], `opening ${range} range`), file = openingAbsolutePath(row.path);
  const fixedRole = path.basename(file) === `${range}.mp4` || (range === "review" && sharedCoreArtifact(record, file));
  if (path.dirname(file) !== outputRoot || !fixedRole) throw new Error("Opening selected media is not the fixed private range artifact");
  const startFrame = integer(row.startFrame, "startFrame"), endFrameExclusive = integer(row.endFrameExclusive, "endFrameExclusive");
  const startSample = integer(row.startSample, "startSample"), endSampleExclusive = integer(row.endSampleExclusive, "endSampleExclusive");
  if (startFrame !== 0 || startFrame !== span.startFrame || endFrameExclusive !== span.endFrameExclusive || endFrameExclusive <= startFrame
      || startSample !== 0 || endSampleExclusive <= startSample) throw new Error("Opening selected range differs from its authority");
  return { path: file, mediaSha256: sha256(row.sha256, "opening media sha256"), sizeBytes: integer(row.sizeBytes, "sizeBytes"),
    width: integer(target.width, "width"), height: integer(target.height, "height"), frameRate: stringValue(authority.frameRate, "frameRate", 21),
    videoFrames: endFrameExclusive - startFrame, startFrame, endFrameExclusive, audioSamples: endSampleExclusive - startSample };
}

export function openingMediaUrl(input: { dir: string; selectionHash: string; mediaSha256: string; range: OpeningRange }): string {
  const query = new URLSearchParams({ dir: input.dir, selectionHash: input.selectionHash, mediaSha256: input.mediaSha256, range: input.range });
  return `/api/producer/guided-opening/media?${query.toString()}`;
}

/** Browser descriptors derived from selected rows; validated by the same client parser the panel uses. */
export function openingMediaDescriptors(dir: string, selectionHash: string, rows: Record<OpeningRange, SelectedOpeningRow>) {
  const describe = (range: OpeningRange) => { const { path: _file, ...rest } = rows[range]; void _file;
    return { ...rest, url: openingMediaUrl({ dir, selectionHash, mediaSha256: rest.mediaSha256, range }) }; };
  return parseOpeningMedia({ core: describe("core"), review: describe("review") }, { dir, selectionHash });
}

const FACT_KEYS = ["schemaVersion", "kind", "scope", "claimHash", "executionId", "inputSha256", "executionInputHash", "cleanupHash", "beforeJournalHash",
  "readbackDirectory", "readbackStartSha256", "readbackOutputSha256", "readbackReceiptSha256", "mediaResultSha256", "receiptHash", "outputRoot", "media",
  "clockHash", "generationStartedAt", "selectionQualifiedAt", "openingApproved", "deliveryApproved"];

/** Shared field projection only; the explicit live owner supplies its already-authenticated schema version. */
export function openingSelectionFact(verified: Verified | VerifiedSourceColorOpening, rows: Record<OpeningRange, SelectedOpeningRow>,
  selectionQualifiedAt: string, schemaVersion: 1 | 2 = 1) {
  const held = verified.observed.held;
  return { schemaVersion, kind: "guided-opening-media-selection", scope: OPENING_SELECTION_SCOPE, claimHash: held.claimHash,
    executionId: held.claim.executionId, inputSha256: held.claim.inputSha256, executionInputHash: held.claim.executionInputHash,
    cleanupHash: verified.observed.cleanupHash, beforeJournalHash: verified.observed.sha256, readbackDirectory: path.basename(path.dirname(verified.receipt.path)),
    readbackStartSha256: String(verified.receipt.value.startSha256), readbackOutputSha256: verified.output.sha256, readbackReceiptSha256: verified.receipt.sha256,
    mediaResultSha256: verified.selected.record.sha256, receiptHash: verified.selected.completion.receiptHash, outputRoot: held.claim.outputRoot,
    media: rows, clockHash: held.claim.clockHash, generationStartedAt: held.claim.generationStartedAt, selectionQualifiedAt,
    openingApproved: false, deliveryApproved: false };
}

/** Commit the exact playback selection under the SAME live lease, journal and original budget as the readback. No approval is implied. */
function selectLegacyOpeningMedia(input: { dir: string; lease: ProjectMutationLease; verified: Verified; remainingMs: () => number }) {
  const { dir, verified } = input, held = verified.observed.held, guard = cutPreviewLeaseGuard(dir, input.lease);
  const check = () => { guard(); input.remainingMs(); if (observeHumanCutJob(dir).sha256 !== verified.observed.sha256) throw new Error("Opening journal changed since readback"); };
  check(); assertOpeningRecord(verified.receipt); assertOpeningRecord(verified.output); assertHeldOpeningResultUnchanged(held, verified.selected);
  readGuidedProposalReadiness(dir);
  const cleanup = readCommittedOpeningCleanup(dir);
  if (cleanup.cleanupHash !== verified.observed.cleanupHash || cleanup.held.claimHash !== held.claimHash) throw new Error("Opening cleanup lineage changed since readback");
  const rows = { core: selectedOpeningRow(verified.selected.record.value, "core", held.claim.outputRoot),
    review: selectedOpeningRow(verified.selected.record.value, "review", held.claim.outputRoot) };
  for (const row of Object.values(rows)) { const stat = lstatSync(row.path); if (!stat.isFile() || stat.size !== row.sizeBytes) throw new Error("Opening selected media size changed"); }
  const selectionQualifiedAt = new Date().toISOString(), fact = openingSelectionFact(verified, rows, selectionQualifiedAt);
  openingMediaDescriptors(dir, "0".repeat(64), rows); // Closed DTO shape proof before commit; the real hash is minted below.
  const selectionHash = writeGuidedObject(dir, fact); saveHumanCutJobSnapshot(dir, verified.observed);
  createHumanCutIndex(path.join(path.dirname(verified.receipt.path), "selection.json"), { ...fact, selectionHash });
  const job = verified.observed.job;
  commitGuidedJob({ beforeHash: verified.observed.sha256, guard: () => { check(); assertOpeningRecord(verified.receipt);
    retainGenerationClockObservation({ dir, origin: { clockHash: held.claim.clockHash, startedAt: held.claim.generationStartedAt },
      executionId: held.claim.executionId, observedAt: new Date().toISOString() }, guard); },
  job: { ...job, updatedAt: selectionQualifiedAt, guidedHandoffV2: { ...job.guidedHandoffV2!, openingMediaSelectionHash: selectionHash },
    message: "Exact private opening media is selected for mechanical review playback. No opening, body or final is approved.",
    nextEventId: job.nextEventId + 1, events: [...job.events, { id: job.nextEventId, at: selectionQualifiedAt,
      payload: { event: "opening_media_selected", executionId: held.claim.executionId, selectionHash, cleanupHash: cleanup.cleanupHash,
        openingApproved: false, deliveryApproved: false } }].slice(-256) } });
  return { selectionHash, fact, mediaSelected: true as const, openingApproved: false as const, deliveryApproved: false as const };
}

/** Explicit version dispatch only; source2 requires an actual same-owner verifier, never a DTO or legacy fallback. */
export function selectVerifiedOpeningMediaUnderLease(input: { dir: string; lease: ProjectMutationLease;
  verified: Verified | VerifiedSourceColorOpening; remainingMs: () => number }) {
  if (input.verified.receipt.value.schemaVersion === 2) return selectSourceColorOpeningMedia(input as Parameters<typeof selectSourceColorOpeningMedia>[0]);
  if (input.verified.receipt.value.schemaVersion !== 1) throw new Error("Opening selection readback version is unsupported");
  return selectLegacyOpeningMedia(input as Parameters<typeof selectLegacyOpeningMedia>[0]);
}

/** Shared exact on-disk fact parser; direct source-color helper calls cannot substitute a caller DTO. */
export function parseOpeningSelectionFact(dir: string, hash: string) {
  const fact = readGuidedObject(dir, hash); exactKeys(fact, FACT_KEYS, FACT_KEYS, "opening media selection"); uuid(fact.executionId, "executionId");
  for (const key of ["claimHash", "inputSha256", "executionInputHash", "cleanupHash", "beforeJournalHash", "readbackStartSha256", "readbackOutputSha256",
    "readbackReceiptSha256", "mediaResultSha256", "receiptHash", "clockHash"]) sha256(fact[key], key);
  if ((fact.schemaVersion !== 1 && fact.schemaVersion !== 2)
      || fact.kind !== "guided-opening-media-selection" || fact.scope !== OPENING_SELECTION_SCOPE
      || fact.openingApproved !== false || fact.deliveryApproved !== false) throw new Error("Opening selection is not mechanical unapproved evidence");
  strictGuidedTimestamp(fact.selectionQualifiedAt); strictGuidedTimestamp(fact.generationStartedAt); openingAbsolutePath(fact.outputRoot);
  return fact;
}

/** Retain the same current or historical cleanup pointer and original claim for either explicit fact version. */
export function assertOpeningSelectionLineage(observed: ReturnType<typeof readCommittedOpeningCleanup> | ReturnType<typeof readHistoricalOpeningCleanup>,
  fact: Record<string, unknown>, hash: string): void {
  const pointer = observed.job.guidedHandoffV2, held = observed.held;
  if (pointer?.openingExecutionClaimHash || pointer?.openingMediaSelectionHash !== hash
      || pointer.openingCleanupHash !== fact.cleanupHash || observed.cleanupHash !== fact.cleanupHash || held.claimHash !== fact.claimHash
      || held.claim.executionId !== fact.executionId || held.claim.outputRoot !== fact.outputRoot || held.claim.clockHash !== fact.clockHash
      || String(fact.selectionQualifiedAt) > observed.job.updatedAt) throw new Error("Opening selection does not bind the current cleanup/claim lineage");
}

/** Cheap current-lineage read for status/media routes. Source bytes are NOT rechecked here (labelled by the status contract). */
function selectionForJournal(dir: string, observed: ReturnType<typeof readCommittedOpeningCleanup> | ReturnType<typeof readHistoricalOpeningCleanup>, guard: () => void) {
  const current = observed, pointer = current.job.guidedHandoffV2;
  if (pointer?.openingExecutionClaimHash) throw new Error("A newer private opening execution owns this project; old selection is not current");
  const hash = pointer?.openingMediaSelectionHash;
  if (!hash) throw new Error("No opening media selection exists");
  const fact = parseOpeningSelectionFact(dir, hash), held = observed.held;
  assertOpeningSelectionLineage(observed, fact, hash);
  if (fact.schemaVersion === 2) return readSourceColorSelection({ dir, observed, selectionHash: hash, fact }, guard);
  const selected = readHeldOpeningResult(held);
  if (selected.record.sha256 !== fact.mediaResultSha256 || selected.completion.receiptHash !== fact.receiptHash) throw new Error("Opening selection names a different held result");
  const readback = path.join(path.dirname(held.claimPath), "readback-attempts", stringValue(fact.readbackDirectory, "readbackDirectory", 64));
  assertOpeningFailureAbsent(path.join(readback, "failure.json"));
  const receipt = readCutPreviewObject(path.join(readback, "verified.json"));
  if (receipt.sha256 !== fact.readbackReceiptSha256 || readCutPreviewObject(path.join(readback, "start.json")).sha256 !== fact.readbackStartSha256
      || readCutPreviewObject(path.join(readback, "output.json")).sha256 !== fact.readbackOutputSha256
      || receipt.value.cleanupHash !== fact.cleanupHash || receipt.value.claimHash !== fact.claimHash) throw new Error("Opening selection readback lineage changed");
  const rows = { core: selectedOpeningRow(selected.record.value, "core", held.claim.outputRoot), review: selectedOpeningRow(selected.record.value, "review", held.claim.outputRoot) };
  if (canonicalJsonSha256(rows) !== canonicalJsonSha256(fact.media)) throw new Error("Opening selection media identities differ from the held result");
  return { selectionHash: hash, fact, held, observed, rows, selectionQualifiedAt: String(fact.selectionQualifiedAt),
    receiptHash: String(fact.receiptHash), receiptSha256: String(fact.mediaResultSha256), sourceFreshness: "not-rechecked-by-status" as const };
}

/** Cheap CURRENT selection; never substitute a retained snapshot for the live journal. */
export function readSelectedOpeningMedia(dir: string, borrowedGuard?: () => void) {
  const started = performance.now(), guard = selectionReadGuard(started, borrowedGuard);
  const current = observeHumanCutJob(dir);
  if (current.job.guidedHandoffV2?.openingExecutionClaimHash) throw new Error("A newer private opening execution owns this project; old selection is not current");
  if (!current.job.guidedHandoffV2?.openingMediaSelectionHash) throw new Error("No opening media selection exists");
  const observed = readCommittedOpeningCleanup(dir);
  if (observed.sha256 !== current.sha256) throw new Error("Opening selection changed before cleanup observation");
  const result = selectionForJournal(dir, observed, guard), sourceColor = result.fact.schemaVersion === 2;
  if (observeHumanCutJob(dir).sha256 !== current.sha256) throw new Error("Opening selection changed during observation");
  if (sourceColor) { assertSourceColorSelectionReadMetadata(result); assertSelectionReadTime(started); }
  return result;
}

/** Historical selection for an already-proved body edge only; neither current selection nor source verification. */
export function readHistoricalOpeningSelection(dir: string, journalHash: string, borrowedGuard?: () => void) {
  const started = performance.now(), guard = selectionReadGuard(started, borrowedGuard);
  const observed = readHistoricalOpeningCleanup(dir, journalHash), result = selectionForJournal(dir, observed, guard), sourceColor = result.fact.schemaVersion === 2;
  const file = path.join(dir, "human-cut-job-snapshots", `${sha256(journalHash, "historical selection journal")}.json`);
  if (readCutPreviewObject(file).sha256 !== journalHash) throw new Error("Historical opening selection snapshot changed");
  if (sourceColor) {
    const historical = historicalSourceColorSelection(result); assertSelectionReadTime(started); return historical;
  }
  return { ...result, observationScope: "held-historical-selection-not-current-or-source-requalified" as const };
}

/** Actual source2 handles only, including historical wrappers; never infer proof from a mutable schema discriminator. */
export function assertOpeningSelectionMetadata(value: object): void {
  if (isCommittedSourceColorSelection(value)) { assertCommittedSourceColorSelectionMetadata(value); return; }
  assertSourceColorSelectionReadMetadata(value);
}

/** Preserve known source2 identity across dispatch; a mutable version cannot request a legacy fallback. */
export function openingSelectionVersion(value: { fact: Record<string, unknown> }): 1 | 2 {
  const version = value.fact.schemaVersion;
  if (version !== 1 && version !== 2) throw new Error("Opening selection version is unsupported");
  if (isCommittedSourceColorSelection(value) || isSourceColorSelectionRead(value) || version === 2) {
    assertOpeningSelectionMetadata(value); return 2;
  }
  return 1;
}
