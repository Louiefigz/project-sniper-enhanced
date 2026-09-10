import path from "node:path";
import { canonicalProducerDir } from "@/app/api/producer/auto-edit/request";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseRawTreatmentRevisionSubmissionV1, type RawTreatmentRevisionSubmissionV1 } from "@/lib/producer/contracts/raw-treatment-revision-v1";
import { rawTreatmentScope } from "@/lib/producer/contracts/raw-treatment-v1";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { readRawTreatmentAdmission } from "./guided-raw-treatment-store";
import { commitGuidedJob } from "./guided-cut-v2";
import { acquireGuidedMutation, finishGuidedOperation, guidedOperation, writeGuidedObject } from "./guided-cut-v2-store";
import { createHumanCutIndex, humanCutDirectory, saveHumanCutJobSnapshot } from "./human-cut-acceptance-store";
import { producerAuthorityPaths, writeAuthorityObjectSync } from "./producer-authority-files";
import { optionalLaunchRecord } from "./guided-opening-launch-store";
import { pinnedProposalFile } from "./guided-proposal-evidence";
import { proposalCompilerAuthority } from "./guided-proposal-compiler";
import { readGuidedTreatmentProposal } from "./guided-proposal-store";
import { readGuidedProposalReadiness } from "./guided-proposal-review-store";
import { startGuardedProposalDeadline } from "./generation-clock-watermark";
import type { DeadlineClocks } from "./generation-deadline";
import { assertTreatmentRevisionIdle, INVALIDATED_TREATMENT_KEYS, invalidatedTreatment,
  MAX_TREATMENT_ADMISSIONS, readTreatmentRevisionReservation, treatmentRevisionReservation } from "./guided-treatment-revision-store";

type Admission = ReturnType<typeof readRawTreatmentAdmission>;
type Operation = ReturnType<typeof guidedOperation>;
type Lease = Awaited<ReturnType<typeof acquireGuidedMutation>>;
interface Dependencies { fault?: (point: "after-reservation" | "after-fact" | "after-commit") => void; budgetClocks?: DeadlineClocks }
/** Fixed production dependencies; no runtime request, environment or CLI substitution. */
export const treatmentRevisionReads = { pinnedFile: pinnedProposalFile, implementation: proposalCompilerAuthority,
  proposal: readGuidedTreatmentProposal, readiness: readGuidedProposalReadiness };
const PINNED = ["src/lib/producer/contracts/raw-treatment-revision-v1.ts", "src/app/api/_lib/project-mutation.ts",
  ...["guided-treatment-revision", "guided-treatment-revision-store", "guided-raw-treatment-store"].map((name) => `src/lib/server/${name}.ts`)];

function assertCurrent(cut: Admission): void {
  assertTreatmentRevisionIdle(cut);
  for (const file of PINNED) treatmentRevisionReads.pinnedFile(cut, file, true);
  if (readRawTreatmentAdmission(cut.job.ctx.dir, { pendingRevisionObservation: true }).sha256 !== cut.sha256) throw new Error("Treatment revision checkpoint changed");
}

function replay(cut: Admission, submission: RawTreatmentRevisionSubmissionV1) {
  const prior = cut.lineage.find((row) => row.submission.idempotencyKey === submission.idempotencyKey);
  if (!prior) return null;
  if (canonicalJsonSha256(prior.submission) !== canonicalJsonSha256(submission)) throw new Error("Treatment revision idempotency key conflicts");
  return { job: cut.job, treatmentAdmissionHash: prior.hash, generationStartedAt: cut.generationStartedAt,
    replayed: true, superseded: prior.hash !== cut.pointer.treatmentAdmissionHash,
    sourceFreshness: "not-requalified-by-revision" as const, ...rawTreatmentScope() };
}

