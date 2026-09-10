import path from "node:path";
import type { AutoEditJob } from "@/lib/server/auto-edit-job-types";
import type { CutApprovalRequestV1 } from "@/lib/producer/contracts/cut-approval-request";
import type { ProjectMutationLease } from "@/lib/server/project-mutation-lease";
import { pipelineAuthorityPath } from "@/lib/server/auto-edit-pipeline-authority";
import { stageTimingEnv, withStageTimingFallback } from "@/lib/server/stage-timing-context";
import { timedStage } from "@/lib/server/stage-timing";
import { generationChildTimeout } from "@/lib/server/generation-attempt-clock";
import { pythonInterpreter } from "../../_lib/spawn-python";
import { assertCutApprovalRequestCurrent } from "./cut-approval-request";
import { cutPreviewLeaseGuard } from "./cut-preview-lease";
import { runCutPreviewProcess } from "./cut-preview-process";
import { observeCutPreviewFile, readCurrentCutPreview, readCutPreviewObject } from "./cut-preview-receipt";

export interface CutPreviewVerificationInput {
  job: AutoEditJob;
  request: CutApprovalRequestV1;
  executionKey: string;
  lease: ProjectMutationLease;
  remainingMs?: () => number;
}

/** Acceptance-side read-only full admitted-byte check; never render or write authority. */
export async function verifyCutPreviewSources(input: CutPreviewVerificationInput): Promise<void> {
  generationChildTimeout(120_000, input.remainingMs);
  const assertLease = cutPreviewLeaseGuard(input.job.ctx.dir, input.lease);
  assertCutApprovalRequestCurrent(input.job, input.request);
  if (!/^[a-f0-9]{64}$/.test(input.executionKey)) throw new Error("cut preview execution key is malformed");
  const directory = path.join(input.job.ctx.dir, "cut-previews", input.request.requestHash, input.executionKey);
  const receipt = readCurrentCutPreview(directory, input.request);
  const invocation = readCutPreviewObject(path.join(directory, "input.json")).value;
  if (invocation.producerDir !== input.job.ctx.dir || invocation.planPath !== input.job.ctx.planPath
      || invocation.manifestPath !== input.job.ctx.manifestPath || invocation.executionKey !== input.executionKey
      || invocation.pipelineDigest !== (input.job.ctx.pipeline?.digest ?? null)) {
    throw new Error("cut preview verification invocation differs from the durable job");
  }
  const script = pipelineAuthorityPath(input.job.ctx, "scripts/producer/cut_preview.py");
  observeCutPreviewFile(script, 16 * 1024 * 1024);
  await withStageTimingFallback({ runId: input.job.artifactToken ?? input.job.token,
    attemptId: input.job.token, attemptNo: input.job.attempts }, () =>
    timedStage(input.job.ctx.dir, "cut_preview_source_reobservation", async () => {
    assertLease();
    const result = await runCutPreviewProcess({ command: pythonInterpreter(),
      args: [script, path.join(directory, "input.json"), "--verify-sources"], cwd: path.dirname(script),
      env: { ...stageTimingEnv(), PYTHONPATH: path.dirname(script),
        ...(input.job.ctx.pipeline ? { SNIPER_PIPELINE_ROOT: input.job.ctx.pipeline.snapshotRoot } : {}) },
      timeoutMs: generationChildTimeout(120_000, input.remainingMs) });
    const event = JSON.parse(result.stdout.trim());
    if (event.status !== "cut_preview_sources_current" || event.requestHash !== input.request.requestHash
        || event.executionKey !== input.executionKey || event.sourceSetDigest !== receipt.sourceSetDigest
        || event.sourceSetReceiptHash !== receipt.sourceSetReceiptHash || event.manifestHash !== receipt.manifestHash) {
      throw new Error("cut preview source reobservation did not bind the expected receipt");
    }
    assertLease();
    assertCutApprovalRequestCurrent(input.job, input.request);
    readCurrentCutPreview(directory, input.request);
  }));
}
