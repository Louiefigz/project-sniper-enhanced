/** Separate schema2 completion/receipt binding, NOT a public readback or selection route.
 * Caller guards own the original journal/lease/deadline. Only finite metadata is
 * opened here; source/media/evidence bytes, tools and Docker remain unobserved.
 */
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { objectValue } from "@/lib/producer/contracts/validation";
import { openingAbsolutePath } from "@/lib/producer/contracts/guided-opening-media-v1";
import { parseSourceColorOpeningCompletion, parseSourceColorOpeningReadback,
  type GuidedOpeningMediaCompletionV2 } from "@/lib/producer/contracts/guided-opening-result-v2";
import { observeCutPreviewFile, readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { readStoppedOpeningProcess, type HeldOpeningClaim } from "./guided-opening-process";
import { assertOpeningFailureAbsent } from "./guided-opening-process-activation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";
import { fileIdentity, directoryIdentity } from "./guided-source-color-cleanup-attempt-hold";
import { captureSourceColorCleanupMedia, cleanupMediaReference, assertCleanupMediaReturn,
  type CleanupMediaReference, type CleanupMediaRole } from "./guided-source-color-cleanup-attempt-media";

export interface SourceColorOpeningResultContext { held: HeldOpeningClaim; guard: () => void }
export interface HeldSourceColorOpeningResult {
  readonly process: ReturnType<typeof readStoppedOpeningProcess>;
  readonly completion: GuidedOpeningMediaCompletionV2;
  readonly record: ReturnType<typeof readCutPreviewObject>;
  readonly observationScope: "actual-source-color-completion-and-receipt-bytes-only";
  readonly sourceBytesObserved: false; readonly mediaBytesObserved: false; readonly mediaSelected: false;
}
const originalResults = new WeakMap<HeldSourceColorOpeningResult, ResultRead>();

function same(actual: unknown, expected: unknown): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error("Source-color opening result original metadata or bytes changed");
}

/** Private finite state never escapes through the returned result or a caller-controlled inventory. */
class ResultRead {
  readonly original;
  private readonly fixed;
  private readonly files = new Map<string, bigint[]>();
  private readonly parents = new Map<string, bigint[]>();
  private readonly media = new Map<CleanupMediaRole, CleanupMediaReference>();
  private readonly returns: Array<{ value: unknown; fixed: unknown }> = [];
  private busy = false;
  readonly resultPath;
  constructor(readonly input: SourceColorOpeningResultContext) {
    this.original = { held: input.held, guard: input.guard };
    this.fixed = snapshotSourceColorMetadata(input.held);
    this.resultPath = path.join(openingAbsolutePath(input.held.claim.outputRoot), "media-result.json");
    for (const file of [input.held.claimPath, input.held.claim.inputPath, this.resultPath]) this.capture(file);
    this.captureParents(path.join(input.held.claim.outputRoot, "audio"));
    captureSourceColorCleanupMedia(input.held, this.captureMedia);
    this.metadata();
  }
  private capture(file: string): void {
    openingAbsolutePath(file); this.files.set(file, fileIdentity(file));
    this.captureParents(path.dirname(file));
  }
  private captureParents(start: string): void {
    for (let directory = start;;) {
      const identity = directoryIdentity(directory), prior = this.parents.get(directory);
      if (prior) same(identity, prior);
      this.parents.set(directory, identity);
      const next = path.dirname(directory); if (next === directory) return;
      directory = next;
    }
  }
  private captureMedia = (reference: CleanupMediaReference): Buffer => {
    const ref = snapshotSourceColorMetadata(reference), maximum = cleanupMediaReference(ref, this.original.held);
    if (this.media.has(ref.role)) throw new Error("Source-color result original media role repeats");
    this.capture(ref.path); this.metadata();
    const raw = observeCutPreviewFile(ref.path, maximum, true, this.metadata);
    if (raw.sha256 !== ref.sha256) throw new Error("Source-color result original media reference differs");
    this.media.set(ref.role, ref); this.metadata(); return raw.bytes;
  };
  retain<T>(value: T): T {
    this.returns.push({ value, fixed: snapshotSourceColorMetadata(value) }); return value;
  }
  private unchanged(): void {
    if (this.input.held !== this.original.held || this.input.guard !== this.original.guard) {
      throw new Error("Source-color result lost its original caller identity");
    }
    same(this.input.held, this.fixed);
    for (const row of this.returns) same(row.value, row.fixed);
  }
  metadata = (): void => {
    this.unchanged();
    for (const [directory, identity] of this.parents) same(directoryIdentity(directory), identity);
    for (const [file, identity] of this.files) same(fileIdentity(file), identity);
    assertOpeningFailureAbsent(path.join(this.original.held.claim.outputRoot, "media-failed.json"));
    assertOpeningFailureAbsent(path.join(this.original.held.claim.outputRoot, "audio/audio-failed.json"));
    this.unchanged();
  };
  check(): void {
    if (this.busy) throw new Error("Source-color result guard reentered its original read");
    this.busy = true;
    try { this.metadata(); this.original.guard(); this.metadata(); }
    finally { this.busy = false; }
  }
  stopped(): ReturnType<typeof readStoppedOpeningProcess> {
    this.metadata();
    const process = readStoppedOpeningProcess(this.original.held);
    if (process.receipt.schemaVersion !== 3 || !process.sourceColor || process.receipt.status !== "complete"
        || process.nestedOwnership !== "resolved-by-normal-return") {
      throw new Error("Source-color result requires its complete resolved actual V3 process");
    }
    assertCleanupMediaReturn(this.media, process); this.metadata(); return process;
  }
  opening(): void {
    const { held } = this.original;
    const claim = readCutPreviewObject(held.claimPath), input = readCutPreviewObject(held.claim.inputPath);
    if (claim.sha256 !== held.claimSha256 || input.sha256 !== held.claim.inputSha256) {
      throw new Error("Source-color result original claim or input raw bytes differ");
    }
    same(claim.value, held.claim);
    if (input.value.executionId !== held.claim.executionId || input.value.executionInputHash !== held.claim.executionInputHash) {
      throw new Error("Source-color result original input execution differs");
    }
    this.metadata();
  }
}

