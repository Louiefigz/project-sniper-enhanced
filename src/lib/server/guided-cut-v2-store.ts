import path from "node:path";
import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { parseGuidedWorkflowV2, parseGuidedCutSubmissionV2 } from "@/lib/producer/contracts/guided-workflow-v2";
import type { GuidedCutSubmissionV2 } from "@/lib/producer/contracts/guided-workflow-v2";
import { parseCutApprovalRequest, type CutApprovalRequestV1 } from "@/lib/producer/contracts/cut-approval-request";
import { exactKeys, objectValue, sha256, uuid } from "@/lib/producer/contracts/validation";
import { assertCutApprovalRequestCurrent } from "@/app/api/producer/auto-edit/cut-approval-request";
import { readCutPreviewObject, readCurrentCutPreview } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseCompatibilityProjection } from "@/app/api/producer/auto-edit/compatibility-timeline-projection";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { observeHumanCutJob, humanCutDirectory, createHumanCutIndex, saveHumanCutJobSnapshot } from "./human-cut-acceptance-store";
import { producerAuthorityPaths, writeAuthorityObjectSync } from "./producer-authority-files";
import { guardProjectMutation, mutationProjectRoot, type CheckpointVerification } from "@/app/api/_lib/project-mutation";
import { assertBootstrapQuiescence } from "./guided-project-bootstrap-quiescence";

export interface GuidedCutDecisionV2 {
  schemaVersion: 2; kind: "guided-cut-decision"; scope: "cut-only-await-treatment-not-delivery";
  producerDir: string; submission: GuidedCutSubmissionV2; originalJobHash: string; contextHash: string;
  request: CutApprovalRequestV1; runId: string; previewAttempt: number;
  sourceSetDigest: string; sourceSetReceiptHash: string; submittedAt: string; nextToken: string;
}

export function strictGuidedTimestamp(value: unknown): string {
  if (typeof value !== "string" || !Number.isFinite(Date.parse(value)) || new Date(value).toISOString() !== value) {
    throw new Error("Guided v2 timestamp is malformed");
  }
  return value;
}

/** Bounded no-follow, single-link object read; never creates authority directories. */
export function readGuidedObject(dir: string, hash: string) {
  sha256(hash, "guided object hash");
  const observed = readCutPreviewObject(path.join(dir, ".sniper-authority-v1", "objects", "receipts", `${hash}.json`));
  if (observed.sha256 !== hash || canonicalJsonSha256(observed.value) !== hash) throw new Error("Guided authority object changed");
  return observed.value;
}
export function writeGuidedObject(dir: string, value: unknown): string {
  return writeAuthorityObjectSync(producerAuthorityPaths(dir).objects.receipts, value).hash;
}

/** Checkpoint capability grants verification only, with all project reconciliation checks retained. */
export async function acquireGuidedMutation(dir: string, checkpointVerification: CheckpointVerification) {
  const guarded = guardProjectMutation({ projectRoot: mutationProjectRoot(dir), producerDir: dir,
    operation: checkpointVerification.action, checkpointVerification });
  if (guarded.response) {
    const detail = await guarded.response.json() as { error?: string };
    throw new Error(detail.error ?? "Guided checkpoint mutation is unavailable");
  }
  return guarded.lease;
}

/** Validate identifiers before deriving paths and bind every execution clock to its immutable intake. */
export function readGuidedExecution(input: { dir: string; id: string; executionId: unknown; hash: unknown }) {
  const id = uuid(input.id, "operation id"), executionId = uuid(input.executionId, "executionId");
  const hash = sha256(input.hash, "executionStartHash");
  const start = readCutPreviewObject(path.join(input.dir, "guided-v2-operations", id, "executions", executionId, "start.json"));
  const row = start.value, keys = ["schemaVersion", "executionId", "submissionHash", "firstReceivedAt", "receivedAt", "startedAt"];
  exactKeys(row, keys, keys, "guided execution start"); sha256(row.submissionHash, "submissionHash");
  const clock = [row.firstReceivedAt, row.receivedAt, row.startedAt].map(strictGuidedTimestamp);
  const intake = readCutPreviewObject(path.join(input.dir, "guided-v2-operations", id, "submission.json")).value;
  const intakeKeys = ["schemaVersion", "kind", "producerDir", "submissionHash", "submission", "receivedAt", "nextToken"];
  exactKeys(intake, intakeKeys, intakeKeys, "guided intake"); uuid(intake.nextToken, "nextToken");
  if (start.sha256 !== hash || row.schemaVersion !== 2 || row.executionId !== executionId
      || clock.some((at, index) => index > 0 && at < clock[index - 1]) || intake.schemaVersion !== 2
      || intake.kind !== "guided-v2-intake" || intake.producerDir !== input.dir || intake.receivedAt !== row.firstReceivedAt
      || intake.submissionHash !== row.submissionHash || canonicalJsonSha256(intake.submission) !== row.submissionHash) {
    throw new Error("Guided execution start/intake changed");
  }
  return row;
}

