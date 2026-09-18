import path from "node:path";
import { canonicalProducerDir } from "@/app/api/producer/auto-edit/request";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { verifyCutPreviewSources } from "@/app/api/producer/auto-edit/cut-preview-verification";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseTreatmentHandoffSubmissionV1, parseTreatmentIntakeV1, treatmentAdmissionScope } from "@/lib/producer/contracts/treatment-handoff-v1";
import { exactKeys, sha256 } from "@/lib/producer/contracts/validation";
import { canonicalJson, canonicalJsonSha256 } from "./auto-edit-hash";
import { observeHumanCutJob, saveHumanCutJobSnapshot } from "./human-cut-acceptance-store";
import { producerAuthorityPaths, writeAuthorityObjectSync } from "./producer-authority-files";
import type { ProjectMutationLease } from "./project-mutation-lease";
import { commitGuidedJob, readGuidedCutV2 } from "./guided-cut-v2";
import { acquireGuidedMutation, finishGuidedOperation, guidedOperation, readGuidedExecution, readGuidedObject, strictGuidedTimestamp, writeGuidedObject } from "./guided-cut-v2-store";
import { timedStage } from "./stage-timing";
import { parseAutoEditJobRecord } from "./auto-edit-job-persistence";
import { assertTreatmentRequestLineage, ensureTreatmentClockV2, readTreatmentClockV2 } from "./guided-treatment-clock-v2";
import { withStageTimingContext } from "./stage-timing-context";

type AcceptedCut = ReturnType<typeof readGuidedCutV2>;
type Submission = ReturnType<typeof parseTreatmentHandoffSubmissionV1>;
interface TreatmentDependencies {
  verifySources: typeof verifyCutPreviewSources;
  fault?: (point: "after-intake" | "after-admission" | "after-commit") => void;
}

/** Admit raw intent before semantic compilation; unsupported clauses remain retained and blocking. */
function intakeSubmission(cut: AcceptedCut, value: unknown) {
  if (Buffer.byteLength(canonicalJson(value)) > 256 * 1024) throw new Error("Treatment intake exceeds 256 KiB");
  const row = parseTreatmentIntakeV1(value), { request } = row;
  if (cut.job.status !== "awaiting_treatment_brief" || row.expectedToken !== cut.job.token
      || row.expectedJournalHash !== cut.sha256 || row.cutDecisionHash !== cut.pointer.cutDecisionHash
      || request.parentRevisionHash !== cut.pointer.pictureLockedRevisionHash || request.workflow !== "cut-first") {
    throw new Error("Treatment intake does not name the current v2 cut and exact revision");
  }
  return { row, request };
}

function assertTreatmentPreconditions(cut: AcceptedCut, submission: Submission): void {
  for (const binding of submission.bindings) {
    const action = binding.action;
    if (action.operation === "grade.set") {
      const grade = (cut.plan.value.baselineLook as { grade?: unknown } | undefined)?.grade ?? "none";
      if (grade !== action.expectedGrade) throw new Error("Treatment grade precondition no longer matches the cut plan");
    }
    if (action.operation === "scene.add" && action.scene.timing.timelineMapHash !== cut.request.timelineMapHash) {
      throw new Error("Proposed scene binds another cut timeline");
    }
    if (action.operation === "scene.move" && action.timelineMapHash !== cut.request.timelineMapHash) {
      throw new Error("Proposed scene move binds another cut timeline");
    }
  }
}

