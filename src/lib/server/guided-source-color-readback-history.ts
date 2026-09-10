/** Retained schema2 records only: no current-media/source verification, selection, lease or execution authority. */
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { exactKeys, objectValue, sha256, uuid } from "@/lib/producer/contracts/validation";
import { openingAbsolutePath } from "@/lib/producer/contracts/guided-opening-media-v1";
import { parseBoundedJson } from "@/lib/producer/contracts/bounded-json";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { strictGuidedTimestamp } from "./guided-cut-v2-store";
import { assertOpeningCleanupMetadata, type readCommittedOpeningCleanup, type readHistoricalOpeningCleanup } from "./guided-opening-cleanup-store";
import { assertSourceColorOpeningResultMetadata, assertSourceColorOpeningReadbackIdentity,
  type HeldSourceColorOpeningResult } from "./guided-source-color-opening-result";
import { sourceColorOpeningReadTools } from "./guided-source-color-read-transport";
import { assertOpeningFailureAbsent } from "./guided-opening-process-activation";
import { fileIdentity, directoryIdentity } from "./guided-source-color-cleanup-attempt-hold";
import { snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";

/** Projection of already-selected or prospective fact fields, not an independent selection-fact parser. */
export interface SourceColorReadbackHistoryReference {
  schemaVersion: 2; beforeJournalHash: string; cleanupHash: string; claimHash: string; executionId: string;
  inputSha256: string; executionInputHash: string; outputRoot: string; readbackDirectory: string;
  readbackStartSha256: string; readbackOutputSha256: string; readbackReceiptSha256: string;
  mediaResultSha256: string; receiptHash: string; clockHash: string; generationStartedAt: string; selectionQualifiedAt: string;
}
export interface SourceColorReadbackHistoryInput {
  cleanup: ReturnType<typeof readCommittedOpeningCleanup> | ReturnType<typeof readHistoricalOpeningCleanup>;
  selected: HeldSourceColorOpeningResult; reference: SourceColorReadbackHistoryReference; guard: () => void;
}
export interface HeldSourceColorReadbackHistory {
  readonly kind: "held-source-color-readback-history";
  readonly observationScope: "retained-schema2-records-not-current-media-source-selection-or-approval";
  readonly mediaSelected: false; readonly openingApproved: false; readonly deliveryApproved: false;
}
const HASH_FIELDS = ["beforeJournalHash", "cleanupHash", "claimHash", "inputSha256", "executionInputHash", "readbackStartSha256",
  "readbackOutputSha256", "readbackReceiptSha256", "mediaResultSha256", "receiptHash", "clockHash"] as const;
const REFERENCE_KEYS = ["schemaVersion", ...HASH_FIELDS, "executionId", "outputRoot", "readbackDirectory", "generationStartedAt", "selectionQualifiedAt"];
const LIMITS = { start: 128 * 1024, output: 4 * 1024 * 1024, verified: 128 * 1024 };
type Role = keyof typeof LIMITS;
const history = new WeakMap<HeldSourceColorReadbackHistory, () => void>();
const active = new WeakSet<SourceColorReadbackHistoryInput>();

function same(actual: unknown, expected: unknown, label: string): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error(`Source-color readback history original ${label} differs`);
}

function reference(value: SourceColorReadbackHistoryReference): void {
  exactKeys(objectValue(value, "source-color readback history reference"), REFERENCE_KEYS, REFERENCE_KEYS, "source-color readback history reference");
  if (value.schemaVersion !== 2) throw new Error("Source-color readback history requires its explicit schema2 reference");
  for (const key of HASH_FIELDS) sha256(value[key], key);
  uuid(value.executionId, "readback execution"); openingAbsolutePath(value.outputRoot);
  const id = uuid(value.readbackDirectory, "readback directory");
  if (id[14] !== "4") throw new Error("Source-color readback history requires its exact UUID4 attempt");
  strictGuidedTimestamp(value.generationStartedAt); strictGuidedTimestamp(value.selectionQualifiedAt);
}