function completionIdentity(value: GuidedOpeningMediaCompletionV2, held: HeldOpeningClaim): void {
  if (value.executionId !== held.claim.executionId || value.inputSha256 !== held.claim.inputSha256
      || value.executionInputHash !== held.claim.executionInputHash || value.executionClaimSha256 !== held.claimSha256
      || value.receiptPath !== path.join(held.claim.outputRoot, "media-result.json")) {
    throw new Error("Source-color completion does not bind its original held execution");
  }
}

function receiptIdentity(record: ReturnType<typeof readCutPreviewObject>, completion: GuidedOpeningMediaCompletionV2,
  held: HeldOpeningClaim): void {
  const row = objectValue(record.value, "source-color media result"), { receiptHash, ...body } = row;
  if (record.sha256 !== completion.receiptSha256 || receiptHash !== completion.receiptHash
      || canonicalJsonSha256(body) !== receiptHash || row.schemaVersion !== 2 || row.kind !== "guided-opening-media-result"
      || row.status !== "complete" || row.scope !== "private-opening-media-not-opening-body-or-delivery-approval"
      || row.executionId !== held.claim.executionId || row.inputPath !== held.claim.inputPath
      || row.inputSha256 !== held.claim.inputSha256 || row.executionInputHash !== held.claim.executionInputHash
      || row.openingApproved !== false || row.deliveryApproved !== false) {
    throw new Error("Source-color result schema, bytes or original execution identity differs");
  }
  same(row.executionClaim, { path: held.claimPath, sha256: held.claimSha256 });
  same(row.sourceColorEvidence, completion.sourceColorEvidence);
}

/** Read only actual V3 completion and schema2 receipt bytes; no cold evidence replay or selection is performed. */
export function readHeldSourceColorOpeningResult(input: SourceColorOpeningResultContext): HeldSourceColorOpeningResult {
  const read = new ResultRead(input); read.opening();
  const process = read.retain(read.stopped());
  const completion = read.retain(parseSourceColorOpeningCompletion(String(process.receipt.stdout)));
  completionIdentity(completion, input.held);
  const record = read.retain(readCutPreviewObject(read.resultPath));
  receiptIdentity(record, completion, input.held);
  const selected = Object.freeze({ process, completion, record,
    observationScope: "actual-source-color-completion-and-receipt-bytes-only" as const,
    sourceBytesObserved: false as const, mediaBytesObserved: false as const, mediaSelected: false as const });
  read.retain(selected); read.check(); originalResults.set(selected, read); return selected;
}

function actual(selected: HeldSourceColorOpeningResult, held?: HeldOpeningClaim): ResultRead {
  const read = originalResults.get(selected);
  if (!read || (held !== undefined && read.original.held !== held)) throw new Error("Source-color result requires its actual original metadata hold");
  read.metadata(); return read;
}

/** Callback-free finite original metadata only; the enclosing owner separately checks its original time/lease. */
export function assertSourceColorOpeningResultMetadata(selected: HeldSourceColorOpeningResult, held?: HeldOpeningClaim): void {
  actual(selected, held).metadata();
}

/** Re-read the original stopped process and receipt; never discover another output or refresh the captured baseline. */
export function assertHeldSourceColorOpeningResultUnchanged(held: HeldOpeningClaim, selected: HeldSourceColorOpeningResult): void {
  const read = actual(selected, held); read.check();
  same(read.stopped(), selected.process); same(readCutPreviewObject(read.resultPath), selected.record);
  read.check();
}

/** Receipt argv is data for the separately owned schema2 child, not launch or cleanup authority. */
export function sourceColorOpeningReadbackReceiptArguments(selected: HeldSourceColorOpeningResult): string[] {
  actual(selected);
  return ["--receipt-sha256", selected.completion.receiptSha256, "--receipt-hash", selected.completion.receiptHash];
}

/** Bind just-returned schema2 child stdout to BOTH original completion and raw result evidence refs. */
export function assertSourceColorOpeningReadbackIdentity(stdout: string,
  input: { held: HeldOpeningClaim; selected: HeldSourceColorOpeningResult }) {
  const { held, selected } = input; const read = actual(selected, held);
  const value = parseSourceColorOpeningReadback(stdout);
  if (value.executionId !== held.claim.executionId || value.inputSha256 !== held.claim.inputSha256
      || value.executionInputHash !== held.claim.executionInputHash || value.claimSha256 !== held.claimSha256
      || value.receiptPath !== selected.completion.receiptPath || value.receiptSha256 !== selected.completion.receiptSha256
      || value.receiptHash !== selected.completion.receiptHash) throw new Error("Source-color readback differs from its actual original completion");
  same(value.sourceColorEvidence, selected.completion.sourceColorEvidence);
  same(value.sourceColorEvidence, selected.record.value.sourceColorEvidence);
  read.metadata(); return value;
}
