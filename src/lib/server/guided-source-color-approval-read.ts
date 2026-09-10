/** Retained explicit schema2 human decision only; no fresh source, body generation or delivery approval. */
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import { exactKeys, objectValue, sha256, uuid } from "@/lib/producer/contracts/validation";
import { openingAbsolutePath } from "@/lib/producer/contracts/guided-opening-media-v1";
import { GUIDED_OPENING_APPROVAL_SCOPE, parseGuidedOpeningApprovalSubmission } from "@/lib/producer/contracts/guided-opening-approval-v1";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { assertOpeningSelectionMetadata, type readSelectedOpeningMedia, type readHistoricalOpeningSelection } from "./guided-opening-selection";
import { type observeHumanCutJob } from "./human-cut-acceptance-store";
import { parseAutoEditJobRecord } from "./auto-edit-job-persistence";
import { readHistoricalOpeningCleanup, assertOpeningCleanupMetadata } from "./guided-opening-cleanup-store";
import { readHeldSourceColorOpeningResult, assertSourceColorOpeningResultMetadata } from "./guided-source-color-opening-result";
import { readSourceColorReadbackHistory, assertSourceColorReadbackHistoryMetadata } from "./guided-source-color-readback-history";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { strictGuidedTimestamp } from "./guided-cut-v2-store";
import { OPENING_APPROVAL_MESSAGE } from "./guided-opening-approval";
import { fileIdentity, directoryIdentity } from "./guided-source-color-cleanup-attempt-hold";
import { assertOpeningFailureAbsent } from "./guided-opening-process-activation";
import { snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";

type Selected = ReturnType<typeof readSelectedOpeningMedia> | ReturnType<typeof readHistoricalOpeningSelection>;
export interface SourceColorOpeningApprovalInput { dir: string; current: ReturnType<typeof observeHumanCutJob>; selected: Selected; guard: () => void }
const FACT_KEYS = ["schemaVersion", "kind", "scope", "actor", "decision", "decisionHash", "selectionHash", "claimHash", "executionId",
  "cleanupHash", "mediaResultSha256", "receiptHash", "coreMediaSha256", "reviewMediaSha256", "requalification", "beforeJournalHash",
  "clockHash", "generationStartedAt", "approvedAt", "openingApproved", "bodyGenerated", "deliveryApproved"];
const ROW_KEYS = ["readbackReceiptSha256", "readbackOutputSha256", "readbackDirectory", "elapsedMs"];
const bounds = { start: 128 * 1024, output: 4 * 1024 * 1024, verified: 128 * 1024, approval: 128 * 1024 };
const approvals = new WeakMap<object, () => void>(), active = new WeakSet<object>();

function same(actual: unknown, expected: unknown, label: string): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error(`Source-color approval original ${label} changed`);
}

function journal(value: SourceColorOpeningApprovalInput["current"]) {
  return { sha256: value.sha256, sizeBytes: value.sizeBytes, job: value.job, bytes: value.bytes, value: value.value };
}