/** Authenticate actual parent handles before any new file read; their original callbacks are never invoked. */
function parentBinding(input: SourceColorReadbackHistoryInput) {
  const { cleanup: c, selected: s, reference: r } = input, held = c.held;
  assertOpeningCleanupMetadata(c); assertSourceColorOpeningResultMetadata(s, held);
  if (!("pending" in c) || c.receipt.phase !== "retired" || c.receipt.claimRetained !== false
      || s.process.receipt.schemaVersion !== 3 || s.process.receipt.status !== "complete" || !s.process.sourceColor
      || s.process.nestedOwnership !== "resolved-by-normal-return" || s.process.receipt.forcedStop !== false) {
    throw new Error("Source-color history requires actual final cleanup and complete same-held source result");
  }
  same(s.process, c.evidence.stop, "stopped process");
  same([r.beforeJournalHash, r.cleanupHash, r.claimHash, r.executionId, r.inputSha256, r.executionInputHash, r.outputRoot,
    r.mediaResultSha256, r.receiptHash, r.clockHash, r.generationStartedAt],
  [c.sha256, c.cleanupHash, held.claimHash, held.claim.executionId, held.claim.inputSha256, held.claim.executionInputHash,
    held.claim.outputRoot, s.record.sha256, s.completion.receiptHash, held.claim.clockHash, held.claim.generationStartedAt], "selection reference");
  same(s.process.sourceColor.reservation, c.pending.fact.reservation, "reservation");
  same(s.process.sourceColor.sourceColorHash, c.pending.fact.sourceColorHash, "source request");
  same([c.pending.fact.archive.sha256, c.pending.fact.archive.sizeBytes],
    [c.pending.fact.reservation.sha256, c.pending.fact.reservation.sizeBytes], "original archived bytes");
  return snapshotSourceColorMetadata({ sourceColor: s.process.sourceColor, archive: c.pending.fact.archive,
    sourceColorEvidence: s.completion.sourceColorEvidence });
}

/** Private state holds every file and ancestor before the first arbitrary caller guard. */
class HistoryRead {
  readonly original;
  readonly fixed;
  readonly directory;
  readonly binding;
  private readonly files = new Map<string, bigint[]>();
  private readonly parents = new Map<string, bigint[]>();
  private busy = false;
  constructor(readonly input: SourceColorReadbackHistoryInput) {
    this.original = { ...input }; this.fixed = snapshotSourceColorMetadata(input.reference);
    reference(input.reference);
    if (typeof input.guard !== "function") throw new Error("Source-color history requires the original caller guard");
    this.binding = parentBinding(input);
    this.directory = path.join(path.dirname(input.cleanup.held.claimPath), "readback-attempts", input.reference.readbackDirectory);
    for (const role of Object.keys(LIMITS) as Role[]) this.capture(role);
    this.metadata();
  }
  private capture(role: Role): void {
    const file = path.join(this.directory, `${role}.json`), identity = fileIdentity(file);
    if (identity[5] < BigInt(1) || identity[5] > BigInt(LIMITS[role])) throw new Error("Source-color readback record exceeds its byte bound");
    this.files.set(file, identity);
    for (let directory = path.dirname(file); !this.parents.has(directory); directory = path.dirname(directory)) {
      this.parents.set(directory, directoryIdentity(directory));
    }
  }
  private unchanged(): void {
    const i = this.input, o = this.original;
    if (i.cleanup !== o.cleanup || i.selected !== o.selected || i.reference !== o.reference || i.guard !== o.guard) {
      throw new Error("Source-color readback history original caller identity changed");
    }
    same(i.reference, this.fixed, "reference metadata");
  }
  metadata = (): void => {
    this.unchanged();
    assertOpeningCleanupMetadata(this.original.cleanup);
    assertSourceColorOpeningResultMetadata(this.original.selected, this.original.cleanup.held);
    for (const [directory, identity] of this.parents) same(directoryIdentity(directory), identity, "parent identity");
    for (const [file, identity] of this.files) same(fileIdentity(file), identity, "file identity");
    assertOpeningFailureAbsent(path.join(this.directory, "failure.json")); this.unchanged();
  };
  check = (): void => {
    if (this.busy) throw new Error("Source-color history guard reentered its original read");
    this.busy = true;
    try { this.metadata(); this.original.guard(); this.metadata(); }
    finally { this.busy = false; }
  };
  read(role: Role): Record<string, unknown> {
    const keys = { start: "readbackStartSha256", output: "readbackOutputSha256", verified: "readbackReceiptSha256" } as const;
    const raw = observeCutPreviewFile(path.join(this.directory, `${role}.json`), LIMITS[role], true, this.check);
    const text = new TextDecoder("utf-8", { fatal: true }).decode(raw.bytes);
    const value = objectValue(role === "output" ? JSON.parse(text) : parseBoundedJson(text, `Source-color ${role}`), `readback ${role}`);
    if (raw.sha256 !== this.fixed[keys[role]] || canonicalJsonSha256(value) !== raw.sha256) {
      throw new Error("Source-color readback original raw record differs from its canonical publication");
    }
    this.check(); return value;
  }
}