export function parseGuidedCutDecision(value: unknown): GuidedCutDecisionV2 {
  const row = objectValue(value, "GuidedCutDecisionV2");
  const keys = ["schemaVersion", "kind", "scope", "producerDir", "submission", "originalJobHash", "contextHash",
    "request", "runId", "previewAttempt", "sourceSetDigest", "sourceSetReceiptHash", "submittedAt", "nextToken"];
  exactKeys(row, keys, keys, "GuidedCutDecisionV2");
  const submission = parseGuidedCutSubmissionV2(row.submission), request = parseCutApprovalRequest(row.request);
  if (row.schemaVersion !== 2 || row.kind !== "guided-cut-decision" || row.scope !== "cut-only-await-treatment-not-delivery"
      || typeof row.producerDir !== "string" || !path.isAbsolute(row.producerDir)
      || typeof row.runId !== "string" || !row.runId || row.runId.length > 200
      || !Number.isSafeInteger(row.previewAttempt) || Number(row.previewAttempt) < 1 || Number(row.previewAttempt) > 10000
      || submission.expectedJournalHash !== row.originalJobHash || submission.requestHash !== request.requestHash) {
    throw new Error("Guided cut decision bindings are invalid");
  }
  for (const key of ["originalJobHash", "contextHash", "sourceSetDigest", "sourceSetReceiptHash"]) sha256(row[key], key);
  strictGuidedTimestamp(row.submittedAt); uuid(row.nextToken, "nextToken");
  return row as unknown as GuidedCutDecisionV2;
}

/** Same full v2 context, old exact cut receipts, actual preview bytes; no authority narrowing. */
export function observeGuidedCutV2(dir: string) {
  const observed = observeHumanCutJob(dir), { job } = observed;
  assertBootstrapQuiescence(job);
  parseGuidedWorkflowV2(job.ctx.workflowV2);
  if (job.cutAcceptance || job.cutAcceptanceAttempt || !job.cutPreview || !job.cutApprovalRequest
      || job.workerPid || job.workerIdentity) throw new Error("V2 handoff needs an idle exact cut checkpoint, not v1 acceptance or a worker");
  const request = assertCutApprovalRequestCurrent(job, job.cutApprovalRequest);
  const receipt = readCurrentCutPreview(path.join(dir, "cut-previews", request.requestHash, job.cutPreview.executionKey), request);
  const clock = [job.requestedAt, request.createdAt, receipt.createdAt, job.cutApprovalWaitStartedAt, job.updatedAt].map(strictGuidedTimestamp);
  if (clock.some((at, index) => index > 0 && at < clock[index - 1])) throw new Error("V2 guided cut checkpoint clocks are inconsistent");
  const manifest = readCutPreviewObject(job.ctx.manifestPath), plan = readCutPreviewObject(job.ctx.planPath);
  const admission = objectValue(manifest.value.sourceSetAdmission, "source-set admission");
  if (receipt.receiptHash !== job.cutPreview.receiptHash || receipt.runId !== (job.artifactToken ?? job.token)
      || receipt.attempt !== job.attempts || receipt.manifestHash !== manifest.sha256
      || receipt.sourceSetDigest !== admission.sourceSetDigest || receipt.sourceSetReceiptHash !== admission.receiptSha256
      || plan.sha256 !== request.planHash) throw new Error("V2 cut preview/source/plan identity drifted");
  const lock = readCutPreviewObject(path.join(dir, "picture_locks", `${request.pictureLockHash}.json`));
  const projected = readCutPreviewObject(path.join(dir, "compatibility_projections", `${request.projectionReceiptHash}.json`));
  const projection = parseCompatibilityProjection(projected.value, String(lock.value.approvedCutPlanHash));
  if (lock.sha256 !== request.pictureLockHash || projected.sha256 !== request.projectionReceiptHash
      || projection.timelineMapHash !== request.timelineMapHash) throw new Error("V2 cut projection changed");
  if (observeHumanCutJob(dir).sha256 !== observed.sha256) throw new Error("V2 cut journal changed during observation");
  assertBootstrapQuiescence(job);
  return { ...observed, request, receipt, manifest, plan, lock, projection };
}
export type GuidedCutObservation = ReturnType<typeof observeGuidedCutV2>;

