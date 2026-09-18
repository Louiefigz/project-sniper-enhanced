/** Retained schema2 selection only. No current source qualification, human approval or execution authority. */
import path from "node:path";
import { lstatSync, realpathSync } from "node:fs";
import { isDeepStrictEqual } from "node:util";
import { sha256 } from "@/lib/producer/contracts/validation";
import { assertOpeningCleanupMetadata, readHistoricalOpeningCleanup, type readCommittedOpeningCleanup } from "./guided-opening-cleanup-store";
import { readHeldSourceColorOpeningResult, assertSourceColorOpeningResultMetadata } from "./guided-source-color-opening-result";
import { readSourceColorReadbackHistory, assertSourceColorReadbackHistoryMetadata,
  type SourceColorReadbackHistoryReference } from "./guided-source-color-readback-history";
import { capturePublication, assertPublication } from "./guided-source-color-cleanup-pending-commit";
import { directoryIdentity } from "./guided-source-color-cleanup-attempt-hold";
import { snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";
import { selectedOpeningRow, parseOpeningSelectionFact, assertOpeningSelectionLineage,
  type SelectedOpeningRow, type OpeningRange } from "./guided-opening-selection";

type Cleanup = ReturnType<typeof readCommittedOpeningCleanup> | ReturnType<typeof readHistoricalOpeningCleanup>;
export interface SourceColorSelectionReadInput { dir: string; observed: Cleanup; selectionHash: string; fact: Record<string, unknown> }
const reads = new WeakMap<object, () => void>();

/** Private identity membership only; a changed discriminator cannot turn an actual source2 read into legacy evidence. */
export function isSourceColorSelectionRead(value: object): boolean { return reads.has(value); }

function same(actual: unknown, expected: unknown): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error("Source-color selection original metadata changed");
}

/** The public reader creates this once before journal IO; nested helpers borrow it without resetting the allowance. */
export function selectionReadGuard(started: number, borrowed?: () => void): () => void {
  return () => {
    borrowed?.(); assertSelectionReadTime(started);
  };
}

/** Pure same-entry time check after the final callback-free metadata sweep. */
export function assertSelectionReadTime(started: number): void {
  const elapsed = performance.now() - started;
  if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed >= 30_000) throw new Error("Source-color selection original read allowance expired");
}

/** Preserve original private media inode/ancestry; this does not decode or hash media payloads. */
function mediaIdentity(file: string): bigint[] {
  const row = lstatSync(file, { bigint: true });
  if (!row.isFile() || row.nlink !== BigInt(1) || row.uid !== BigInt(process.getuid!())
      || (row.mode & BigInt(0o022)) !== BigInt(0) || realpathSync(file) !== file) {
    throw new Error("Source-color selected media must remain canonical owned single-link regular files without foreign write access");
  }
  return [row.dev, row.ino, row.mode, row.uid, row.nlink, row.size, row.mtimeNs, row.ctimeNs];
}

/** Readable 0644 FFmpeg output is allowed inside the held private root; mode changes still invalidate the hold. */
export function holdSelectionMedia(rows: Record<OpeningRange, SelectedOpeningRow>): () => void {
  const files = Object.values(rows).map(row => ({ row, fixed: snapshotSourceColorMetadata(row), identity: mediaIdentity(row.path) }));
  const parents = new Map<string, bigint[]>();
  for (const { row, identity } of files) {
    if (identity[5] !== BigInt(row.sizeBytes)) throw new Error("Source-color selected media size differs");
    for (let directory = path.dirname(row.path); !parents.has(directory); directory = path.dirname(directory)) {
      parents.set(directory, directoryIdentity(directory));
    }
  }
  return () => {
    for (const [directory, state] of parents) same(directoryIdentity(directory), state);
    for (const { row, fixed, identity } of files) { same(row, fixed); same(mediaIdentity(row.path), identity); }
  };
}