function startRecord(read: HistoryRead, start: Record<string, unknown>): void {
  const { cleanup, selected } = read.original, r = read.fixed;
  read.check(); const tools = sourceColorOpeningReadTools(cleanup.held, selected); read.check();
  same(start, { schemaVersion: 2, kind: "guided-opening-readback-start", beforeJournalHash: r.beforeJournalHash,
    cleanupHash: r.cleanupHash, claimHash: r.claimHash, executionId: r.executionId, receiptSha256: r.mediaResultSha256,
    tools, ...read.binding, clockHash: r.clockHash, generationStartedAt: r.generationStartedAt, startedAt: start.startedAt }, "start record");
  if (strictGuidedTimestamp(start.startedAt) < cleanup.job.updatedAt) throw new Error("Source-color readback predates its held journal");
}

function outputRecord(read: HistoryRead, output: Record<string, unknown>) {
  const keys = ["schemaVersion", "kind", "startSha256", "stdout", "stderr", "processGroupStopped", "observedAt", "elapsedMs"];
  exactKeys(output, keys, keys, "source-color readback output");
  if (output.schemaVersion !== 2 || output.kind !== "guided-opening-readback-owned-output" || output.processGroupStopped !== true
      || output.startSha256 !== read.fixed.readbackStartSha256 || typeof output.stdout !== "string" || typeof output.stderr !== "string"
      || Buffer.byteLength(output.stdout) > 2 * 1024 * 1024 || Buffer.byteLength(output.stderr) > 2 * 1024 * 1024
      || typeof output.elapsedMs !== "number" || !Number.isFinite(output.elapsedMs) || output.elapsedMs < 0 || output.elapsedMs > 1_500_000) {
    throw new Error("Source-color readback output version, bounded timing or owned return differs");
  }
  const result = assertSourceColorOpeningReadbackIdentity(output.stdout, { held: read.original.cleanup.held, selected: read.original.selected });
  if (result.elapsedMs > output.elapsedMs + 1) throw new Error("Source-color readback child time exceeds its actual owned duration");
  return result;
}

function verifiedRecord(read: HistoryRead, records: Record<Role, Record<string, unknown>>): void {
  startRecord(read, records.start); const result = outputRecord(read, records.output), r = read.fixed, value = records.verified;
  same(value, { schemaVersion: 2, kind: "guided-opening-owned-readback", scope: "actual-current-readback-not-selected-or-approved",
    beforeJournalHash: r.beforeJournalHash, cleanupHash: r.cleanupHash, claimHash: r.claimHash, startSha256: r.readbackStartSha256,
    outputSha256: r.readbackOutputSha256, result, ...read.binding, clockHash: r.clockHash, generationStartedAt: r.generationStartedAt,
    createdAt: value.createdAt, mediaSelected: false, openingApproved: false, deliveryApproved: false }, "verified record");
  const stamps = [r.generationStartedAt, records.start.startedAt, records.output.observedAt, value.createdAt, r.selectionQualifiedAt].map(strictGuidedTimestamp);
  if (stamps.some((stamp, index) => index > 0 && stamp < stamps[index - 1])) throw new Error("Source-color readback historical timestamps moved backwards");
}

/** Read under the caller's existing guard. No old proof callbacks, new clock or public selection is created. */
export function readSourceColorReadbackHistory(input: SourceColorReadbackHistoryInput): HeldSourceColorReadbackHistory {
  exactKeys(objectValue(input, "source-color history input"), ["cleanup", "selected", "reference", "guard"],
    ["cleanup", "selected", "reference", "guard"], "source-color history input");
  if (active.has(input)) throw new Error("Source-color history cannot recursively reenter the same input");
  active.add(input);
  try {
    const read = new HistoryRead(input); read.check();
    const records = { start: read.read("start"), output: read.read("output"), verified: read.read("verified") };
    verifiedRecord(read, records); read.check();
    const value = Object.freeze({ kind: "held-source-color-readback-history" as const,
      observationScope: "retained-schema2-records-not-current-media-source-selection-or-approval" as const,
      mediaSelected: false as const, openingApproved: false as const, deliveryApproved: false as const });
    read.metadata(); history.set(value, read.metadata); return value;
  } finally { active.delete(input); }
}

/** Callback-free finite original metadata only; copied records or handles cannot inherit this proof. */
export function assertSourceColorReadbackHistoryMetadata(value: HeldSourceColorReadbackHistory): void {
  const check = history.get(value);
  if (!check) throw new Error("Source-color history requires its actual original metadata handle");
  check();
}