/** Admission proof only: original plan/intent/revision stay unchanged and no clause becomes committed. */
export function readTreatmentAdmissionV2(dir: string) {
  const cut = readGuidedCutV2(dir), hash = cut.pointer.treatmentAdmissionHash;
  if (cut.job.status !== "treatment_admitted" || !hash) throw new Error("No v2 treatment request has been admitted");
  const row = readGuidedObject(dir, hash);
  const keys = ["schemaVersion", "kind", "scope", "submission", "submissionHash", "requestObjectHash", "cutDecisionHash",
    "cutActivationHash", "parentRevisionHash", "clockHash", "beforeJournalHash", "executionId", "executionStartHash", "admittedAt"];
  exactKeys(row, keys, keys, "TreatmentAdmissionV2");
  const submission = parseTreatmentHandoffSubmissionV1(row.submission);
  if (row.schemaVersion !== 2 || row.kind !== "guided-treatment-admission" || row.scope !== treatmentAdmissionScope().scope
      || row.submissionHash !== canonicalJsonSha256(submission) || row.cutDecisionHash !== cut.pointer.cutDecisionHash
      || row.cutActivationHash !== cut.pointer.cutActivationHash || row.parentRevisionHash !== cut.pointer.pictureLockedRevisionHash
      || strictGuidedTimestamp(row.admittedAt) > cut.job.updatedAt || row.beforeJournalHash !== submission.expectedJournalHash) {
    throw new Error("Treatment admission authority changed");
  }
  const request = readCutPreviewObject(path.join(dir, ".sniper-authority-v1", "objects", "requests", `${sha256(row.requestObjectHash, "requestObjectHash")}.json`));
  if (request.sha256 !== row.requestObjectHash || canonicalJsonSha256(request.value) !== canonicalJsonSha256(submission.request)) {
    throw new Error("Treatment request ledger object changed");
  }
  const clock = readTreatmentClockV2(cut, { hash: sha256(row.clockHash, "clockHash"), noLaterThan: String(row.admittedAt) });
  const start = readGuidedExecution({ dir, id: submission.request.idempotencyKey, executionId: row.executionId, hash: row.executionStartHash });
  if (start.submissionHash !== row.submissionHash || strictGuidedTimestamp(start.startedAt) > String(row.admittedAt)
      || strictGuidedTimestamp(start.firstReceivedAt) < String(clock.value.startedAt)) throw new Error("Treatment admission execution changed");
  const before = readCutPreviewObject(path.join(dir, "human-cut-job-snapshots", `${sha256(row.beforeJournalHash, "beforeJournalHash")}.json`));
  const prior = parseAutoEditJobRecord(before.value);
  if (before.sha256 !== row.beforeJournalHash || prior.status !== "awaiting_treatment_brief" || prior.token !== cut.job.token
      || prior.guidedHandoffV2?.cutDecisionHash !== cut.pointer.cutDecisionHash || prior.guidedHandoffV2.treatmentAdmissionHash
      || canonicalJsonSha256(prior.ctx) !== canonicalJsonSha256(cut.job.ctx) || prior.updatedAt > String(clock.value.startedAt)
      || submission.expectedToken !== prior.token) throw new Error("Treatment admission lost its before journal");
  assertTreatmentRequestLineage(clock.request, submission.request);
  assertTreatmentPreconditions(cut, submission);
  if (observeHumanCutJob(dir).sha256 !== cut.sha256) throw new Error("Treatment changed during readback");
  return { ...cut, admission: row, submission, generationStartedAt: String(clock.value.startedAt), ...treatmentAdmissionScope() };
}

