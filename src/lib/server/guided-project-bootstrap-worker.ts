/** Existing worker integration: fresh source verification, observed process scope, no alternative author. */
import path from "node:path";
import { pythonInterpreter } from "@/app/api/_lib/spawn-python";
import { runCutPreviewProcess, CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import type { AutoEditJob } from "./auto-edit-job-types";
import type { ProjectMutationLease } from "./project-mutation-lease";
import { pipelineAuthorityPath } from "./auto-edit-pipeline-authority";
import { stageTimingEnv } from "./stage-timing-context";
import { assertBootstrapCurrent } from "./guided-project-bootstrap-guard";
import { BootstrapCleanupError, assertBootstrapQuiescent, withBootstrapProcessScope } from "./guided-project-bootstrap-observer";
import { assertBootstrapJob, retainBootstrapFailure, bootstrapCleanupUnknown, BOOTSTRAP_FAILURE } from "./guided-project-bootstrap-store";
import { assertExistingCutContext, hasGuidedBootstrap } from "./guided-project-bootstrap-contract";
import { authoredPreparationRemainingMs } from "./guided-project-preparation-deadline";

const VERIFY = ["import json,sys", "from pathlib import Path", "from cut_preview_io import bound_json",
  "from ingest_execution_authority import execution_media_authority_entries",
  "plan=bound_json(Path(sys.argv[1]),sys.argv[2])", "manifest=bound_json(Path(sys.argv[3]),sys.argv[4])",
  "entries=execution_media_authority_entries(plan,manifest,sys.argv[3])",
  "if not entries: raise RuntimeError('bootstrap requires fully admitted current source bytes')",
  "print(json.dumps({'status':'bootstrap_sources_current','planHash':sys.argv[2],'manifestHash':sys.argv[4]}))"].join("\n");
const retainedLeases = new WeakSet<AutoEditJob>();

function retainWorkerFailure(job: AutoEditJob, error: unknown, cleanup: { verified: boolean; forcedStop: boolean }): void {
  if (!cleanup.verified) retainedLeases.add(job);
  try { retainBootstrapFailure(job.ctx.dir, error, cleanup); }
  catch (cause) { retainedLeases.add(job); throw cause; }
}

/** Exact parent-held candidate/manifest hashes are inputs, never generated replacement authority. */
export async function verifyBootstrapSources(job: AutoEditJob, lease: ProjectMutationLease): Promise<void> {
  const intake = assertBootstrapJob(job), guard = cutPreviewLeaseGuard(job.ctx.dir, lease);
  const source = pipelineAuthorityPath(job.ctx, "scripts/producer/ingest_execution_authority.py");
  const expected = { status: "bootstrap_sources_current", planHash: job.ctx.authoredCut?.initialPlanSha256 ?? job.ctx.existingCutCandidate!.savedPlanSha256,
    manifestHash: intake.request.manifest.sha256 };
  guard(); assertBootstrapCurrent(job);
  const result = await runCutPreviewProcess({ command: pythonInterpreter(),
    args: ["-c", VERIFY, job.ctx.planPath, expected.planHash, job.ctx.manifestPath, expected.manifestHash],
    cwd: path.dirname(source), timeoutMs: Math.min(120_000, authoredPreparationRemainingMs(job.ctx) ?? 120_000), trackForShutdown: true,
    env: { ...stageTimingEnv(), PYTHONPATH: path.dirname(source), SNIPER_PIPELINE_ROOT: job.ctx.pipeline!.snapshotRoot } });
  const actual = JSON.parse(result.stdout.trim());
  if (JSON.stringify(Object.keys(actual).sort()) !== JSON.stringify(Object.keys(expected).sort())
      || actual.status !== expected.status || actual.planHash !== expected.planHash || actual.manifestHash !== expected.manifestHash) {
    throw new Error("Bootstrap source verifier returned a mismatched observation");
  }
  guard(); assertBootstrapCurrent(job); await assertBootstrapQuiescent();
}

/** Forced outer-group stop does NOT establish absence of nested Python sessions. */
export function bootstrapFailureCleanup(error: unknown): { verified: boolean; forcedStop: boolean } {
  if (error instanceof CutPreviewProcessError) return {
    verified: error.details.groupStopped && !error.details.forcedStop, forcedStop: error.details.forcedStop };
  if (error instanceof BootstrapCleanupError) {
    const original = error.original ? bootstrapFailureCleanup(error.original) : { verified: true, forcedStop: false };
    return { verified: error.observation.clean && !error.nestedUncertain && original.verified,
      forcedStop: error.observation.forced || original.forcedStop };
  }
  return { verified: true, forcedStop: false }; // Used only after successful scope settlement.
}

/** Fixed runtime hooks for unit mocking only. No production dependency or source-verification override argument. */
export const bootstrapWorkerServices = { verifySources: verifyBootstrapSources };

export async function runBootstrapWorker(job: AutoEditJob, lease: ProjectMutationLease, run: () => Promise<void>): Promise<void> {
  assertExistingCutContext(job.ctx);
  if (!hasGuidedBootstrap(job.ctx)) return run();
  const onLate = () => retainWorkerFailure(job, "Late subprocess registration invalidated bootstrap quiescence",
    { verified: false, forcedStop: true });
  try {
    await withBootstrapProcessScope(async () => {
      authoredPreparationRemainingMs(job.ctx);
      await bootstrapWorkerServices.verifySources(job, lease);
      await run();
      authoredPreparationRemainingMs(job.ctx);
    }, onLate);
  } catch (error) {
    const cleanup = bootstrapFailureCleanup(error);
    retainWorkerFailure(job, error instanceof Error ? error.message : "Bootstrap failed", cleanup);
    throw error;
  }
}

/** Failure marker is independently read: persistence errors/late unknown work retain the worker lease. */
export function bootstrapMayReleaseLease(job: AutoEditJob): boolean {
  if (!hasGuidedBootstrap(job.ctx)) return true;
  if (retainedLeases.has(job)) return false;
  try {
    if (bootstrapCleanupUnknown(job.ctx.dir)) return false;
    const row = readCutPreviewObject(path.join(path.dirname(job.ctx.dir), BOOTSTRAP_FAILURE)).value;
    return row.cleanupVerified === true;
  } catch (error) { return (error as NodeJS.ErrnoException).code === "ENOENT"; }
}
