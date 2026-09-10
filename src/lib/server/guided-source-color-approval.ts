/** Explicit submitted human decision for schema2 media. No automatic approval, body launch or delivery. */
import path from "node:path";
import { isDeepStrictEqual } from "node:util";
import type { GuidedOpeningApprovalSubmissionV1 } from "@/lib/producer/contracts/guided-opening-approval-v1";
import { GUIDED_OPENING_APPROVAL_SCOPE, parseGuidedOpeningApprovalSubmission } from "@/lib/producer/contracts/guided-opening-approval-v1";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import type { ProjectMutationLease } from "./project-mutation-lease";
import { assertOpeningSelectionMetadata, readHistoricalOpeningSelection, type readSelectedOpeningMedia } from "./guided-opening-selection";
import { verifyCleanedSourceColorOpeningMediaUnderLease, assertSourceColorOpeningReadbackOwner,
  assertSourceColorOpeningReadbackMetadata } from "./guided-source-color-readback";
import { readHistoricalOpeningCleanup } from "./guided-opening-cleanup-store";
import { readHeldSourceColorOpeningResult } from "./guided-source-color-opening-result";
import { readSourceColorReadbackHistory, assertSourceColorReadbackHistoryMetadata } from "./guided-source-color-readback-history";
import { holdSelectionMedia } from "./guided-source-color-selection-read";
import { verifyOpeningApprovalMedia, OPENING_APPROVAL_MESSAGE } from "./guided-opening-approval";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { createHumanCutIndex, observeHumanCutJob, saveHumanCutJobSnapshot } from "./human-cut-acceptance-store";
import { writeGuidedObject } from "./guided-cut-v2-store";
import { commitGuidedJob } from "./guided-cut-v2";
import { autoEditJobPath } from "./auto-edit-job-persistence";
import { capturePublication, assertPublication } from "./guided-source-color-cleanup-pending-commit";
import { freezeSourceColorValue, snapshotSourceColorMetadata } from "./guided-source-color-staging-hold";
import { retainGenerationClockObservation } from "./generation-clock-watermark";

interface ApprovalInput {
  dir: string; submission: GuidedOpeningApprovalSubmissionV1; lease: ProjectMutationLease;
  selected: ReturnType<typeof readSelectedOpeningMedia>; remainingMs: () => number;
}
type Verified = Awaited<ReturnType<typeof verifyCleanedSourceColorOpeningMediaUnderLease>>;
export const sourceColorApprovalDependencies = { verify: verifyCleanedSourceColorOpeningMediaUnderLease };
const committedApprovals = new WeakMap<object, () => void>();

function same(actual: unknown, expected: unknown): void {
  if (!isDeepStrictEqual(actual, expected)) throw new Error("Source-color approval original authority changed");
}

/** No caller callback before exact request, selected proof, media metadata and current journal are captured. */
function owner(input: ApprovalInput) {
  const original = { ...input, release: input.lease.release };
  const decision = parseGuidedOpeningApprovalSubmission(snapshotSourceColorMetadata(input.submission));
  const { selected, dir } = original; assertOpeningSelectionMetadata(selected);
  if (selected.fact.schemaVersion !== 2) throw new Error("Source-color approval needs its explicit schema2 selection");
  const media = holdSelectionMedia(selected.rows), lease = cutPreviewLeaseGuard(dir, original.lease);
  const before = capturePublication(autoEditJobPath(dir), selected.observed.sha256);
  const current = observeHumanCutJob(dir);
  same([current.sha256, current.job.token, selected.selectionHash, selected.rows.core.mediaSha256, selected.rows.review.mediaSha256],
    [decision.expectedJournalHash, decision.expectedToken, decision.selectionHash, decision.coreMediaSha256, decision.reviewMediaSha256]);
  if (current.sha256 !== selected.observed.sha256 || current.job.guidedHandoffV2?.openingApprovalHash) {
    throw new Error("Source-color approval journal is stale or already approved");
  }
  const identity = () => {
    if (input.dir !== original.dir || input.lease !== original.lease || input.selected !== selected
        || input.submission !== original.submission || input.remainingMs !== original.remainingMs || input.lease.release !== original.release) {
      throw new Error("Source-color approval original caller changed");
    }
    same(input.submission, decision); media();
  };
  const metadata = () => { identity(); lease(); assertOpeningSelectionMetadata(selected); assertPublication(before); identity(); };
  const check = () => {
    metadata(); const began = performance.now(), remaining = original.remainingMs(); metadata();
    if (!Number.isSafeInteger(remaining) || remaining <= 0 || remaining > 600_000) throw new Error("Source-color approval protected remainder is invalid");
    const elapsed = performance.now() - began;
    if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed >= remaining) throw new Error("Source-color approval original allowance expired");
    return { started: performance.now(), remaining: remaining - elapsed };
  };
  metadata(); return { original, decision, current, identity, metadata, lease, check, guard: () => { check(); } };
}
type Owner = ReturnType<typeof owner>;