async function admitNewTreatment(input: { cut: AcceptedCut; value: unknown; receivedAt: string; lease: ProjectMutationLease }, deps: TreatmentDependencies) {
  const { cut } = input, dir = cut.job.ctx.dir, guard = cutPreviewLeaseGuard(dir, input.lease);
  const intake = intakeSubmission(cut, input.value);
  const operation = guidedOperation({ dir, id: intake.request.idempotencyKey, submission: intake.row, receivedAt: input.receivedAt });
  const clock = ensureTreatmentClockV2(cut, intake.request, operation);
  try {
    deps.fault?.("after-intake");
    const submission = parseTreatmentHandoffSubmissionV1(intake.row); assertTreatmentPreconditions(cut, submission);
    assertTreatmentRequestLineage(clock.request, submission.request);
    await deps.verifySources({ job: cut.job, request: cut.request, executionKey: cut.receipt.executionKey, lease: input.lease });
    guard(); const current = readGuidedCutV2(dir);
    if (current.sha256 !== cut.sha256) throw new Error("Treatment checkpoint changed during admitted-source verification");
    saveHumanCutJobSnapshot(dir, current);
    const requestObjectHash = writeAuthorityObjectSync(producerAuthorityPaths(dir).objects.requests, submission.request).hash;
    const now = new Date().toISOString(), start = readCutPreviewObject(path.join(operation.execution, "start.json"));
    const treatmentAdmissionHash = writeGuidedObject(dir, { schemaVersion: 2, kind: "guided-treatment-admission",
      scope: treatmentAdmissionScope().scope, submission, submissionHash: canonicalJsonSha256(submission), requestObjectHash,
      cutDecisionHash: cut.pointer.cutDecisionHash, cutActivationHash: cut.pointer.cutActivationHash,
      parentRevisionHash: cut.pointer.pictureLockedRevisionHash, clockHash: clock.hash, beforeJournalHash: cut.sha256,
      executionId: operation.executionId, executionStartHash: start.sha256, admittedAt: now });
    deps.fault?.("after-admission"); guard();
    const job = commitGuidedJob({ beforeHash: cut.sha256, guard, job: { ...current.job,
      status: "treatment_admitted", updatedAt: now, guidedHandoffV2: { ...cut.pointer, treatmentAdmissionHash },
      message: "New treatment intent admitted, not executed. Opening preview/body continuation remain unavailable.",
      nextEventId: current.job.nextEventId + 1, events: [...current.job.events, { id: current.job.nextEventId, at: now,
        payload: { event: "guided_treatment_admitted_v2", treatmentAdmissionHash, generationStartedAt: clock.value.startedAt,
          treatmentExecuted: false, finalApproved: false } }].slice(-256) } });
    finishGuidedOperation(operation, { state: "admitted-not-executed", treatmentAdmissionHash }); deps.fault?.("after-commit");
    return { job, treatmentAdmissionHash, generationStartedAt: String(clock.value.startedAt), replayed: false, ...treatmentAdmissionScope() };
  } catch (error) {
    try { finishGuidedOperation(operation, { state: "blocked-or-incomplete", error: String(error).slice(0, 1000) }); } catch { /* retained immutable diagnostic wins */ }
    throw error;
  }
}

/** Internal compiler/decision seam. No route, writer, render, or implicit ordinary Resume is enabled. */
export async function admitTreatmentV2(input: { dir: unknown; submission: unknown }, overrides: Partial<TreatmentDependencies> = {}) {
  const receivedAt = new Date().toISOString(), dir = canonicalProducerDir(input.dir), value = structuredClone(input.submission);
  const cut = readGuidedCutV2(dir);
  if (cut.job.status === "treatment_admitted") {
    const accepted = readTreatmentAdmissionV2(dir);
    if (canonicalJsonSha256(value) !== canonicalJsonSha256(accepted.submission)) throw new Error("A different treatment request is already admitted");
    return { job: accepted.job, treatmentAdmissionHash: accepted.pointer.treatmentAdmissionHash!,
      generationStartedAt: accepted.generationStartedAt, replayed: true, ...treatmentAdmissionScope() };
  }
  const intake = intakeSubmission(cut, value);
  const lease = await acquireGuidedMutation(dir, { workflowVersion: 2, action: "admit-post-cut-treatment",
    expectedStatus: "awaiting_treatment_brief", expectedToken: String(intake.row.expectedToken), expectedJournalHash: String(intake.row.expectedJournalHash) });
  try { return await withStageTimingContext({ runId: cut.fact.runId, attemptId: `guided-v2-treatment:${cut.job.token}`,
    attemptNo: cut.job.attempts }, () => timedStage(dir, "guided_v2_treatment_admission", () =>
    admitNewTreatment({ cut, value, receivedAt, lease }, { verifySources: verifyCutPreviewSources, ...overrides })));
  } finally { lease.release(); }
}
