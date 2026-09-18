import { randomUUID } from "node:crypto";
import { mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import type { TestContext } from "node:test";
import path from "node:path";
import { guidedFixture } from "@/lib/producer/__tests__/_guided-cut-fixture";
import { parseRawTreatmentSubmissionV1 } from "@/lib/producer/contracts/raw-treatment-v1";
import { parseRawTreatmentRevisionSubmissionV1 } from "@/lib/producer/contracts/raw-treatment-revision-v1";
import { autoEditRequestKey, canonicalJsonSha256 } from "../auto-edit-hash";
import { parseAutoEditJobRecord } from "../auto-edit-job-persistence";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { clearProducerRun } from "../producer-run-registry";
import { readRawTreatmentAdmission, rawTreatmentAdmissionReads, ensureRawTreatmentClock } from "../guided-raw-treatment-store";
import { treatmentRevisionReads } from "../guided-treatment-revision";
import { guidedOperation, writeGuidedObject } from "../guided-cut-v2-store";
import { saveHumanCutJobSnapshot } from "../human-cut-acceptance-store";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";

const H = "a".repeat(64);

/** TEST protocol data only: real request/clock/lineage/lease/CAS; accepted media and pipeline proof are mocked. */
export async function treatmentRevisionFixture(t: TestContext) {
  const root = realpathSync(mkdtempSync("/private/tmp/sniper-treatment-revision-"));
  const env = process.env.SNIPER_WORKSPACE_ROOT; process.env.SNIPER_WORKSPACE_ROOT = root;
  const base = guidedFixture(path.join(root, "TEST-project"), { schemaVersion: 2, mode: "guided",
    afterCut: "treatment-then-intro", approvalPolicy: "explicit-human" });
  const dir = base.ctx.dir, at = new Date(Date.now() - 1000).toISOString(), job = structuredClone(base.run.job);
  const request = { schemaVersion: 1 as const, requestKey: autoEditRequestKey(job.ctx), planHash: H, authorityDigest: H,
    cutAuthorityDigest: H, cutApprovalReceiptHash: H, cutReviewApprovalReceiptHash: H, pictureLockHash: H,
    timelineMapHash: H, projectionReceiptHash: H, createdAt: at };
  Object.assign(job, { token: randomUUID(), status: "awaiting_treatment_brief", checkpoint: "cut_reviewed", updatedAt: at,
    workerPid: undefined, workerIdentity: undefined, cutApprovalWaitStartedAt: at,
    cutApprovalRequest: { ...request, requestHash: canonicalJsonSha256(request) }, cutPreview: { executionKey: H, receiptHash: H },
    guidedHandoffV2: { schemaVersion: 2, cutDecisionHash: H, cutActivationHash: H, pictureLockedRevisionHash: H } });
  writeFileSync(base.jobPath, JSON.stringify(parseAutoEditJobRecord(job))); clearProducerRun(dir);
  t.after(() => { clearProducerRun(dir); rmSync(root, { recursive: true, force: true });
    if (env === undefined) delete process.env.SNIPER_WORKSPACE_ROOT; else process.env.SNIPER_WORKSPACE_ROOT = env; });
  t.mock.method(rawTreatmentAdmissionReads, "cut", () => {
    const observed = observeHumanCutJob(dir);
    return { ...observed, pointer: observed.job.guidedHandoffV2!, fact: { contextHash: canonicalJsonSha256(job.ctx), runId: "TEST-run" },
      activation: { recordedAt: at }, receipt: { executionKey: H }, request: observed.job.cutApprovalRequest } as unknown as ReturnType<typeof rawTreatmentAdmissionReads.cut>;
  });
  t.mock.method(treatmentRevisionReads, "pinnedFile", () => ({ sha256: H }));
  t.mock.method(treatmentRevisionReads, "implementation", () => ({ scope: "TEST-only-pinned-implementation" }));
  const cut = rawTreatmentAdmissionReads.cut(dir), first = parseRawTreatmentSubmissionV1({ schemaVersion: 1, operation: "propose-post-cut-treatment",
    requestId: randomUUID(), idempotencyKey: randomUUID(), expectedToken: cut.job.token, expectedJournalHash: cut.sha256,
    cutDecisionHash: H, parentRevisionHash: H, rawIntent: "TEST original complete brief." });
  firstAdmission(cut, first, base.jobPath);
  return { ...base, root, dir, first };
}

function firstAdmission(cut: ReturnType<typeof rawTreatmentAdmissionReads.cut>, first: ReturnType<typeof parseRawTreatmentSubmissionV1>, file: string) {
  const dir = cut.job.ctx.dir, operation = guidedOperation({ dir, id: first.idempotencyKey, submission: first, receivedAt: new Date().toISOString() });
  const clock = ensureRawTreatmentClock(cut, first, operation), admittedAt = new Date().toISOString();
  saveHumanCutJobSnapshot(dir, cut);
  const hash = writeGuidedObject(dir, { schemaVersion: 1, kind: "guided-raw-treatment-admission", scope: "raw-treatment-request-not-executed-or-approved",
    requestObjectHash: canonicalJsonSha256(first), cutDecisionHash: H, cutActivationHash: H, parentRevisionHash: H, clockHash: clock.hash,
    beforeJournalHash: cut.sha256, executionId: operation.executionId,
    executionStartHash: readCutPreviewObject(path.join(operation.execution, "start.json")).sha256, admittedAt });
  writeFileSync(file, JSON.stringify({ ...cut.job, status: "treatment_admitted", updatedAt: admittedAt,
    guidedHandoffV2: { ...cut.pointer, treatmentAdmissionHash: hash } }));
}

export function revisionRequest(dir: string, rawIntent = "TEST explicit replacement complete brief.") {
  const current = readRawTreatmentAdmission(dir);
  return parseRawTreatmentRevisionSubmissionV1({ schemaVersion: 1, operation: "revise-post-cut-treatment",
    supersession: "replace-complete-prior-brief", requestId: randomUUID(), idempotencyKey: randomUUID(),
    expectedToken: current.job.token, expectedJournalHash: current.sha256, cutDecisionHash: current.pointer.cutDecisionHash,
    parentRevisionHash: current.pointer.pictureLockedRevisionHash, parentAdmissionHash: current.pointer.treatmentAdmissionHash,
    supersedesRequestHash: canonicalJsonSha256(current.submission), rawIntent });
}