/** Actual private verification capability must belong to this original approval lease and protected remainder. */
async function requalify(held: Owner) {
  const { original: o } = held;
  verifyOpeningApprovalMedia(o.selected.rows, held.guard); held.check();
  const request = { dir: o.dir, lease: o.lease, expectedCleanupHash: String(o.selected.fact.cleanupHash), remainingMs: o.remainingMs };
  const verified = await sourceColorApprovalDependencies.verify(request);
  assertSourceColorOpeningReadbackOwner(verified, request); held.check();
  same([verified.selected.record.sha256, verified.observed.cleanupHash, verified.observed.sha256, verified.selected.completion.receiptHash],
    [o.selected.fact.mediaResultSha256, o.selected.fact.cleanupHash, held.current.sha256, o.selected.fact.receiptHash]);
  return verified;
}

function approvalFact(held: Owner, verified: Verified) {
  const { selected } = held.original, claim = selected.held.claim;
  const approvedAt = new Date().toISOString();
  if (approvedAt < String(verified.receipt.value.createdAt) || approvedAt < selected.selectionQualifiedAt) throw new Error("Source-color approval predates its exact verification");
  return freezeSourceColorValue({ schemaVersion: 2, kind: "guided-opening-approval", scope: GUIDED_OPENING_APPROVAL_SCOPE, actor: "local-operator",
    decision: held.decision, decisionHash: canonicalJsonSha256(held.decision), selectionHash: selected.selectionHash,
    claimHash: selected.held.claimHash, executionId: claim.executionId, cleanupHash: selected.fact.cleanupHash,
    mediaResultSha256: selected.fact.mediaResultSha256, receiptHash: selected.fact.receiptHash,
    coreMediaSha256: selected.rows.core.mediaSha256, reviewMediaSha256: selected.rows.review.mediaSha256,
    requalification: { readbackReceiptSha256: verified.receipt.sha256, readbackOutputSha256: verified.output.sha256,
      readbackDirectory: path.basename(path.dirname(verified.receipt.path)), elapsedMs: Number(verified.output.value.elapsedMs) },
    beforeJournalHash: held.current.sha256, clockHash: claim.clockHash, generationStartedAt: claim.generationStartedAt, approvedAt,
    openingApproved: true, bodyGenerated: false, deliveryApproved: false });
}

/** Capture separate saved history before CAS; current proof must never be replayed after its deliberate journal advance. */
function retained(held: Owner, verified: Verified, fact: ReturnType<typeof approvalFact>) {
  const { dir } = held.original;
  saveHumanCutJobSnapshot(dir, held.current); held.check();
  const selection = readHistoricalOpeningSelection(dir, held.current.sha256, held.guard);
  const cleanup = readHistoricalOpeningCleanup(dir, held.current.sha256); held.check();
  const selected = readHeldSourceColorOpeningResult({ held: cleanup.held, guard: held.guard }), claim = cleanup.held.claim;
  const reference = { schemaVersion: 2 as const, beforeJournalHash: held.current.sha256, cleanupHash: cleanup.cleanupHash,
    claimHash: cleanup.held.claimHash, executionId: claim.executionId, inputSha256: cleanup.held.claim.inputSha256,
    executionInputHash: cleanup.held.claim.executionInputHash, outputRoot: cleanup.held.claim.outputRoot,
    readbackDirectory: fact.requalification.readbackDirectory, readbackStartSha256: String(verified.receipt.value.startSha256),
    readbackOutputSha256: verified.output.sha256, readbackReceiptSha256: verified.receipt.sha256,
    mediaResultSha256: selected.record.sha256, receiptHash: selected.completion.receiptHash,
    clockHash: cleanup.held.claim.clockHash, generationStartedAt: cleanup.held.claim.generationStartedAt, selectionQualifiedAt: fact.approvedAt };
  const history = readSourceColorReadbackHistory({ cleanup, selected, reference, guard: held.guard });
  const metadata = () => { held.identity(); assertOpeningSelectionMetadata(selection); assertSourceColorReadbackHistoryMetadata(history); };
  held.check(); metadata(); return metadata;
}