/** State never escapes: every original caller, parsed value, raw Buffer, file and ancestor survives later callbacks. */
class ApprovalRead {
  readonly original;
  readonly originalJob;
  readonly originalBytes;
  readonly fixed;
  readonly hash;
  readonly factRecord;
  readonly fact;
  readonly row;
  readonly root;
  readonly beforePath;
  private readonly files = new Map<string, bigint[]>();
  private readonly parents = new Map<string, bigint[]>();
  private readonly returned: Array<{ value: unknown; fixed: unknown }> = [];
  private busy = false;
  constructor(readonly input: SourceColorOpeningApprovalInput) {
    exactKeys(objectValue(input, "source-color approval input"), ["dir", "current", "selected", "guard"], ["dir", "current", "selected", "guard"], "source-color approval input");
    this.original = { ...input }; this.originalJob = input.current.job; this.originalBytes = input.current.bytes;
    this.fixed = snapshotSourceColorMetadata(journal(input.current));
    if (typeof input.guard !== "function") throw new Error("Source-color approval requires its original caller guard");
    openingAbsolutePath(input.dir); assertOpeningSelectionMetadata(input.selected);
    if (input.selected.fact.schemaVersion !== 2 || input.dir !== input.selected.observed.job.ctx.dir) throw new Error("Source-color approval needs its actual schema2 selection");
    same(journal(input.current), journal(input.selected.observed), "selected journal");
    this.hash = sha256(input.current.job.guidedHandoffV2?.openingApprovalHash, "source-color approval hash");
    const file = path.join(input.dir, ".sniper-authority-v1/objects/receipts", `${this.hash}.json`);
    this.capture(file, 128 * 1024); this.factRecord = this.read(file, 128 * 1024); this.fact = this.factRecord.value;
    same(this.factRecord.sha256, this.hash, "approval fact raw SHA");
    validateFact(this.fact, this.hash); this.row = objectValue(this.fact.requalification, "approval requalification");
    this.root = path.join(path.dirname(input.selected.held.claimPath), "readback-attempts", String(this.row.readbackDirectory));
    this.beforePath = path.join(input.dir, "human-cut-job-snapshots", `${this.fact.beforeJournalHash}.json`);
    this.capture(this.beforePath, 16 * 1024 * 1024);
    for (const [role, maximum] of Object.entries(bounds)) this.capture(path.join(this.root, `${role}.json`), maximum);
    this.metadata();
  }
  private capture(file: string, maximum: number): void {
    const identity = fileIdentity(file);
    if (identity[5] <= BigInt(0) || identity[5] > BigInt(maximum)) throw new Error("Source-color approval metadata exceeds its raw byte bound");
    this.files.set(file, identity);
    for (let directory = path.dirname(file); !this.parents.has(directory); directory = path.dirname(directory)) {
      this.parents.set(directory, directoryIdentity(directory));
    }
  }
  retain<T>(value: T): T { this.returned.push({ value, fixed: snapshotSourceColorMetadata(value) }); return value; }
  private unchanged(): void {
    const i = this.input, o = this.original;
    if (i.dir !== o.dir || i.current !== o.current || i.selected !== o.selected || i.guard !== o.guard
        || i.current.job !== this.originalJob || i.current.bytes !== this.originalBytes) throw new Error("Source-color approval original caller identity changed");
    same(journal(i.current), this.fixed, "current journal");
    for (const row of this.returned) same(row.value, row.fixed, "parsed or raw return");
  }
  metadata = (): void => {
    this.unchanged(); assertOpeningSelectionMetadata(this.original.selected);
    for (const [directory, state] of this.parents) same(directoryIdentity(directory), state, "ancestry");
    for (const [file, state] of this.files) same(fileIdentity(file), state, "file identity");
    if (this.root) assertOpeningFailureAbsent(path.join(this.root, "failure.json"));
    this.unchanged();
  };
  check = (): void => {
    if (this.busy) throw new Error("Source-color approval original guard reentered");
    this.busy = true;
    try { this.metadata(); this.original.guard(); this.metadata(); }
    finally { this.busy = false; }
  };
  read(file: string, maximum: number) {
    if (!this.files.has(file)) throw new Error("Source-color approval cannot discover an uncaptured file");
    const raw = observeCutPreviewFile(file, maximum, true, this.metadata);
    const value = objectValue(JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw.bytes)), "source-color approval metadata");
    const result = this.retain({ ...raw, value }); this.metadata(); return result;
  }
}

