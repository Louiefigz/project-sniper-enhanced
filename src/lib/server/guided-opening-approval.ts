import path from "node:path";
import { exactKeys, sha256, stringValue } from "@/lib/producer/contracts/validation";
import { GUIDED_OPENING_APPROVAL_SCOPE, parseGuidedOpeningApprovalSubmission,
  type GuidedOpeningApprovalSubmissionV1 } from "@/lib/producer/contracts/guided-opening-approval-v1";
import { canonicalProducerDir } from "@/app/api/producer/auto-edit/request";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { acquireGuidedMutation, readGuidedObject, strictGuidedTimestamp, writeGuidedObject } from "./guided-cut-v2-store";
import { createHumanCutIndex, observeHumanCutJob, saveHumanCutJobSnapshot } from "./human-cut-acceptance-store";
import { assertOpeningSelectionMetadata, openingSelectionVersion, parseOpeningSelectionFact, readSelectedOpeningMedia } from "./guided-opening-selection";
import { verifyCleanedOpeningMediaUnderLease } from "./guided-opening-readback";
import { approveSourceColorOpeningUnderLease, assertSourceColorOpeningApprovalCommitMetadata } from "./guided-source-color-approval";
import { readSourceColorOpeningApproval, assertSourceColorOpeningApprovalMetadata } from "./guided-source-color-approval-read";
import { selectionReadGuard, assertSelectionReadTime } from "./guided-source-color-selection-read";
import type { ProjectMutationLease } from "./project-mutation-lease";
import { commitGuidedJob } from "./guided-cut-v2";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { retainGenerationClockObservation } from "./generation-clock-watermark";
import { timedStage } from "./stage-timing";
import { withStageTimingContext } from "./stage-timing-context";

/** Separate protected verification allowance for the human decision; it never renews the generation budget. */
const APPROVAL_VERIFICATION_MS = 600_000;
export const OPENING_APPROVAL_MESSAGE = "The operator approved the exact selected opening. Full-body generation and delivery remain separate, unstarted work.";
const FACT_KEYS = ["schemaVersion", "kind", "scope", "actor", "decision", "decisionHash", "selectionHash", "claimHash", "executionId",
  "cleanupHash", "mediaResultSha256", "receiptHash", "coreMediaSha256", "reviewMediaSha256", "requalification", "beforeJournalHash",
  "clockHash", "generationStartedAt", "approvedAt", "openingApproved", "bodyGenerated", "deliveryApproved"];
const sourceApprovalSummaries = new WeakMap<object, () => void>();
interface ApprovalAttempt { dir: string; submission: GuidedOpeningApprovalSubmissionV1; lease: ProjectMutationLease;
  selected: ReturnType<typeof readSelectedOpeningMedia>; remainingMs: () => number }

export class GuidedOpeningApprovalError extends Error { constructor(message: string, readonly status: number) { super(message); } }

/** Observe each unique selected file once; every range keeps its exact SHA/size obligation.
 * This is guarded byte verification only, never an approval or source requalification. */
export function verifyOpeningApprovalMedia(
  rows: Record<string, { path: string; sizeBytes: number; mediaSha256: string }>, guard: () => void,
) {
  const checked = new Map<string, ReturnType<typeof observeCutPreviewFile>>();
  for (const row of Object.values(rows)) {
    guard();
    const observed = checked.get(row.path) ?? observeCutPreviewFile(row.path, 2 * 1024 ** 3, false, guard);
    if (observed.sizeBytes !== row.sizeBytes || observed.sha256 !== row.mediaSha256) {
      throw new GuidedOpeningApprovalError("Opening media bytes or size changed since selection", 409);
    }
    checked.set(row.path, observed);
  }
  guard();
}

function protectedClock() {
  const started = performance.now();
  return () => { const remaining = Math.floor(APPROVAL_VERIFICATION_MS - (performance.now() - started));
    if (!Number.isSafeInteger(remaining) || remaining <= 0 || remaining > APPROVAL_VERIFICATION_MS) {
      throw new GuidedOpeningApprovalError("Opening approval verification exceeded its protected allowance", 409);
    } return remaining; };
}

function replay(dir: string, hash: string, submission: GuidedOpeningApprovalSubmissionV1) {
  const fact = readGuidedObject(dir, hash);
  const verified = readGuidedOpeningApproval(dir, submission.selectionHash);
  if (verified?.approvalHash !== hash) throw new GuidedOpeningApprovalError("Opening approval replay lost its exact current lineage", 409);
  if (fact.schemaVersion === 2) {
    assertSourceColorOpeningApprovalSummaryMetadata(verified);
  } else if (fact.schemaVersion !== 1) throw new GuidedOpeningApprovalError("Opening approval version is unsupported", 409);
  if (canonicalJsonSha256(fact.decision) !== canonicalJsonSha256(submission)) throw new GuidedOpeningApprovalError("This opening already carries a different approval decision", 409);
  return { ok: true as const, replayed: true as const, approvalHash: hash, approvedAt: String(fact.approvedAt), selectionHash: String(fact.selectionHash) };
}