/** New immutable fact/index only. Failure does not overwrite a previous decision or fake a successful CAS. */
function publish(held: Owner, verified: Verified, fact: ReturnType<typeof approvalFact>) {
  const { dir } = held.original, approvalHash = writeGuidedObject(dir, fact);
  const record = capturePublication(path.join(dir, ".sniper-authority-v1/objects/receipts", `${approvalHash}.json`), approvalHash);
  const value = { ...fact, approvalHash }, file = path.join(path.dirname(verified.receipt.path), "approval.json");
  held.check(); assertSourceColorOpeningReadbackMetadata(verified); createHumanCutIndex(file, value);
  const actual = readCutPreviewObject(file); same(actual.value, value);
  const index = capturePublication(file, actual.sha256);
  return { approvalHash, metadata: () => { assertPublication(record); assertPublication(index); } };
}

function nextJob(held: Owner, fact: ReturnType<typeof approvalFact>, approvalHash: string) {
  const job = held.current.job, at = fact.approvedAt;
  return snapshotSourceColorMetadata({ ...job, updatedAt: at, guidedHandoffV2: { ...job.guidedHandoffV2!, openingApprovalHash: approvalHash },
    message: OPENING_APPROVAL_MESSAGE, nextEventId: job.nextEventId + 1,
    events: [...job.events, { id: job.nextEventId, at, payload: { event: "opening_approved_by_operator", approvalHash,
      selectionHash: fact.selectionHash, executionId: fact.executionId, bodyGenerated: false, deliveryApproved: false } }].slice(-256) });
}

/** Caller already holds the original protected approval operation; this helper never starts or releases one. */
export async function approveSourceColorOpeningUnderLease(input: ApprovalInput) {
  const held = owner(input), verified = await requalify(held), fact = approvalFact(held, verified);
  const history = retained(held, verified, fact), publication = publish(held, verified, fact);
  const job = nextJob(held, fact, publication.approvalHash), fixed = snapshotSourceColorMetadata(job);
  let checkpoint: ReturnType<Owner["check"]> | undefined;
  const guard = () => {
    held.check(); assertSourceColorOpeningReadbackMetadata(verified); history(); publication.metadata(); same(job, fixed);
    retainGenerationClockObservation({ dir: held.original.dir, origin: { clockHash: fact.clockHash, startedAt: fact.generationStartedAt },
      executionId: fact.executionId, observedAt: new Date().toISOString() }, held.metadata);
    checkpoint = held.check(); assertSourceColorOpeningReadbackMetadata(verified); history(); publication.metadata(); same(job, fixed);
  };
  commitGuidedJob({ beforeHash: held.current.sha256, job, guard });
  const current = observeHumanCutJob(held.original.dir); same(current.job, fixed);
  const journal = capturePublication(autoEditJobPath(held.original.dir), current.sha256);
  held.lease(); history(); publication.metadata(); assertPublication(journal);
  const result = Object.freeze({ ok: true as const, replayed: false as const, approvalHash: publication.approvalHash,
    approvedAt: fact.approvedAt, selectionHash: fact.selectionHash });
  const metadata = () => { history(); publication.metadata(); assertPublication(journal); };
  metadata(); const elapsed = checkpoint ? performance.now() - checkpoint.started : Number.NaN;
  if (!checkpoint || !Number.isFinite(elapsed) || elapsed < 0 || elapsed >= checkpoint.remaining) {
    throw new Error("Source-color approval tail expired; decision may be committed, retain its evidence");
  }
  committedApprovals.set(result, metadata); return result;
}

/** Keep the original committed evidence through timing and legitimate lease release; never reread to rebaseline it. */
export function assertSourceColorOpeningApprovalCommitMetadata(result: object): void {
  const check = committedApprovals.get(result);
  if (!check) throw new Error("Source-color approval commit requires its actual original result");
  check();
}
