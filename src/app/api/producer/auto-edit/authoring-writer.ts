/** The existing writer lifecycle, including ordinary timeout draft recovery. */
import { readFileSync } from "node:fs";
import { reconcileGraphicIds, type EditPlan } from "@/lib/producer/edit-plan";
import { autoEditWorkbench } from "@/lib/producer/auto-edit-delivery-policy";
import { atomicWriteJsonSync } from "@/lib/server/atomic-file";
import { planContentHash } from "@/lib/server/auto-edit-authority";
import { assertAuthoredBootstrapDraft } from "@/lib/server/guided-project-bootstrap-guard";
import { brainModel, brainProvider, brainProviderLabel } from "../../_lib/ai-provider";
import type { AuthoringResult, AuthoringSessionMode, AuthoringStage } from "./authoring";
import type { AuthoringRuntime, AuthoringStageDependencies } from "./authoring-stage";
import { currentCutPlanState, type CutPlanState } from "./authoring-cut-state";
import { AUTHORING_TIMEOUT_MIN } from "./claude-authoring-process";
import { AutoEditError } from "./stream";

export const authoringWriterGuards = { authoredDraft: assertAuthoredBootstrapDraft };

function normalizeGraphicBindings(planPath: string): void {
  try {
    const value = JSON.parse(readFileSync(planPath, "utf8")) as EditPlan;
    if (!value || typeof value !== "object" || Array.isArray(value)) return;
    const normalized = reconcileGraphicIds(value).plan;
    if (normalized !== value) atomicWriteJsonSync(planPath, normalized);
  } catch {
    // Preserve the authoring result as the controlling failure. A malformed or
    // partial timeout draft is rejected by planState instead of masking the
    // deadline with a JSON parse error.
  }
}

function timeoutMessage(result: AuthoringResult, stage: AuthoringStage): string {
  const brain = brainProviderLabel(result.provider);
  return `${stage} authoring timed out after ${AUTHORING_TIMEOUT_MIN} min — ${brain} was killed. ${result.errTail.slice(-300)}`;
}

function writerFailure(result: AuthoringResult, stage: AuthoringStage): AutoEditError {
  return new AutoEditError(`${brainProviderLabel(result.provider)} ${stage} authoring failed `
    + `(exit ${result.code}). ${result.errTail.slice(-300)}`);
}

/** Start exactly the same ordinary writer events and checkpoint as before. */
function beginWriter(run: AuthoringRuntime, stage: AuthoringStage): void {
  const { ctx } = run.job;
  const provider = brainProvider();
  const brain = brainProviderLabel(provider);
  run.job = run.io.advance({
    checkpoint: "authoring", phase: "authoring",
    message: stage === "cut"
      ? `${brain} is approving transcript-safe cuts before any visual planning.`
      : `${brain} is adding retention and visual treatment without changing approved cuts.`,
  });
  run.io.send({ event: "authoring_started", stage, provider,
    model: brainModel(provider), brain, workbench: autoEditWorkbench(ctx) });
}

/** Transport/editor failures precede any binding, normalization, or recovery. */
function assertWriterOutcome(run: AuthoringRuntime, result: AuthoringResult,
  options: { stage: AuthoringStage; authoredCut: boolean }): void {
  if (result.protocolFailure || result.providerFailure) throw new AutoEditError(result.protocolFailure || result.providerFailure!);
  if (result.blocked) {
    const message = `${result.blocked.marker} ${result.blocked.reason}`;
    run.io.send({ event: "authoring_blocked", stage: options.stage, provider: result.provider, reason: result.blocked.reason, message });
    throw new AutoEditError(message);
  }
  if (!options.authoredCut) return;
  if (result.code !== 0 && !result.timedOut) throw writerFailure(result, options.stage);
  authoringWriterGuards.authoredDraft(run.job);
}

function recoveredState(run: AuthoringRuntime, deps: AuthoringStageDependencies,
  options: { beforeContentHash: string | undefined; result: AuthoringResult; stage: AuthoringStage }): CutPlanState | null {
  const { beforeContentHash, result, stage } = options;
  const state = currentCutPlanState(run, deps);
  if (!state || state.contentHash === beforeContentHash) return null;
  run.io.send({
    event: "authoring_deadline_recovered", stage,
    provider: result.provider, model: brainModel(result.provider), ms: result.ms,
    planHash: state.fileHash, planContentHash: state.contentHash,
    note: `${stage} draft recovered only as a pre-approval candidate.`,
  });
  return state;
}

/** Author once; an eligible authored bootstrap must pass its source/seed wall first. */
export async function runWriter(run: AuthoringRuntime, deps: AuthoringStageDependencies,
  stage: AuthoringStage, sessionMode: AuthoringSessionMode): Promise<CutPlanState> {
  const { ctx } = run.job;
  const authoredCut = ctx.authoredCut !== undefined;
  const beforeContentHash = planContentHash(ctx.planPath);
  beginWriter(run, stage);
  const result = await deps.author(ctx, run.io.send, stage, sessionMode);
  assertWriterOutcome(run, result, { stage, authoredCut });
  if (result.sessionEstablished && deps.bindSession) run.job = deps.bindSession(run.job);
  if (deps.exists(ctx.planPath)) normalizeGraphicBindings(ctx.planPath);
  let state = currentCutPlanState(run, deps);
  if (result.timedOut) {
    state = recoveredState(run, deps, { beforeContentHash, result, stage });
    if (!state) throw new AutoEditError(timeoutMessage(result, stage));
  } else if (result.code !== 0) {
    throw writerFailure(result, stage);
  }
  if (!state) throw new AutoEditError(
    `${brainProviderLabel(result.provider)} exited 0 but wrote no valid ${ctx.planPath}`,
  );
  run.io.send({ event: "authoring_done", stage, provider: result.provider,
    model: brainModel(result.provider), ms: result.ms, authored: result.authored });
  return state;
}