async function approveLegacyUnderLease(input: ApprovalAttempt) {
  const { dir, submission, lease, selected, remainingMs } = input, guard = cutPreviewLeaseGuard(dir, lease);
  if (selected.selectionHash !== submission.selectionHash || selected.rows.core.mediaSha256 !== submission.coreMediaSha256
      || selected.rows.review.mediaSha256 !== submission.reviewMediaSha256) throw new GuidedOpeningApprovalError("Approval names media that is not the current exact selection", 409);
  const current = observeHumanCutJob(dir);
  if (current.sha256 !== submission.expectedJournalHash || current.job.token !== submission.expectedToken) throw new GuidedOpeningApprovalError("Approval names a stale journal", 409);
  verifyOpeningApprovalMedia(selected.rows, () => { guard(); remainingMs(); });
  guard(); remainingMs();
  // Full current source/pipeline/context/output requalification through the actual read-only child, under a separate protected allowance.
  const verified = await verifyCleanedOpeningMediaUnderLease({ dir, lease, expectedCleanupHash: selected.fact.cleanupHash as string, remainingMs });
  if (verified.selected.record.sha256 !== selected.fact.mediaResultSha256 || verified.observed.cleanupHash !== selected.fact.cleanupHash
      || verified.observed.sha256 !== current.sha256) throw new GuidedOpeningApprovalError("Opening requalification does not bind the selected media", 409);
  guard(); remainingMs();
  const approvedAt = new Date().toISOString(), held = selected.held;
  const fact = { schemaVersion: 1, kind: "guided-opening-approval", scope: GUIDED_OPENING_APPROVAL_SCOPE, actor: "local-operator",
    decision: submission, decisionHash: canonicalJsonSha256(submission), selectionHash: selected.selectionHash, claimHash: held.claimHash,
    executionId: held.claim.executionId, cleanupHash: selected.fact.cleanupHash, mediaResultSha256: selected.fact.mediaResultSha256,
    receiptHash: selected.fact.receiptHash, coreMediaSha256: selected.rows.core.mediaSha256, reviewMediaSha256: selected.rows.review.mediaSha256,
    requalification: { readbackReceiptSha256: verified.receipt.sha256, readbackOutputSha256: verified.output.sha256,
      readbackDirectory: path.basename(path.dirname(verified.receipt.path)), elapsedMs: Number(verified.output.value.elapsedMs) },
    beforeJournalHash: current.sha256, clockHash: held.claim.clockHash, generationStartedAt: held.claim.generationStartedAt, approvedAt,
    openingApproved: true, bodyGenerated: false, deliveryApproved: false };
  const approvalHash = writeGuidedObject(dir, fact); saveHumanCutJobSnapshot(dir, current);
  createHumanCutIndex(path.join(path.dirname(verified.receipt.path), "approval.json"), { ...fact, approvalHash });
  const job = current.job;
  commitGuidedJob({ beforeHash: current.sha256, guard: () => { guard(); remainingMs();
    if (observeHumanCutJob(dir).sha256 !== current.sha256) throw new Error("Opening journal changed during approval");
    retainGenerationClockObservation({ dir, origin: { clockHash: held.claim.clockHash, startedAt: held.claim.generationStartedAt },
      executionId: held.claim.executionId, observedAt: new Date().toISOString() }, guard); },
  job: { ...job, updatedAt: approvedAt, guidedHandoffV2: { ...job.guidedHandoffV2!, openingApprovalHash: approvalHash },
    message: OPENING_APPROVAL_MESSAGE,
    nextEventId: job.nextEventId + 1, events: [...job.events, { id: job.nextEventId, at: approvedAt,
      payload: { event: "opening_approved_by_operator", approvalHash, selectionHash: selected.selectionHash, executionId: held.claim.executionId,
        bodyGenerated: false, deliveryApproved: false } }].slice(-256) } });
  return { ok: true as const, replayed: false as const, approvalHash, approvedAt, selectionHash: selected.selectionHash };
}

/** Explicit receipt version dispatch under the caller's ONE original protected approval allowance. */
export async function approveGuidedOpeningUnderLease(input: ApprovalAttempt) {
  if (openingSelectionVersion(input.selected) === 2) return approveSourceColorOpeningUnderLease(input);
  if (input.selected.fact.schemaVersion !== 1) throw new GuidedOpeningApprovalError("Opening selection version is unsupported", 409);
  return approveLegacyUnderLease(input);
}

