/** Bootstrap-only durable PAUSE guard. A retained failure revokes usability, never erases evidence. */
import path from "node:path";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import type { CutApprovalRequestV1, CutPreviewPointer } from "@/lib/producer/contracts/cut-approval-request";
import { exactKeys, isoDate } from "@/lib/producer/contracts/validation";
import type { AutoEditJob } from "./auto-edit-job-types";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { atomicCreateJsonSync } from "./atomic-file";
import { assertBootstrapQuiescent } from "./guided-project-bootstrap-observer";
import { assertBootstrapJob, assertNoBootstrapFailure } from "./guided-project-bootstrap-store";
import { hasGuidedBootstrap } from "./guided-project-bootstrap-contract";
import { authoredPreparationRemainingMs, AUTHORED_PREPARATION_LIMIT_MS } from "./guided-project-preparation-deadline";

const FILE = "bootstrap-process-quiescence.json";

function bindings(job: AutoEditJob, request: CutApprovalRequestV1, preview: CutPreviewPointer) {
  return { schemaVersion: 1, kind: "guided-project-bootstrap-quiescence", producerDir: job.ctx.dir,
    token: job.artifactToken ?? job.token, requestKey: job.requestKey, contextHash: canonicalJsonSha256(job.ctx),
    requestHash: request.requestHash, previewExecutionKey: preview.executionKey, previewReceiptHash: preview.receiptHash,
    scope: "observed-registered-groups-not-human-approval", cleanupVerified: true };
}

/** Must run in the actual worker scope before its synchronous PAUSE transaction. */
export async function sealBootstrapPause(job: AutoEditJob, request: CutApprovalRequestV1, preview: CutPreviewPointer): Promise<void> {
  if (!hasGuidedBootstrap(job.ctx)) return;
  assertBootstrapJob(job); assertNoBootstrapFailure(job.ctx.dir);
  authoredPreparationRemainingMs(job.ctx);
  await assertBootstrapQuiescent(true);
  assertNoBootstrapFailure(job.ctx.dir);
  authoredPreparationRemainingMs(job.ctx);
  atomicCreateJsonSync(path.join(job.ctx.dir, FILE), { ...bindings(job, request, preview), recordedAt: new Date().toISOString() });
  assertNoBootstrapFailure(job.ctx.dir);
  authoredPreparationRemainingMs(job.ctx);
}

/** Omission stays legacy-only. Existence without the journal-held exact hash is never authority. */
export function bootstrapPauseHash(job: AutoEditJob, request: CutApprovalRequestV1, preview?: CutPreviewPointer): string | undefined {
  if (!hasGuidedBootstrap(job.ctx)) return undefined;
  if (job.status === "running") authoredPreparationRemainingMs(job.ctx);
  if (!preview) throw new Error("Bootstrap PAUSE lacks a qualified preview");
  assertNoBootstrapFailure(job.ctx.dir);
  const held = readCutPreviewObject(path.join(job.ctx.dir, FILE)), row = held.value;
  const expected = bindings(job, request, preview), keys = [...Object.keys(expected), "recordedAt"];
  exactKeys(row, keys, keys, "bootstrap quiescence"); isoDate(row.recordedAt, "quiescence recordedAt");
  if (job.ctx.authoredCut) {
    const began = Date.parse(job.ctx.authoredCut.preparationStartedAt), sealed = Date.parse(String(row.recordedAt));
    if (sealed < began || sealed >= began + AUTHORED_PREPARATION_LIMIT_MS) throw new Error("Authored cut PAUSE exceeded its original preparation window");
  }
  const { recordedAt: _at, ...actual } = row; void _at;
  if (canonicalJsonSha256(actual) !== canonicalJsonSha256(expected)) throw new Error("Bootstrap quiescence bindings changed");
  assertNoBootstrapFailure(job.ctx.dir);
  if (job.status === "running") authoredPreparationRemainingMs(job.ctx);
  return held.sha256;
}

/** Shared by strong pending/accepted readers and the final acceptance CAS. No fresh source claim. */
export function assertBootstrapQuiescence(job: AutoEditJob): void {
  if (!hasGuidedBootstrap(job.ctx)) return;
  if (!job.cutApprovalRequest || !job.bootstrapQuiescenceHash
      || bootstrapPauseHash(job, job.cutApprovalRequest, job.cutPreview) !== job.bootstrapQuiescenceHash) {
    throw new Error("Bootstrap lacks its exact journal-held quiescence fact");
  }
}
