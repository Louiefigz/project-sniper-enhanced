import path from "node:path";
import { canonicalProducerDir } from "@/app/api/producer/auto-edit/request";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { verifyCutPreviewSources } from "@/app/api/producer/auto-edit/cut-preview-verification";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseRawTreatmentSubmissionV1, rawTreatmentScope } from "@/lib/producer/contracts/raw-treatment-v1";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { readGuidedCutV2, commitGuidedJob } from "./guided-cut-v2";
import { acquireGuidedMutation, guidedOperation, writeGuidedObject, finishGuidedOperation } from "./guided-cut-v2-store";
import { ensureRawTreatmentClock, readRawTreatmentAdmission } from "./guided-raw-treatment-store";
import { saveHumanCutJobSnapshot } from "./human-cut-acceptance-store";
import { timedStage } from "./stage-timing";
import { withStageTimingContext } from "./stage-timing-context";

interface IntakeDependencies {
  verifySources: typeof verifyCutPreviewSources;
  fault?: (point: "after-clock" | "after-fact" | "after-commit") => void;
}

/** Plain-language request intake. No checked boxes, generated clause IDs or executed operations required. */
export async function admitRawTreatment(input: { dir: unknown; submission: unknown }, overrides: Partial<IntakeDependencies> = {}) {
  const submission = parseRawTreatmentSubmissionV1(structuredClone(input.submission)), receivedAt = new Date().toISOString();
  const dir = canonicalProducerDir(input.dir), cut = readGuidedCutV2(dir);
  if (cut.job.status === "treatment_admitted") {
    const prior = readRawTreatmentAdmission(dir);
    if (canonicalJsonSha256(prior.submission) !== canonicalJsonSha256(submission)) throw new Error("Another treatment request is already admitted");
    return { job: prior.job, generationStartedAt: prior.generationStartedAt, replayed: true, ...rawTreatmentScope() };
  }
  if (submission.expectedJournalHash !== cut.sha256 || submission.expectedToken !== cut.job.token
      || submission.cutDecisionHash !== cut.pointer.cutDecisionHash || submission.parentRevisionHash !== cut.pointer.pictureLockedRevisionHash) {
    throw new Error("Raw request names a stale cut or journal");
  }
  const lease = await acquireGuidedMutation(dir, { workflowVersion: 2, action: "admit-post-cut-treatment",
    expectedStatus: "awaiting_treatment_brief", expectedToken: submission.expectedToken, expectedJournalHash: submission.expectedJournalHash });
  try { return await withStageTimingContext({ runId: cut.fact.runId, attemptId: `raw-treatment:${submission.idempotencyKey}`, attemptNo: cut.job.attempts }, () =>
    timedStage(dir, "guided_raw_treatment_intake", () => intakeUnderLease({ cut, submission, receivedAt, lease },
      { verifySources: verifyCutPreviewSources, ...overrides })));
  } finally { lease.release(); }
}

async function intakeUnderLease(input: { cut: ReturnType<typeof readGuidedCutV2>; submission: ReturnType<typeof parseRawTreatmentSubmissionV1>;
  receivedAt: string; lease: Awaited<ReturnType<typeof acquireGuidedMutation>> }, deps: IntakeDependencies) {
  const { cut, submission } = input, dir = cut.job.ctx.dir, guard = cutPreviewLeaseGuard(dir, input.lease);
  const operation = guidedOperation({ dir, id: submission.idempotencyKey, submission, receivedAt: input.receivedAt });
  try {
    const clock = ensureRawTreatmentClock(cut, submission, operation); deps.fault?.("after-clock");
    await deps.verifySources({ job: cut.job, request: cut.request, executionKey: cut.receipt.executionKey, lease: input.lease });
    guard(); const current = readGuidedCutV2(dir);
    if (current.sha256 !== cut.sha256) throw new Error("Raw treatment checkpoint changed during source verification");
    saveHumanCutJobSnapshot(dir, current);
    const now = new Date().toISOString(), start = readCutPreviewObject(path.join(operation.execution, "start.json"));
    const treatmentAdmissionHash = writeGuidedObject(dir, { schemaVersion: 1, kind: "guided-raw-treatment-admission",
      scope: rawTreatmentScope().scope, requestObjectHash: canonicalJsonSha256(submission), cutDecisionHash: cut.pointer.cutDecisionHash,
      cutActivationHash: cut.pointer.cutActivationHash, parentRevisionHash: cut.pointer.pictureLockedRevisionHash,
      clockHash: clock.hash, beforeJournalHash: cut.sha256, executionId: operation.executionId, executionStartHash: start.sha256, admittedAt: now });
    deps.fault?.("after-fact");
    const job = commitGuidedJob({ guard, beforeHash: cut.sha256, job: { ...current.job, status: "treatment_admitted", updatedAt: now,
      guidedHandoffV2: { ...cut.pointer, treatmentAdmissionHash }, message: "Raw treatment request retained. Unapproved proposal is pending; no treatment has executed.",
      nextEventId: current.job.nextEventId + 1, events: [...current.job.events, { id: current.job.nextEventId, at: now,
        payload: { event: "raw_treatment_admitted", treatmentAdmissionHash, generationStartedAt: clock.value.startedAt, treatmentExecuted: false } }].slice(-256) } });
    finishGuidedOperation(operation, { state: "raw-request-admitted", treatmentAdmissionHash }); deps.fault?.("after-commit");
    return { job, generationStartedAt: String(clock.value.startedAt), replayed: false, ...rawTreatmentScope() };
  } catch (error) {
    try { finishGuidedOperation(operation, { state: "failed-or-incomplete", error: String(error).slice(0, 1000) }); } catch { /* keep earlier immutable diagnostic */ }
    throw error;
  }
}