function assertSubmission(cut: Admission, submission: RawTreatmentRevisionSubmissionV1): void {
  if (cut.sha256 !== submission.expectedJournalHash || cut.job.token !== submission.expectedToken
      || cut.pointer.cutDecisionHash !== submission.cutDecisionHash || cut.pointer.pictureLockedRevisionHash !== submission.parentRevisionHash
      || cut.pointer.treatmentAdmissionHash !== submission.parentAdmissionHash
      || cut.admission.requestObjectHash !== submission.supersedesRequestHash) throw new Error("Treatment revision names a stale parent, request or journal");
  if (cut.lineage.length >= MAX_TREATMENT_ADMISSIONS) throw new Error("Treatment revision capacity exhausted; no automatic reset");
  if (cut.lineage.some((row) => row.submission.requestId === submission.requestId || row.submission.idempotencyKey === submission.requestId
      || row.submission.requestId === submission.idempotencyKey)) throw new Error("Treatment revision reuses a prior request identifier");
}

/** Metadata-only replacement; actual source requalification remains the ordinary compile owner's duty. */
export function reviseRawTreatment(input: { dir: unknown; submission: unknown }, deps: Dependencies = {}) {
  return revision(input, deps, false);
}

/** Explicit same-request recovery only. No automatic retry, new key, altered text or clock reset. */
export function reconcileRawTreatmentRevision(input: { dir: unknown; submission: unknown }, deps: Dependencies = {}) {
  return revision(input, deps, true);
}

async function revision(input: { dir: unknown; submission: unknown }, deps: Dependencies, reconcile: boolean) {
  const submission = parseRawTreatmentRevisionSubmissionV1(structuredClone(input.submission)), receivedAt = new Date().toISOString();
  const dir = canonicalProducerDir(input.dir), cut = readRawTreatmentAdmission(dir, { pendingRevisionObservation: true }), prior = replay(cut, submission);
  if (prior) return prior;
  assertSubmission(cut, submission); assertCurrent(cut);
  treatmentRevisionReads.implementation(cut);
  if (!reconcile) assertPriorWork(cut);
  const lease = await acquireGuidedMutation(dir, { workflowVersion: 2, action: "revise-post-cut-treatment",
    expectedStatus: "treatment_admitted", expectedToken: submission.expectedToken, expectedJournalHash: submission.expectedJournalHash });
  try {
    assertCurrent(cut);
    reserveRevision({ cut, submission, reconcile }); deps.fault?.("after-reservation");
    const operation = guidedOperation({ dir, id: submission.idempotencyKey, submission, receivedAt });
    return retainRevision({ cut, submission, operation, lease }, deps);
  } finally { lease.release(); }
}

function assertPriorWork(cut: Admission): void {
  const dir = cut.job.ctx.dir;
  if (cut.pointer.proposalReadinessHash) treatmentRevisionReads.readiness(dir);
  else if (cut.pointer.treatmentProposalHash) treatmentRevisionReads.proposal(dir);
}

function reserveRevision(input: { cut: Admission; submission: RawTreatmentRevisionSubmissionV1; reconcile: boolean }): void {
  const { cut, submission, reconcile } = input, dir = cut.job.ctx.dir;
  const expected = { schemaVersion: 1, kind: "guided-treatment-revision-reservation", parentAdmissionHash: submission.parentAdmissionHash,
    requestObjectHash: canonicalJsonSha256(submission), idempotencyKey: submission.idempotencyKey };
  const file = treatmentRevisionReservation(dir, submission.parentAdmissionHash), prior = readTreatmentRevisionReservation(dir, submission.parentAdmissionHash);
  if (prior) {
    if (canonicalJsonSha256(prior.value) !== canonicalJsonSha256(expected)) throw new Error("Another exact revision owns this parent; no fork or automatic recovery");
    if (!reconcile) throw new Error("Incomplete revision retained; use reconcile-revision with the same exact request file");
    return;
  }
  if (reconcile) throw new Error("No retained revision reservation to reconcile");
  if (optionalLaunchRecord(path.join(dir, "guided-v2-operations", submission.idempotencyKey, "submission.json"))) {
    throw new Error("Treatment revision idempotency key is already used by another operation");
  }
  humanCutDirectory(dir, "guided-treatment-revisions"); createHumanCutIndex(file, expected);
}

