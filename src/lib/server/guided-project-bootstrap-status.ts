/** Read retained new-only launch evidence; never start/recover/accept a job on a status call. */
import path from "node:path";
import { lstatSync } from "node:fs";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { autoEditJobPath, parseAutoEditJobRecord } from "./auto-edit-job-persistence";
import { assertBootstrapJob, readBootstrapIntake, BOOTSTRAP_FAILURE, bootstrapCleanupUnknown } from "./guided-project-bootstrap-store";
import { observeGuidedCutV2 } from "./guided-cut-v2-store";

function present(file: string): boolean {
  try { lstatSync(file); return true; }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return false; throw error; }
}

export function readGuidedProjectBootstrapStatus(dir: string) {
  const intake = readBootstrapIntake(dir), jobPath = autoEditJobPath(dir);
  const failurePath = path.join(path.dirname(dir), BOOTSTRAP_FAILURE);
  const failure = present(failurePath) ? readCutPreviewObject(failurePath).value : null;
  const cleanupUnknown = bootstrapCleanupUnknown(dir);
  const held = present(jobPath) ? readCutPreviewObject(jobPath) : null;
  const job = held ? parseAutoEditJobRecord(held.value) : null;
  if (job) assertBootstrapJob(job);
  const state = failure || cleanupUnknown ? "failed-or-unknown-no-relaunch" : job?.status ?? "incomplete-no-relaunch";
  let preview: { requestHash: string; executionKey: string; receiptHash: string } | null = null;
  if (job?.status === "awaiting_cut_approval" && !failure && !cleanupUnknown) {
    const current = observeGuidedCutV2(dir);
    if (current.sha256 !== held!.sha256) throw new Error("Bootstrap pause journal changed during readback");
    preview = { requestHash: current.request.requestHash, executionKey: current.receipt.executionKey, receiptHash: current.receipt.receiptHash };
  }
  if (held && readCutPreviewObject(jobPath).sha256 !== held.sha256) throw new Error("Bootstrap status journal changed");
  if (present(failurePath) !== (failure !== null)) throw new Error("Bootstrap cleanup state changed during status");
  if (bootstrapCleanupUnknown(dir) !== cleanupUnknown) throw new Error("Bootstrap unknown-cleanup state changed during status");
  return { scope: "guided-project-bootstrap-status-not-approval", producerDir: dir, state,
    idempotencyKey: intake.request.idempotencyKey, requestHash: intake.requestHash,
    journalHash: held?.sha256 ?? null, preview, failure, cleanupUnknown,
    sourceFreshness: "not-requalified-by-status", retryable: false, cutAccepted: false,
    approvalGranted: false, note: "Existing requests never launch again; ambiguous/partial state requires explicit recovery." };
}