/** Explicit human transaction under the guided lease. Replays an identical decision; refuses a different one. */
export async function approveGuidedOpening(input: { dir: unknown; submission: unknown }) {
  const submission = parseGuidedOpeningApprovalSubmission(structuredClone(input.submission)), remainingMs = protectedClock();
  const dir = canonicalProducerDir(input.dir);
  const before = observeHumanCutJob(dir);
  if (before.job.guidedHandoffV2?.openingApprovalHash) return replay(dir, before.job.guidedHandoffV2.openingApprovalHash, submission);
  if (before.job.status !== "treatment_admitted") throw new GuidedOpeningApprovalError("Opening approval requires an admitted treatment", 409);
  const lease = await acquireGuidedMutation(dir, { workflowVersion: 2, action: "approve-guided-opening", expectedStatus: "treatment_admitted",
    expectedToken: submission.expectedToken, expectedJournalHash: submission.expectedJournalHash });
  let result: Awaited<ReturnType<typeof approveGuidedOpeningUnderLease>>, sourceColor = false;
  try {
    const leaseGuard = cutPreviewLeaseGuard(dir, lease), guard = () => { leaseGuard(); remainingMs(); };
    guard(); const selected = readSelectedOpeningMedia(dir, guard), held = selected.held;
    sourceColor = selected.fact.schemaVersion === 2;
    result = await withStageTimingContext({ runId: held.job.artifactToken ?? held.job.token, attemptId: `opening-approval:${held.claim.executionId}`,
      attemptNo: held.job.attempts }, () => timedStage(dir, "guided_opening_human_approval",
      () => approveGuidedOpeningUnderLease({ dir, submission, lease, selected, remainingMs })));
    guard();
    if (sourceColor) assertSourceColorOpeningApprovalCommitMetadata(result);
  } finally { lease.release(); }
  remainingMs();
  if (sourceColor) assertSourceColorOpeningApprovalCommitMetadata(result);
  remainingMs(); return result;
}

/** Cheap verified read for status: the pointer must bind the CURRENT exact selection. */
export function readGuidedOpeningApproval(dir: string, selectionHash: string, existingSelection?: ReturnType<typeof readSelectedOpeningMedia>) {
  const started = performance.now(), guard = selectionReadGuard(started);
  const current = observeHumanCutJob(dir), hash = current.job.guidedHandoffV2?.openingApprovalHash;
  if (!hash) return null;
  if (current.job.guidedHandoffV2?.openingMediaSelectionHash !== selectionHash) throw new Error("Opening approval selection is stale");
  const fact = readGuidedObject(dir, hash);
  if (fact.schemaVersion !== parseOpeningSelectionFact(dir, selectionHash).schemaVersion) {
    throw new Error("Opening approval and actual selection versions differ");
  }
  if (fact.schemaVersion === 2) {
    const selected = existingSelection ?? readSelectedOpeningMedia(dir, guard);
    assertOpeningSelectionMetadata(selected);
    if (selected.selectionHash !== selectionHash || selected.observed.sha256 !== current.sha256) throw new Error("Source-color approval selection is stale");
    const approval = readSourceColorOpeningApproval({ dir, current, selected, guard });
    const summary = Object.freeze({ ...approval.summary });
    const metadata = () => { assertSourceColorOpeningApprovalMetadata(approval); };
    guard(); metadata(); assertSelectionReadTime(started); sourceApprovalSummaries.set(summary, metadata); return summary;
  }
  exactKeys(fact, FACT_KEYS, FACT_KEYS, "opening approval");
  for (const key of ["decisionHash", "selectionHash", "claimHash", "cleanupHash", "mediaResultSha256", "receiptHash", "coreMediaSha256", "reviewMediaSha256", "beforeJournalHash", "clockHash"]) sha256(fact[key], key);
  const decision = parseGuidedOpeningApprovalSubmission(fact.decision);
  if (fact.schemaVersion !== 1 || fact.kind !== "guided-opening-approval" || fact.scope !== GUIDED_OPENING_APPROVAL_SCOPE || fact.actor !== "local-operator"
      || fact.openingApproved !== true || fact.bodyGenerated !== false || fact.deliveryApproved !== false || fact.selectionHash !== selectionHash
      || decision.selectionHash !== selectionHash || canonicalJsonSha256(decision) !== fact.decisionHash
      || String(fact.approvedAt) > current.job.updatedAt) throw new Error("Opening approval does not bind the current exact selection");
  return { approvalHash: hash, approvedAt: strictGuidedTimestamp(fact.approvedAt), decisionHash: stringValue(fact.decisionHash, "decisionHash", 64) };
}

/** Retain the exact source2 approval proof through later status callbacks; a plain summary is not authority. */
export function assertSourceColorOpeningApprovalSummaryMetadata(summary: object): void {
  const check = sourceApprovalSummaries.get(summary);
  if (!check) throw new Error("Source-color approval summary requires its actual original retained read");
  check();
}
