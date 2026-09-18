import { mkdirSync, writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import path from "node:path";
import type { AutoEditJob } from "@/lib/server/auto-edit-job-types";
import type { CutApprovalRequestV1 } from "@/lib/producer/contracts/cut-approval-request";
import type { ProjectMutationLease } from "@/lib/server/project-mutation-lease";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import { pipelineAuthorityPath } from "@/lib/server/auto-edit-pipeline-authority";
import { autoEditJobPath, readAutoEditJob } from "@/lib/server/auto-edit-job-persistence";
import { stageTimingContext, stageTimingEnv, withStageTimingContext } from "@/lib/server/stage-timing-context";
import { timedStage } from "@/lib/server/stage-timing";
import { pythonInterpreter } from "../../_lib/spawn-python";
import { assertCutApprovalRequestCurrent } from "./cut-approval-request";
import { cutPreviewLeaseGuard } from "./cut-preview-lease";
import { CutPreviewProcessError, runCutPreviewProcess } from "./cut-preview-process";
import {
  assertCutPreviewDirectory, observeCutPreviewFile, readCurrentCutPreview, readCutPreviewObject,
  type CutPreviewReceiptV1,
} from "./cut-preview-receipt";

export interface PrivateCutPreviewInput {
  job: AutoEditJob;
  request: CutApprovalRequestV1;
  lease: ProjectMutationLease;
  /** Only shrinks further; renderer caps the source-aspect long edge to 960px. */
  proxyScale?: number;
  timeoutMs?: number;
}

/** Honest initial class; source retiming needs separate picture/audio qualification. */
export const PRIVATE_CUT_PREVIEW_CAPABILITIES = Object.freeze({
  sourceSpeeds: Object.freeze([1]), maxDurationSeconds: 1200, maxCuts: 500,
  maxSourceFps: 60, maxLongEdgePixels: 960, color: "yuv420p-no-declared-HDR-ungraded" as const,
  finishing: "ungraded-unmixed-not-delivery" as const,
});

function assertSupportedCut(input: PrivateCutPreviewInput): void {
  const plan = readCutPreviewObject(input.job.ctx.planPath).value;
  if (!Array.isArray(plan.cutTrack) || plan.cutTrack.some((row) => !row || typeof row !== "object" || (row.speed ?? 1) !== 1)) {
    throw new Error("Private cut preview currently supports source speed 1 only; nonunity retiming is not qualified. Do not silently change the approved cut.");
  }
}

function currentJob(input: PrivateCutPreviewInput): void {
  const current = readAutoEditJob(autoEditJobPath(input.job.ctx.dir));
  if (!current || current.token !== input.job.token || current.status !== "running"
      || current.attempts !== input.job.attempts || current.requestKey !== input.job.requestKey) {
    throw new Error("cut preview worker no longer owns the running job");
  }
  assertCutApprovalRequestCurrent(current, input.request);
}

function realChildDirectory(parent: string, name: string): string {
  assertCutPreviewDirectory(parent);
  const directory = path.join(parent, name);
  try { mkdirSync(directory, { mode: 0o700 }); }
  catch (error) { if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error; }
  assertCutPreviewDirectory(directory);
  return directory;
}

function invocation(input: PrivateCutPreviewInput) {
  const proxyScale = input.proxyScale ?? 1;
  const timeoutMs = input.timeoutMs ?? 600_000;
  if (!Number.isFinite(proxyScale) || proxyScale <= 0 || proxyScale > 1
      || !Number.isInteger(timeoutMs) || timeoutMs < 1000 || timeoutMs > 900_000) {
    throw new Error("cut preview requires bounded scale and 1..900 second deadline");
  }
  const identity = { requestHash: input.request.requestHash,
    runId: input.job.artifactToken ?? input.job.token, attempt: input.job.attempts,
    createdAt: new Date().toISOString(), executionNonce: randomUUID(),
    proxyScale, pipelineDigest: input.job.ctx.pipeline?.digest ?? null };
  const executionKey = canonicalJsonSha256(identity);
  const root = realChildDirectory(input.job.ctx.dir, "cut-previews");
  const requestDir = realChildDirectory(root, input.request.requestHash);
  const outputDir = path.join(requestDir, executionKey);
  mkdirSync(outputDir, { mode: 0o700 }); // Never reuse an existing attempt.
  const { requestHash: _requestHash, ...execution } = identity;
  const value = { schemaVersion: 1, request: input.request, ...execution, executionKey,
    producerDir: input.job.ctx.dir, planPath: input.job.ctx.planPath,
    manifestPath: input.job.ctx.manifestPath, timeoutSeconds: Math.ceil(timeoutMs / 1000) };
  const inputPath = path.join(outputDir, "input.json");
  writeFileSync(inputPath, `${JSON.stringify(value)}\n`, { flag: "wx", mode: 0o600 });
  return { outputDir, inputPath, value, timeoutMs };
}

function failure(directory: string, error: unknown): void {
  const details = error instanceof CutPreviewProcessError ? error.details : undefined;
  try {
    assertCutPreviewDirectory(directory);
    writeFileSync(path.join(directory, "controller-failure.json"), JSON.stringify({
      schemaVersion: 1, kind: "cut-preview-controller-failure",
      error: String(error).slice(-1000), timedOut: details?.timedOut ?? false,
      groupStopped: details?.groupStopped ?? null,
      stderrTail: details?.stderr.slice(-2000) ?? "",
    }), { flag: "wx", mode: 0o600 });
  } catch { /* Failed artifacts remain; diagnostics cannot replace the controlling error. */ }
}

function assertReceiptContext(input: PrivateCutPreviewInput, receipt: CutPreviewReceiptV1, output: ReturnType<typeof invocation>, script: string) {
  const manifest = readCutPreviewObject(input.job.ctx.manifestPath).value;
  const admission = manifest.sourceSetAdmission as Record<string, unknown>;
  const runtime = readCutPreviewObject(path.join(output.outputDir, "toolchain.json")).value;
  const binaries = runtime.binaries as Record<string, string>;
  const files = runtime.files as { path: string; sha256: string }[];
  if (receipt.executionKey !== output.value.executionKey || receipt.runId !== output.value.runId
      || receipt.attempt !== output.value.attempt || receipt.createdAt !== output.value.createdAt
      || receipt.sourceSetDigest !== admission?.sourceSetDigest || receipt.sourceSetReceiptHash !== admission?.receiptSha256
      || runtime.kind !== "cut-preview-toolchain-v1" || runtime.pipelineDigest !== (input.job.ctx.pipeline?.digest ?? null)
      || !binaries?.ffmpeg || !binaries?.ffprobe || !binaries?.python
      || ![script, binaries.ffmpeg, binaries.ffprobe, binaries.python].every((file) => files.some((row) => row.path === file))) {
    throw new Error("cut preview receipt does not bind the actual invocation/source/toolchain");
  }
}

/** Private foundation only: caller owns the lease; never pause, accept or promote. */
export async function renderPrivateCutPreview(input: PrivateCutPreviewInput): Promise<{ directory: string; receipt: CutPreviewReceiptV1 }> {
  const assertLease = cutPreviewLeaseGuard(input.job.ctx.dir, input.lease);
  currentJob(input);
  assertSupportedCut(input);
  const script = pipelineAuthorityPath(input.job.ctx, "scripts/producer/cut_preview.py");
  observeCutPreviewFile(script, 16 * 1024 * 1024); // Old snapshots fail, never use current-repo fallback.
  const output = invocation(input);
  const currentTiming = stageTimingContext();
  return withStageTimingContext({ ...currentTiming, runId: input.job.artifactToken ?? input.job.token,
    attemptId: input.job.token, attemptNo: input.job.attempts }, () =>
    timedStage(input.job.ctx.dir, "cut_preview", async () => {
      try {
        assertLease();
        const env = { ...stageTimingEnv(), PYTHONPATH: path.dirname(script),
          ...(input.job.ctx.pipeline ? { SNIPER_PIPELINE_ROOT: input.job.ctx.pipeline.snapshotRoot } : {}) };
        await runCutPreviewProcess({ command: pythonInterpreter(), args: [script, output.inputPath],
          cwd: path.dirname(script), env, timeoutMs: output.timeoutMs });
        assertLease(); currentJob(input);
        const receipt = readCurrentCutPreview(output.outputDir, input.request);
        assertReceiptContext(input, receipt, output, script);
        return { directory: output.outputDir, receipt };
      } catch (error) { failure(output.outputDir, error); throw error; }
    }));
}