/** Immutable intake + execution starts survive crashes; reads of them are non-creating. */
export function guidedOperation(input: { dir: string; id: string; submission: unknown; receivedAt: string }) {
  uuid(input.id, "guided operation id"); strictGuidedTimestamp(input.receivedAt);
  const root = humanCutDirectory(input.dir, "guided-v2-operations"), directory = humanCutDirectory(root, input.id);
  const file = path.join(directory, "submission.json"), digest = canonicalJsonSha256(input.submission);
  if (!existsSync(file)) createHumanCutIndex(file, { schemaVersion: 2, kind: "guided-v2-intake", producerDir: input.dir,
    submissionHash: digest, submission: input.submission, receivedAt: input.receivedAt, nextToken: randomUUID() });
  const record = readCutPreviewObject(file).value;
  const keys = ["schemaVersion", "kind", "producerDir", "submissionHash", "submission", "receivedAt", "nextToken"];
  exactKeys(record, keys, keys, "GuidedV2Intake");
  if (record.schemaVersion !== 2 || record.kind !== "guided-v2-intake" || record.producerDir !== input.dir
      || record.submissionHash !== digest || canonicalJsonSha256(record.submission) !== digest) throw new Error("Guided idempotency key conflicts with retained full request");
  strictGuidedTimestamp(record.receivedAt); uuid(record.nextToken, "nextToken");
  const executionId = randomUUID(), executions = humanCutDirectory(directory, "executions");
  const execution = humanCutDirectory(executions, executionId), startedAt = new Date().toISOString();
  createHumanCutIndex(path.join(execution, "start.json"), { schemaVersion: 2, executionId, submissionHash: digest,
    firstReceivedAt: record.receivedAt, receivedAt: input.receivedAt, startedAt });
  return { directory, execution, executionId, startedAt, receivedAt: input.receivedAt, record, startedMono: performance.now() };
}

export function finishGuidedOperation(operation: ReturnType<typeof guidedOperation>, result: Record<string, unknown>): void {
  createHumanCutIndex(path.join(operation.execution, "result.json"), { schemaVersion: 2, executionId: operation.executionId,
    completedAt: new Date().toISOString(), elapsedMs: performance.now() - operation.startedMono, ...result });
}

export function buildGuidedCutDecision(cut: GuidedCutObservation, submission: GuidedCutSubmissionV2,
  operation: ReturnType<typeof guidedOperation>): GuidedCutDecisionV2 {
  saveHumanCutJobSnapshot(cut.job.ctx.dir, cut);
  return parseGuidedCutDecision({ schemaVersion: 2, kind: "guided-cut-decision", scope: "cut-only-await-treatment-not-delivery",
    producerDir: cut.job.ctx.dir, submission, originalJobHash: cut.sha256, contextHash: canonicalJsonSha256(cut.job.ctx),
    request: cut.request, runId: cut.receipt.runId, previewAttempt: cut.receipt.attempt,
    sourceSetDigest: cut.receipt.sourceSetDigest, sourceSetReceiptHash: cut.receipt.sourceSetReceiptHash,
    submittedAt: operation.record.receivedAt, nextToken: operation.record.nextToken });
}