/** Same existing human decision schema/attestations, with an explicitly versioned retained approval fact. */
function validateFact(fact: Record<string, unknown>, hash: string): void {
  exactKeys(fact, FACT_KEYS, FACT_KEYS, "source-color opening approval");
  for (const key of ["decisionHash", "selectionHash", "claimHash", "cleanupHash", "mediaResultSha256", "receiptHash", "coreMediaSha256",
    "reviewMediaSha256", "beforeJournalHash", "clockHash"]) sha256(fact[key], key);
  uuid(fact.executionId, "approval execution"); strictGuidedTimestamp(fact.approvedAt); strictGuidedTimestamp(fact.generationStartedAt);
  if (fact.schemaVersion !== 2 || fact.kind !== "guided-opening-approval" || fact.scope !== GUIDED_OPENING_APPROVAL_SCOPE
      || fact.actor !== "local-operator" || fact.openingApproved !== true || fact.bodyGenerated !== false || fact.deliveryApproved !== false
      || canonicalJsonSha256(fact) !== hash) throw new Error("Source-color approval fact version, scope or original hash differs");
  const row = objectValue(fact.requalification, "source-color approval requalification"); exactKeys(row, ROW_KEYS, ROW_KEYS, "approval requalification");
  sha256(row.readbackReceiptSha256, "approval verified SHA"); sha256(row.readbackOutputSha256, "approval output SHA");
  if (uuid(row.readbackDirectory, "approval readback directory")[14] !== "4" || typeof row.elapsedMs !== "number"
      || !Number.isFinite(row.elapsedMs) || row.elapsedMs < 0 || row.elapsedMs > 600_000) throw new Error("Source-color approval requalification timing or directory differs");
  const decision = parseGuidedOpeningApprovalSubmission(fact.decision);
  if (canonicalJsonSha256(decision) !== fact.decisionHash) throw new Error("Source-color approval explicit decision hash differs");
}

function decisionBinding(read: ApprovalRead) {
  const fact = read.fact, { selected, current } = read.original, claim = selected.held.claim;
  const decision = parseGuidedOpeningApprovalSubmission(fact.decision);
  const expected = { selectionHash: selected.selectionHash, claimHash: selected.held.claimHash, executionId: claim.executionId,
    cleanupHash: selected.fact.cleanupHash, mediaResultSha256: selected.receiptSha256, receiptHash: selected.receiptHash,
    coreMediaSha256: selected.rows.core.mediaSha256, reviewMediaSha256: selected.rows.review.mediaSha256,
    clockHash: claim.clockHash, generationStartedAt: claim.generationStartedAt };
  for (const [key, value] of Object.entries(expected)) same(fact[key], value, key);
  same([decision.expectedToken, decision.expectedJournalHash, decision.selectionHash, decision.coreMediaSha256, decision.reviewMediaSha256],
    [current.job.token, fact.beforeJournalHash, fact.selectionHash, fact.coreMediaSha256, fact.reviewMediaSha256], "human decision");
  const stamps = [claim.generationStartedAt, selected.selectionQualifiedAt, fact.approvedAt].map(strictGuidedTimestamp);
  if (stamps.some((stamp, index) => index > 0 && stamp < stamps[index - 1])) throw new Error("Source-color approval predates its exact selection");
  return { decision, summary: { approvalHash: read.hash, approvedAt: String(fact.approvedAt), decisionHash: String(fact.decisionHash) } };
}

function originalTransition(read: ApprovalRead, before: ReturnType<ApprovalRead["read"]>): void {
  const fact = read.fact, job = parseAutoEditJobRecord(before.value), pointer = objectValue(job.guidedHandoffV2, "approval before pointer");
  if (before.sha256 !== fact.beforeJournalHash || pointer.openingApprovalHash || pointer.openingExecutionClaimHash
      || pointer.openingMediaSelectionHash !== fact.selectionHash || job.status !== "treatment_admitted"
      || !Number.isSafeInteger(job.nextEventId) || job.nextEventId < 0 || job.events.length > 256
      || strictGuidedTimestamp(job.updatedAt) > String(fact.approvedAt)) throw new Error("Source-color approval lost its exact preapproval journal");
  const event = { id: job.nextEventId, at: fact.approvedAt, payload: { event: "opening_approved_by_operator", approvalHash: read.hash,
    selectionHash: fact.selectionHash, executionId: fact.executionId, bodyGenerated: false, deliveryApproved: false } };
  same(read.original.current.job, { ...job, updatedAt: fact.approvedAt, guidedHandoffV2: { ...pointer, openingApprovalHash: read.hash },
    message: OPENING_APPROVAL_MESSAGE, nextEventId: job.nextEventId + 1, events: [...job.events, event].slice(-256) }, "approval job transition");
}