/** Only the existing closed selection fact is projected; no alternate receipt schema is invented. */
export function sourceColorSelectionReference(fact: Record<string, unknown>): SourceColorReadbackHistoryReference {
  const { schemaVersion, beforeJournalHash, cleanupHash, claimHash, executionId, inputSha256, executionInputHash,
    outputRoot, readbackDirectory, readbackStartSha256, readbackOutputSha256, readbackReceiptSha256,
    mediaResultSha256, receiptHash, clockHash, generationStartedAt, selectionQualifiedAt } = fact;
  return { schemaVersion, beforeJournalHash, cleanupHash, claimHash, executionId, inputSha256, executionInputHash,
    outputRoot, readbackDirectory, readbackStartSha256, readbackOutputSha256, readbackReceiptSha256,
    mediaResultSha256, receiptHash, clockHash, generationStartedAt, selectionQualifiedAt } as SourceColorReadbackHistoryReference;
}

/** The original fact/current parent is held before the historical reader's first borrowed callback. */
function context(input: SourceColorSelectionReadInput) {
  const original = { ...input }, fixed = snapshotSourceColorMetadata(input.fact);
  assertOpeningCleanupMetadata(original.observed);
  sha256(original.selectionHash, "source-color selection hash");
  if (original.dir !== original.observed.job.ctx.dir) throw new Error("Source-color selection original directory differs");
  const publication = capturePublication(path.join(original.dir, ".sniper-authority-v1/objects/receipts", `${original.selectionHash}.json`), original.selectionHash);
  same(original.fact, parseOpeningSelectionFact(original.dir, original.selectionHash));
  if (original.fact.schemaVersion !== 2) throw new Error("Source-color selection original fact role differs");
  assertOpeningSelectionLineage(original.observed, original.fact, original.selectionHash);
  const metadata = () => {
    same([input.dir, input.observed, input.selectionHash, input.fact], [original.dir, original.observed, original.selectionHash, original.fact]);
    if (input.observed !== original.observed || input.fact !== original.fact) throw new Error("Source-color selection caller identity changed");
    same(input.fact, fixed); assertOpeningCleanupMetadata(original.observed); assertPublication(publication);
  };
  metadata(); return { original, metadata };
}

/** Genuine final cleanup at beforeJournalHash is mandatory, even when the current journal already contains selection. */
export function readSourceColorSelection(input: SourceColorSelectionReadInput, guard: () => void) {
  const held = context(input), { dir, observed, selectionHash, fact } = held.original;
  const before = readHistoricalOpeningCleanup(dir, String(fact.beforeJournalHash)); held.metadata();
  const selected = readHeldSourceColorOpeningResult({ held: before.held, guard: held.metadata });
  const rows = { core: selectedOpeningRow(selected.record.value, "core", before.held.claim.outputRoot),
    review: selectedOpeningRow(selected.record.value, "review", before.held.claim.outputRoot) };
  same(rows, fact.media); const media = holdSelectionMedia(rows);
  const metadata = () => { held.metadata(); assertOpeningCleanupMetadata(before); assertSourceColorOpeningResultMetadata(selected, before.held); media(); };
  const check = () => { metadata(); guard(); metadata(); };
  const history = readSourceColorReadbackHistory({ cleanup: before, selected, reference: sourceColorSelectionReference(fact), guard: check });
  const result = Object.freeze({ selectionHash, fact, held: before.held, observed, rows,
    selectionQualifiedAt: String(fact.selectionQualifiedAt), receiptHash: String(fact.receiptHash),
    receiptSha256: String(fact.mediaResultSha256), sourceFreshness: "not-rechecked-by-status" as const });
  const fixed = snapshotSourceColorMetadata({ fact, rows });
  const finite = () => { same({ fact: result.fact, rows: result.rows }, fixed); metadata(); assertSourceColorReadbackHistoryMetadata(history); };
  check(); finite(); reads.set(result, finite); return result;
}

/** Exact original handle only; discriminator mutation and copies cannot bypass this dispatcher. */
export function assertSourceColorSelectionReadMetadata(value: object): void {
  const check = reads.get(value);
  if (!check) throw new Error("Source-color selection needs its actual original metadata read");
  check();
}

/** Preserve the private inner read across the existing historical projection without exposing its capability. */
export function historicalSourceColorSelection(value: ReturnType<typeof readSourceColorSelection>) {
  assertSourceColorSelectionReadMetadata(value);
  const result = Object.freeze({ ...value, observationScope: "held-historical-selection-not-current-or-source-requalified" as const });
  const check = () => { assertSourceColorSelectionReadMetadata(value); };
  check(); reads.set(result, check); return result;
}
