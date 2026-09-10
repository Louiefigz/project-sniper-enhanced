import path from "node:path";
import { lstatSync } from "node:fs";
import { isDeepStrictEqual } from "node:util";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { BODY_CLAIM_MESSAGE, parseGuidedBodyExecutionClaim, type GuidedBodyExecutionClaimV1 } from "@/lib/producer/contracts/guided-body-claim-v1";
import { projectBodyProgramReferences } from "@/lib/producer/contracts/guided-body-media-v1";
import { canonicalJsonSha256 as hash } from "./auto-edit-hash";
import { observeHumanCutJob } from "./human-cut-acceptance-store";
import { autoEditJobPath, parseAutoEditJobRecord } from "./auto-edit-job-persistence";
import { readGuidedExecution, readGuidedObject } from "./guided-cut-v2-store";
import { readHistoricalOpeningSelection } from "./guided-opening-selection";
import { readHeldOpeningResult } from "./guided-opening-result";
import { bodyApprovalReads, readBodyOpeningApproval } from "./guided-body-approval";
import { assertBodyDeadlineProof } from "./guided-body-deadline";
import { parseBodyHeldDocument, readBodyObject } from "./guided-body-store";
import { readBodyOpeningResult, retainBodyOpeningMetadata, holdBodyOpeningReplay, type BodyOpeningResult } from "./guided-body-opening-version";
import { assertBodySourceColorReplayMetadata } from "./guided-body-source-color-replay";
import { selectionReadGuard, assertSelectionReadTime } from "./guided-source-color-selection-read";
import { capturePublication, assertPublication } from "./guided-source-color-cleanup-pending-commit";
import { snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";
import { directoryIdentity } from "./guided-source-color-cleanup-attempt-hold";

/** Internal read dependencies only; no public request can replace approval or process evidence. */
export const bodyClaimLineageReads = { selection: readHistoricalOpeningSelection, result: readHeldOpeningResult, approval: bodyApprovalReads };
const sourceClaimProofs = new WeakMap<object, () => void>();

/** Capture BEFORE the initial journal read; current and historical callers supply distinct exact paths. */
function bodyJournalMetadata(file: string): () => void {
  const identity = () => {
    const row = lstatSync(file, { bigint: true });
    if (!row.isFile() || row.nlink !== BigInt(1)) throw new Error("Body journal is not an original single-link regular file");
    return [row.dev, row.ino, row.mode, row.uid, row.nlink, row.size, row.mtimeNs, row.ctimeNs];
  };
  const original = identity(), parents = new Map<string, bigint[]>();
  for (let directory = path.dirname(file);; directory = path.dirname(directory)) {
    parents.set(directory, directoryIdentity(directory)); if (path.dirname(directory) === directory) break;
  }
  return () => {
    for (const [directory, state] of parents) {
      if (!isDeepStrictEqual(directoryIdentity(directory), state)) throw new Error("Body original journal ancestry changed");
    }
    if (!isDeepStrictEqual(identity(), original)) throw new Error("Body original journal file identity changed");
  };
}

/** Finite original admission/source proof only; copies and legacy rows cannot reconstruct it. */
export function assertBodyClaimSourceColorMetadata(held: object): void {
  const check = sourceClaimProofs.get(held);
  if (!check) throw new Error("Body source-color admission requires its actual original lineage proof");
  check();
}

/** Known source2 admissions cannot discard their original proof by downgrading a mutable tag. */
export function bodyAdmissionInputVersion(held: ReturnType<typeof readGuidedBodyClaim>): 1 | 2 {
  if (sourceClaimProofs.has(held) || held.input.row.schemaVersion === 2) {
    assertBodyClaimSourceColorMetadata(held); return 2;
  }
  if (held.input.row.schemaVersion !== 1 || held.input.input.schemaVersion !== 1) {
    throw new Error("Body admission input version is unsupported");
  }
  return 1;
}

/** Retain the original private/public body records BEFORE any historical-reader callback. */
function sourceAdmissionRecords(dir: string, edge: ReturnType<typeof snapshotAndEdge>, input: ReturnType<typeof parseBodyHeldDocument>) {
  if (input.row.schemaVersion !== 2) return () => {};
  const objects = path.join(dir, ".sniper-authority-v1/objects/receipts"), claim = edge.claim;
  const rows = [["claim.json", edge.claimHash], ["held-input.json", claim.heldInputHash],
    ["budget-admission.json", claim.budgetAdmissionHash], ["budget-precommit.json", claim.budgetPrecommitHash]];
  const records = rows.flatMap(([name, sha]) => [capturePublication(path.join(edge.execution, name), sha),
    capturePublication(path.join(objects, `${sha}.json`), sha)]);
  records.push(capturePublication(edge.snapshotPath, edge.before.sha256));
  const startPath = path.join(edge.execution, "start.json"), start = readCutPreviewObject(startPath);
  records.push(capturePublication(startPath, start.sha256));
  const fixed = snapshotSourceColorMetadata({ edge, input });
  const metadata = () => {
    if (!isDeepStrictEqual({ edge, input }, fixed)) throw new Error("Body source-color original admission metadata changed");
    records.forEach(assertPublication);
  };
  metadata(); return metadata;
}

function same(actual: unknown, expected: unknown, label: string): void {
  if (hash(actual) !== hash(expected)) throw new Error(`Body claim ${label} differs from exact held authority`);
}

/** Exactly ONE permitted edge. Never remove arbitrary fields or accept general descendants. */
export function bodyClaimJournal(before: ReturnType<typeof observeHumanCutJob>, claim: GuidedBodyExecutionClaimV1, claimHash: string) {
  const job = before.job, pointer = job.guidedHandoffV2;
  if (before.sha256 !== claim.beforeJournalHash || job.status !== "treatment_admitted" || !pointer?.openingApprovalHash
      || pointer.openingExecutionClaimHash || pointer.bodyExecutionClaimHash || job.updatedAt > claim.createdAt) {
    throw new Error("Body claim requires the exact unchanged post-approval journal");
  }
  return { ...job, updatedAt: claim.createdAt, guidedHandoffV2: { ...pointer, bodyExecutionClaimHash: claimHash },
    message: BODY_CLAIM_MESSAGE, nextEventId: job.nextEventId + 1,
    events: [...job.events, { id: job.nextEventId, at: claim.createdAt,
      payload: { event: "body_admission_claimed", claimHash, executionId: claim.executionId,
        executable: false, bodyGenerated: false, deliveryApproved: false } }].slice(-256) };
}

function snapshotAndEdge(dir: string, current: ReturnType<typeof observeHumanCutJob>) {
  const claimHash = current.job.guidedHandoffV2?.bodyExecutionClaimHash;
  if (!claimHash) throw new Error("No durable body admission claim exists");
  const claim = parseGuidedBodyExecutionClaim(readGuidedObject(dir, claimHash));
  const execution = path.join(dir, "guided-v2-operations", claim.requestId, "executions", claim.executionId);
  readBodyObject(dir, execution, "claim.json", claimHash);
  const file = path.join(dir, "human-cut-job-snapshots", `${claim.beforeJournalHash}.json`), raw = readCutPreviewObject(file);
  const before = { ...raw, job: parseAutoEditJobRecord(raw.value) };
  if (raw.sha256 !== claim.beforeJournalHash || before.job.ctx.dir !== dir) throw new Error("Body approved snapshot is changed or transplanted");
  same(current.job, bodyClaimJournal(before, claim, claimHash), "single approved-to-claim journal edge");
  return { claim, claimHash, execution, before, snapshotPath: file };
}

function heldBindings(input: ReturnType<typeof parseBodyHeldDocument>, edge: ReturnType<typeof snapshotAndEdge>,
  selected: ReturnType<typeof readHistoricalOpeningSelection>, result: BodyOpeningResult) {
  const { claim, before } = edge, pointer = before.job.guidedHandoffV2!, held = selected.held;
  same([input.input.journalHash, input.input.approvalHash, input.input.selectionHash, input.input.readinessHash, input.input.draftRevisionHash],
    [before.sha256, pointer.openingApprovalHash, pointer.openingMediaSelectionHash, pointer.proposalReadinessHash, pointer.treatmentDraftRevisionHash], "held input pointers");
  same(input.origin, { clockHash: claim.clockHash, startedAt: claim.generationStartedAt }, "original clock");
  same(input.origin, { clockHash: held.claim.clockHash, startedAt: held.claim.generationStartedAt }, "approved opening clock");
  same(input.input.authority, result.record.value.authority, "original media authority");
  same(input.opening, { claimPath: held.claimPath, claimSha256: held.claimSha256, inputPath: held.claim.inputPath,
    inputSha256: held.claim.inputSha256, executionInputHash: held.claim.executionInputHash, outputRoot: held.claim.outputRoot,
    resultPath: path.join(held.claim.outputRoot, "media-result.json"), resultSha256: result.record.sha256 }, "original opening references");
  same(input.input.references, projectBodyProgramReferences(result.record.value), "retained whole program references");
  if (input.submission.idempotencyKey !== claim.requestId || input.submission.expectedJournalHash !== before.sha256
      || input.submission.expectedToken !== before.job.token) throw new Error("Body claim request moved to another approved checkpoint");
  same([input.submission.openingApprovalHash, input.submission.selectionHash, input.submission.proposalReadinessHash, input.submission.treatmentDraftRevisionHash],
    [pointer.openingApprovalHash, pointer.openingMediaSelectionHash, pointer.proposalReadinessHash, pointer.treatmentDraftRevisionHash], "request approval pointers");
}

function executionProof(dir: string, edge: ReturnType<typeof snapshotAndEdge>, input: ReturnType<typeof parseBodyHeldDocument>) {
  const { claim, execution } = edge, file = readCutPreviewObject(path.join(execution, "start.json"));
  const started = readGuidedExecution({ dir, id: claim.requestId, executionId: claim.executionId, hash: file.sha256 });
  same(started.submissionHash, hash(input.submission), "operation intake");
  const admission = readBodyObject(dir, execution, "budget-admission.json", claim.budgetAdmissionHash);
  const precommit = readBodyObject(dir, execution, "budget-precommit.json", claim.budgetPrecommitHash);
  assertBodyDeadlineProof({ admission, precommit }, { origin: { clockHash: claim.clockHash, startedAt: claim.generationStartedAt },
    executionReceivedAt: String(started.receivedAt), executionStartedAt: String(started.startedAt), createdAt: claim.createdAt });
}

/** Historical non-executable admission only; an exact current body edge is checked BEFORE reading opening history. */
function fromJournal(dir: string, current: ReturnType<typeof observeHumanCutJob>, reads: typeof bodyClaimLineageReads,
  controls: { guard: () => void; journal: () => void }) {
  const originalCurrent = snapshotSourceColorMetadata(current);
  const journalMetadata = () => {
    if (!isDeepStrictEqual(current, originalCurrent)) throw new Error("Body original current journal observation changed");
  };
  const edge = snapshotAndEdge(dir, current);
  const input = parseBodyHeldDocument(readBodyObject(dir, edge.execution, "held-input.json", edge.claim.heldInputHash));
  const admissionMetadata = sourceAdmissionRecords(dir, edge, input);
  const entryMetadata = () => { journalMetadata(); if (input.row.schemaVersion === 2) controls.journal(); };
  const check = () => { entryMetadata(); admissionMetadata(); controls.guard(); entryMetadata(); admissionMetadata(); };
  const selected = reads.selection(dir, edge.before.sha256, check), sourceColor = selected.fact.schemaVersion === 2;
  const result = readBodyOpeningResult({ selected, guard: check }, reads.result);
  const approval = readBodyOpeningApproval({ dir, current: edge.before, selected, result, guard: check }, reads.approval);
  const openingMetadata = retainBodyOpeningMetadata({ selected, result, approval });
  const replay = holdBodyOpeningReplay({ selected, result, guard: check });
  const metadata = () => { entryMetadata(); admissionMetadata(); openingMetadata(); if (replay) assertBodySourceColorReplayMetadata(replay); };
  same(input.row.schemaVersion, sourceColor ? 2 : 1, "held opening version");
  if (replay) same(input.input.sourceColorReplay, replay.references, "original source-color replay references");
  heldBindings(input, edge, selected, result); executionProof(dir, edge, input);
  if (readCutPreviewObject(edge.snapshotPath).sha256 !== edge.before.sha256) {
    throw new Error("Body claim changed during historical observation");
  }
  metadata(); const held = { ...edge, current, input, observationScope: "exact-claim-and-held-approved-history-not-current-source-or-media-verification" as const,
    executable: false as const, workerState: "not-installed" as const, bodyGenerated: false as const, deliveryApproved: false as const };
  if (sourceColor) {
    const fixed = snapshotSourceColorMetadata(held);
    sourceClaimProofs.set(held, () => {
      if (!isDeepStrictEqual(held, fixed)) throw new Error("Body source-color returned admission metadata changed");
      metadata();
    });
  }
  return held;
}

/** Current admission only: no later execution edge may be mistaken for this single claim transition. */
export function readGuidedBodyClaim(dir: string, reads = bodyClaimLineageReads) {
  const started = performance.now(), guard = selectionReadGuard(started);
  const journal = bodyJournalMetadata(autoEditJobPath(dir));
  const current = observeHumanCutJob(dir), held = fromJournal(dir, current, reads, { guard, journal });
  if (observeHumanCutJob(dir).sha256 !== current.sha256) throw new Error("Body claim changed during historical observation");
  const metadata = sourceClaimProofs.get(held);
  if (metadata) { metadata(); assertSelectionReadTime(started); }
  return held;
}

/** Actual retained journal bytes only. The consumer must first prove its distinct known activation edge. */
export function readHistoricalBodyAdmission(dir: string, journalHash: string) {
  const started = performance.now(), guard = selectionReadGuard(started);
  if (!/^[a-f0-9]{64}$/u.test(journalHash)) throw new Error("Historical body admission hash is malformed");
  const file = path.join(dir, "human-cut-job-snapshots", `${journalHash}.json`), journal = bodyJournalMetadata(file), raw = readCutPreviewObject(file);
  if (raw.sha256 !== journalHash) throw new Error("Historical body admission journal changed");
  const current = { ...raw, job: parseAutoEditJobRecord(raw.value) };
  if (current.job.ctx.dir !== dir) throw new Error("Historical body admission names another project");
  const held = fromJournal(dir, current, bodyClaimLineageReads, { guard, journal });
  if (readCutPreviewObject(file).sha256 !== journalHash) throw new Error("Historical body admission changed during observation");
  const metadata = sourceClaimProofs.get(held);
  if (metadata) { metadata(); assertSelectionReadTime(started); }
  return held;
}