function records(read: ApprovalRead) {
  const files = { root: read.root, row: read.row, start: read.read(path.join(read.root, "start.json"), bounds.start),
    output: read.read(path.join(read.root, "output.json"), bounds.output), receipt: read.read(path.join(read.root, "verified.json"), bounds.verified),
    published: read.read(path.join(read.root, "approval.json"), bounds.approval) };
  same(files.receipt.sha256, read.row.readbackReceiptSha256, "verified raw SHA");
  same(files.output.sha256, read.row.readbackOutputSha256, "output raw SHA");
  same(files.output.value.elapsedMs, read.row.elapsedMs, "protected verification time");
  same(files.published.value, { ...read.fact, approvalHash: read.hash }, "private approval publication");
  same(files.start.sha256, sha256(files.receipt.value.startSha256, "raw-bound requalification start"), "start raw SHA");
  return files;
}

/** Retain genuine before-approval parents; expired live verifiers and current tools are never consulted. */
function qualification(read: ApprovalRead, files: ReturnType<typeof records>) {
  const cleanup = readHistoricalOpeningCleanup(read.original.dir, String(read.fact.beforeJournalHash)); read.metadata();
  const selected = readHeldSourceColorOpeningResult({ held: cleanup.held, guard: read.check }), claim = cleanup.held.claim;
  const history = readSourceColorReadbackHistory({ cleanup, selected, guard: read.check, reference: { schemaVersion: 2,
    beforeJournalHash: cleanup.sha256, cleanupHash: cleanup.cleanupHash, claimHash: cleanup.held.claimHash, executionId: claim.executionId,
    inputSha256: claim.inputSha256, executionInputHash: claim.executionInputHash, outputRoot: claim.outputRoot,
    readbackDirectory: String(read.row.readbackDirectory), readbackStartSha256: files.start.sha256,
    readbackOutputSha256: files.output.sha256, readbackReceiptSha256: files.receipt.sha256, mediaResultSha256: String(read.fact.mediaResultSha256),
    receiptHash: String(read.fact.receiptHash), clockHash: String(read.fact.clockHash), generationStartedAt: String(read.fact.generationStartedAt),
    selectionQualifiedAt: String(read.fact.approvedAt) } });
  return () => { assertOpeningCleanupMetadata(cleanup); assertSourceColorOpeningResultMetadata(selected, cleanup.held); assertSourceColorReadbackHistoryMetadata(history); };
}

/** One caller-protected metadata read; no work budget, user decision, launch or lease is created. */
export function readSourceColorOpeningApproval(input: SourceColorOpeningApprovalInput) {
  if (active.has(input)) throw new Error("Source-color approval cannot recursively reenter the same input");
  active.add(input);
  try {
    const read = new ApprovalRead(input), approval = read.retain(decisionBinding(read)), before = read.read(read.beforePath, 16 * 1024 * 1024);
    originalTransition(read, before); const files = read.retain(records(read)); read.check();
    const history = qualification(read, files); read.check(); history();
    const result = Object.freeze({ fact: read.fact, ...approval, before, files,
      observationScope: "retained-source2-human-decision-not-current-source-body-or-delivery-approval" as const });
    read.retain(result); const metadata = () => { read.metadata(); history(); read.metadata(); };
    metadata(); approvals.set(result, metadata); return result;
  } finally { active.delete(input); }
}

/** Callback-free finite original metadata only. Copies, altered values or another old proof cannot inherit this handle. */
export function assertSourceColorOpeningApprovalMetadata(value: object): void {
  const check = approvals.get(value);
  if (!check) throw new Error("Source-color approval requires its actual original retained read");
  check();
}
