import path from "node:path";
import type { AutoEditJob } from "./auto-edit-job-types";
import type { ProjectMutationLease } from "./project-mutation-lease";
import { autoEditAuthoritySnapshot } from "./auto-edit-authority-snapshot";
import { pipelineAuthorityPath } from "./auto-edit-pipeline-authority";
import { stageTimingContext, stageTimingEnv, withStageTimingContext } from "./stage-timing-context";
import { timedStage } from "./stage-timing";
import { activeHumanCutAcceptance, assertHumanCutContext } from "./human-cut-acceptance-store";
import { pythonInterpreter } from "@/app/api/_lib/spawn-python";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { runCutPreviewProcess } from "@/app/api/producer/auto-edit/cut-preview-process";

// Read-only use of the pinned existing admission implementation. The current
// visual plan is independently hash-bound, never forged into an old cut request.
const VERIFY_CURRENT_SOURCES = [
  "import json,sys",
  "from cut_preview_io import bound_json",
  "from ingest_execution_authority import execution_media_authority_entries",
  "plan=bound_json(__import__('pathlib').Path(sys.argv[1]),sys.argv[2])",
  "manifest=bound_json(__import__('pathlib').Path(sys.argv[3]),sys.argv[4])",
  "entries=execution_media_authority_entries(plan,manifest,sys.argv[3])",
  "if not entries: raise RuntimeError('accepted cut requires fully admitted source bytes; re-ingest is required')",
  "binding=manifest['sourceSetAdmission']",
  "print(json.dumps({'status':'accepted_cut_sources_current','planHash':sys.argv[2],'manifestHash':sys.argv[4]," +
    "'sourceSetDigest':binding['sourceSetDigest'],'sourceSetReceiptHash':binding['receiptSha256']}))",
].join("\n");

/** Reobserve actual source bytes before accepted-worker model work, including after visual expansion. */
export async function verifyHumanAcceptedSourceBytes(input: { job: AutoEditJob; lease: ProjectMutationLease }): Promise<void> {
  const { job, lease } = input;
  const guard = cutPreviewLeaseGuard(job.ctx.dir, lease), fact = activeHumanCutAcceptance(job);
  const before = autoEditAuthoritySnapshot(job.ctx);
  if (!before.planHash || before.manifestHash !== fact.preview.manifestHash) throw new Error("Accepted cut source verification lost its plan/manifest identity");
  const sourceModule = pipelineAuthorityPath(job.ctx, "scripts/producer/ingest_execution_authority.py");
  observeCutPreviewFile(sourceModule, 16 * 1024 * 1024);
  observeCutPreviewFile(path.join(path.dirname(sourceModule), "cut_preview_io.py"), 16 * 1024 * 1024);
  await withStageTimingContext({ ...stageTimingContext(), runId: job.artifactToken ?? job.token,
    attemptId: job.token, attemptNo: job.attempts }, () => timedStage(job.ctx.dir, "human_accepted_cut_sources", async () => {
    guard();
    const result = await runCutPreviewProcess({ command: pythonInterpreter(),
      args: ["-c", VERIFY_CURRENT_SOURCES, job.ctx.planPath, before.planHash!, job.ctx.manifestPath, fact.preview.manifestHash],
      cwd: path.dirname(sourceModule), timeoutMs: 120_000,
      env: { ...stageTimingEnv(), PYTHONPATH: path.dirname(sourceModule),
        ...(job.ctx.pipeline ? { SNIPER_PIPELINE_ROOT: job.ctx.pipeline.snapshotRoot } : {}) } });
    const observed = JSON.parse(result.stdout.trim());
    if (Object.keys(observed).sort().join(",") !== "manifestHash,planHash,sourceSetDigest,sourceSetReceiptHash,status"
        || observed.status !== "accepted_cut_sources_current" || observed.planHash !== before.planHash
        || observed.manifestHash !== fact.preview.manifestHash || observed.sourceSetDigest !== fact.preview.sourceSetDigest
        || observed.sourceSetReceiptHash !== fact.preview.sourceSetReceiptHash) throw new Error("Accepted cut source verification returned mismatched proof");
    guard(); assertHumanCutContext(job, fact);
    if (autoEditAuthoritySnapshot(job.ctx).digest !== before.digest) throw new Error("Accepted cut authority changed during source verification");
  }));
}
