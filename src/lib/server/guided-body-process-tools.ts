import path from "node:path";
import { realpathSync } from "node:fs";
import { runCutPreviewProcess } from "@/app/api/producer/auto-edit/cut-preview-process";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { sha256 } from "@/lib/producer/contracts/validation";
import { openingPythonIdentity } from "./guided-opening-process";
import { openingRuntimeEnvironment } from "./guided-opening-runtime-control";
import { observeHistoricalProposalSnapshot, observeHistoricalPipelineSnapshot } from "./guided-proposal-history-snapshot";
import { readGuidedObject } from "./guided-cut-v2-store";
import { OWNED_PROCESS_LEDGER_ENV, ownedProcessLedgerPath } from "./guided-opening-process-ledger";
import { stageTimingEnv } from "./stage-timing-context";
import type { readGuidedBodyActivation } from "./guided-body-activation";

export type BodyActivation = ReturnType<typeof readGuidedBodyActivation>;
export type BodyExecutionControl = Pick<BodyActivation, "current" | "activation" | "activationHash" | "activationPath" | "activationSha256" | "controlJob">;
export type BodyChildPurpose = "media" | "cleanup" | "read";

/** Select exact original-pipeline workers; no fallback to a new current file for a historical execution. */
function selectBodyChildTools(held: BodyExecutionControl, purpose: BodyChildPurpose) {
  const job = held.controlJob, pipeline = job.ctx.pipeline;
  if (!pipeline) throw new Error("Body execution has no pinned pipeline");
  if ("admission" in held) {
    const proposal = readGuidedObject(job.ctx.dir, job.guidedHandoffV2!.treatmentProposalHash!);
    observeHistoricalProposalSnapshot(pipeline, readGuidedObject(job.ctx.dir, sha256(proposal.compilerAuthorityHash, "compilerAuthorityHash")));
  } else observeHistoricalPipelineSnapshot(pipeline);
  const relative = `scripts/producer/guided_body_${purpose}.py`, wrapper = "scripts/producer/headless/process_runner.py";
  const script = path.join(pipeline.snapshotRoot, relative), runnerScript = path.join(pipeline.snapshotRoot, wrapper);
  const scriptHash = observeCutPreviewFile(script, 1024 * 1024).sha256, runnerScriptHash = observeCutPreviewFile(runnerScript, 1024 * 1024).sha256;
  if (!pipeline.files.some((row) => row.path === relative && row.hash === scriptHash)
      || !pipeline.files.some((row) => row.path === wrapper && row.hash === runnerScriptHash)) {
    throw new Error("Body worker/lifecycle wrapper is absent from the original pinned closure");
  }
  return { script, scriptHash, runnerScript, runnerScriptHash, ...openingPythonIdentity() };
}

/** Code-only tool/runtime/OS TEST leaves; no input can replace phase, result, lease or CAS authority. */
export const bodyProcessToolLeaves = { select: selectBodyChildTools, runtime: openingRuntimeEnvironment, run: runCutPreviewProcess };

/** Keep the original pinned selection policy; tests may supply explicitly inert native tool identities. */
export function bodyChildTools(held: BodyExecutionControl, purpose: BodyChildPurpose) {
  return bodyProcessToolLeaves.select(held, purpose);
}

export function assertBodyToolsUnchanged(tools: ReturnType<typeof bodyChildTools>): void {
  if (observeCutPreviewFile(tools.script, 1024 * 1024).sha256 !== tools.scriptHash
      || observeCutPreviewFile(tools.runnerScript, 1024 * 1024).sha256 !== tools.runnerScriptHash
      || realpathSync(tools.python) !== tools.pythonResolved
      || observeCutPreviewFile(tools.pythonResolved, 256 * 1024 * 1024).sha256 !== tools.pythonHash
      || observeCutPreviewFile(tools.venvConfig, 64 * 1024).sha256 !== tools.venvConfigHash) {
    throw new Error("Body pinned worker/interpreter bytes changed");
  }
}

/** Exactly one group and mandatory wrapper even with zero nested helpers. Cleanup has separate protected accounting. */
export function invokeBodyChild(input: { held: BodyExecutionControl; purpose: BodyChildPurpose; tools: ReturnType<typeof bodyChildTools>;
  remainingMs: () => number; extraArgs?: string[]; ledgerRoot?: string }) {
  const { held, purpose, tools } = input, activation = held.activation, root = path.dirname(held.activationPath);
  if (purpose !== "cleanup" && !("admission" in held)) throw new Error("Reduced body control permits cleanup only, never media/readback");
  const runtime = bodyProcessToolLeaves.runtime(activation.runtime), timeoutMs = input.remainingMs();
  const seconds = Math.max(1, timeoutMs - 250) / 1000;
  return bodyProcessToolLeaves.run({ command: tools.python, args: [tools.runnerScript, tools.script, activation.inputPath, activation.outputRoot,
    "--input-sha256", activation.inputSha256, "--execution-activation", held.activationPath,
    "--execution-activation-sha256", held.activationSha256, ...(input.extraArgs ?? []), "--timeout-seconds", String(seconds)],
    cwd: path.dirname(tools.script), env: { ...stageTimingEnv(), ...runtime, PYTHONPATH: path.dirname(tools.script),
      SNIPER_PIPELINE_ROOT: held.controlJob.ctx.pipeline!.snapshotRoot,
      [OWNED_PROCESS_LEDGER_ENV]: ownedProcessLedgerPath(input.ledgerRoot ?? root, purpose),
      PYTHONDONTWRITEBYTECODE: "1", PYTHONHOME: undefined, PYTHONNOUSERSITE: "1" },
    timeoutMs: input.remainingMs(), purpose: purpose === "cleanup" ? "cut-preview" : "guided-body" });
}