function revisionJob(cut: Admission, hash: string, at: string) {
  const pointer = { ...cut.pointer, treatmentAdmissionHash: hash };
  for (const key of INVALIDATED_TREATMENT_KEYS) delete pointer[key];
  return { ...cut.job, guidedHandoffV2: pointer, updatedAt: at,
    message: "Replacement treatment brief retained at unchanged accepted intent/cut. Prior unapproved work is historical; nothing executed or approved.",
    nextEventId: cut.job.nextEventId + 1, events: [...cut.job.events, { id: cut.job.nextEventId, at,
      payload: { event: "raw_treatment_revised", treatmentAdmissionHash: hash, parentAdmissionHash: cut.pointer.treatmentAdmissionHash,
        treatmentExecuted: false } }].slice(-256) };
}

function retainRevision(input: { cut: Admission; submission: RawTreatmentRevisionSubmissionV1; operation: Operation; lease: Lease }, deps: Dependencies) {
  const { cut, submission, operation, lease } = input, dir = cut.job.ctx.dir, leaseGuard = cutPreviewLeaseGuard(dir, lease);
  const budget = startGuardedProposalDeadline({ dir, origin: { clockHash: cut.clock.hash, startedAt: cut.generationStartedAt },
    executionId: operation.executionId, guard: leaseGuard }, deps.budgetClocks);
  const guard = () => { leaseGuard(); budget.remainingMs(); assertCurrent(cut); };
  try {
    guard(); saveHumanCutJobSnapshot(dir, cut);
    const requestObjectHash = writeAuthorityObjectSync(producerAuthorityPaths(dir).objects.requests, submission).hash;
    const budgetAdmissionHash = writeGuidedObject(dir, budget.admission), budgetPrecommitHash = writeGuidedObject(dir, budget.observe());
    const admittedAt = new Date().toISOString(), start = readCutPreviewObject(path.join(operation.execution, "start.json"));
    const treatmentAdmissionHash = writeGuidedObject(dir, { schemaVersion: 2, kind: "guided-raw-treatment-admission", scope: rawTreatmentScope().scope,
      requestObjectHash, parentAdmissionHash: submission.parentAdmissionHash, supersedesRequestHash: submission.supersedesRequestHash,
      invalidated: invalidatedTreatment(cut.pointer), cutDecisionHash: cut.pointer.cutDecisionHash, cutActivationHash: cut.pointer.cutActivationHash,
      parentRevisionHash: cut.pointer.pictureLockedRevisionHash, clockHash: cut.clock.hash, beforeJournalHash: cut.sha256,
      executionId: operation.executionId, executionStartHash: start.sha256, admittedAt, budgetAdmissionHash, budgetPrecommitHash });
    deps.fault?.("after-fact");
    guard(); treatmentRevisionReads.implementation(cut); guard();
    const job = commitGuidedJob({ beforeHash: cut.sha256, job: revisionJob(cut, treatmentAdmissionHash, admittedAt), guard });
    finishGuidedOperation(operation, { state: "raw-request-revised", treatmentAdmissionHash }); deps.fault?.("after-commit");
    const current = readRawTreatmentAdmission(dir);
    if (canonicalJsonSha256(current.job) !== canonicalJsonSha256(job)) throw new Error("Revision changed during final readback");
    leaseGuard(); budget.remainingMs();
    return { job, treatmentAdmissionHash, generationStartedAt: cut.generationStartedAt, replayed: false, superseded: false,
      sourceFreshness: "not-requalified-by-revision" as const, ...rawTreatmentScope() };
  } catch (error) {
    try { finishGuidedOperation(operation, { state: "failed-or-incomplete", error: String(error).slice(0, 1000) }); } catch { /* preserve earlier immutable evidence */ }
    throw error;
  }
}
