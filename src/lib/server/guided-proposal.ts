import path from "node:path";
import { canonicalProducerDir } from "@/app/api/producer/auto-edit/request";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { verifyCutPreviewSources } from "@/app/api/producer/auto-edit/cut-preview-verification";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";
import { parseTreatmentCompileSubmissionV1 } from "@/lib/producer/contracts/raw-treatment-v1";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { readRawTreatmentAdmission } from "./guided-raw-treatment-store";
import { commitGuidedJob } from "./guided-cut-v2";
import { acquireGuidedMutation, guidedOperation, finishGuidedOperation, writeGuidedObject } from "./guided-cut-v2-store";
import { createHumanCutIndex, saveHumanCutJobSnapshot } from "./human-cut-acceptance-store";
import { prepareProposalEvidence } from "./guided-proposal-inputs";
import { buildProposalPrompt, proposalCompilerAuthority, runProposalBrain } from "./guided-proposal-compiler";
import { buildTreatmentCandidate } from "./guided-proposal-candidate";
import { PROPOSAL_SCOPE, readGuidedTreatmentProposal, type RawAdmission } from "./guided-proposal-store";
import { timedStage } from "./stage-timing";
import { withStageTimingContext } from "./stage-timing-context";
import { startProposalDeadline, type DeadlineClocks } from "./generation-deadline";
import { startGuardedProposalDeadline } from "./generation-clock-watermark";
import { CURRENT_TREATMENT_PROPOSAL_VERSION } from "@/lib/producer/contracts/treatment-proposal-v5";
import { nativeReferenceImages, type NativeReferenceSelection } from "./guided-native-references";
import type { DirectorBrain } from "./native-director-store";

interface Dependencies {
  verifySources: typeof verifyCutPreviewSources; brain: typeof runProposalBrain;
  /** Internal qualification seam only; request transport does not select schemas or relax checks. */
  proposalVersion?: 4 | 5 | 6 | 7 | 8 | 9 | 10;
  nativeReferences?: NativeReferenceSelection[];
  directorBrain?: DirectorBrain;
  fault?: (point: "after-brain" | "after-receipt" | "after-commit") => void;
  budgetClocks?: DeadlineClocks;
}
type CompileSubmission = ReturnType<typeof parseTreatmentCompileSubmissionV1>;
type Operation = ReturnType<typeof guidedOperation>;
type Lease = Awaited<ReturnType<typeof acquireGuidedMutation>>;
type ProposalBudget = ReturnType<typeof startProposalDeadline>;

function retained(dir: string, execution: string, name: string, value: unknown) {
  createHumanCutIndex(path.join(execution, name), value); return writeGuidedObject(dir, value);
}

/** Internal only. One explicit compile attempt, no provider retry, worker, root plan edit or final authority. */
export async function compileGuidedTreatmentProposal(input: { dir: unknown; submission: unknown }, overrides: Partial<Dependencies> = {}) {
  const submission = parseTreatmentCompileSubmissionV1(structuredClone(input.submission)), receivedAt = new Date().toISOString();
  const dir = canonicalProducerDir(input.dir), cut = readRawTreatmentAdmission(dir);
  if (cut.pointer.treatmentProposalHash) {
    const prior = readGuidedTreatmentProposal(dir);
    if (canonicalJsonSha256(prior.compileSubmission) !== canonicalJsonSha256(submission)) throw new Error("A different proposal already exists; explicit future revision is required");
    return { ...prior, replayed: true };
  }
  if (submission.expectedJournalHash !== cut.sha256 || submission.expectedToken !== cut.job.token
      || submission.treatmentAdmissionHash !== cut.pointer.treatmentAdmissionHash) throw new Error("Compile submission names a stale admitted request");
  const lease = await acquireGuidedMutation(dir, { workflowVersion: 2, action: "compile-post-cut-proposal", expectedStatus: "treatment_admitted",
    expectedToken: submission.expectedToken, expectedJournalHash: submission.expectedJournalHash });
  try {
    const operation = guidedOperation({ dir, id: submission.idempotencyKey, submission, receivedAt });
    return await withStageTimingContext({ runId: cut.fact.runId, attemptId: `proposal:${operation.executionId}`, attemptNo: cut.job.attempts }, () =>
      timedStage(dir, "guided_full_program_proposal", () => compileUnderLease({ cut, submission, operation, lease },
        { verifySources: verifyCutPreviewSources, brain: runProposalBrain, ...overrides })));
  } finally { lease.release(); }
}

async function compileUnderLease(input: { cut: RawAdmission; submission: CompileSubmission; operation: Operation; lease: Lease }, deps: Dependencies) {
  const { cut, submission, operation, lease } = input, dir = cut.job.ctx.dir, guard = cutPreviewLeaseGuard(dir, lease);
  let budget: ProposalBudget | undefined;
  try {
    budget = startGuardedProposalDeadline({ dir, origin: { clockHash: cut.clock.hash, startedAt: cut.generationStartedAt },
      executionId: operation.executionId, guard }, deps.budgetClocks);
    const budgetAdmissionHash = retained(dir, operation.execution, "budget-admission.json", budget.admission);
    budget.remainingMs();
    await deps.verifySources({ job: cut.job, request: cut.request, executionKey: cut.receipt.executionKey, lease,
      remainingMs: budget.remainingMs }); guard();
    const candidate = await compileCandidate({ cut, operation, budget, deps });
    await deps.verifySources({ job: cut.job, request: cut.request, executionKey: cut.receipt.executionKey, lease,
      remainingMs: budget.remainingMs }); guard();
    await timedStage(dir, "proposal_ts_closure_after", async () => proposalCompilerAuthority(cut,
      { version: deps.proposalVersion ?? CURRENT_TREATMENT_PROPOSAL_VERSION }));
    const current = readRawTreatmentAdmission(dir);
    if (current.sha256 !== cut.sha256) throw new Error("Proposal source/cut/journal changed during compilation");
    saveHumanCutJobSnapshot(dir, current);
    budget.remainingMs();
    const budgetPrecommitHash = retained(dir, operation.execution, "budget-precommit.json", budget.observe());
    const proof = { ...candidate.proof, budgetAdmissionHash, budgetPrecommitHash };
    const receipt = proposalReceipt({ cut, submission, operation, proof });
    const proposalHash = writeGuidedObject(dir, receipt); deps.fault?.("after-receipt");
    commitProposal({ cut: current, guard: () => { guard(); budget!.remainingMs(); },
      proposalHash, createdAt: receipt.createdAt, blocked: candidate.blocked, pendingAssets: candidate.pendingAssets });
    finishGuidedOperation(operation, { state: "unapproved-proposal", proposalHash, generationStartedAt: cut.generationStartedAt,
      budget: budgetObservation(budget) });
    deps.fault?.("after-commit"); return { ...readGuidedTreatmentProposal(dir), replayed: false };
  } catch (error) {
    try { finishGuidedOperation(operation, { state: "failed-or-incomplete", error: String(error).slice(0, 1000), generationStartedAt: cut.generationStartedAt,
      budget: budgetObservation(budget),
      ...(error instanceof CutPreviewProcessError ? { subprocess: error.details } : {}) }); } catch { /* preserve immutable prior result */ }
    throw error;
  }
}

async function compileCandidate(input: { cut: RawAdmission; operation: Operation; budget: ProposalBudget; deps: Dependencies }) {
  const { cut, operation, budget, deps } = input, dir = cut.job.ctx.dir;
  budget.remainingMs();
  const options = { version: deps.proposalVersion ?? CURRENT_TREATMENT_PROPOSAL_VERSION,
    nativeReferences: deps.nativeReferences, directorBrain: deps.directorBrain };
  const authority = await timedStage(dir, "proposal_ts_closure_before", async () => proposalCompilerAuthority(cut, options));
  const evidence = await timedStage(dir, "proposal_input_preparation", () => prepareProposalEvidence(cut, operation.execution, budget.remainingMs, options));
  const prompt = buildProposalPrompt(cut.submission.rawIntent, evidence);
  const evidenceHash = retained(dir, operation.execution, "evidence.json", evidence);
  const compilerAuthorityHash = retained(dir, operation.execution, "compiler-authority.json", authority);
  const compiler = await timedStage(dir, "proposal_creative_compiler", () => deps.brain({ prompt, ctx: cut.job.ctx,
    cwd: operation.execution, timeoutMs: budget.remainingMs(), schema: authority.schema,
    ...(evidence.nativeReferences ? { imagePaths: nativeReferenceImages(operation.execution, evidence.nativeReferences) } : {}) }));
  const compilerResultHash = retained(dir, operation.execution, "compiler-result.json", compiler); deps.fault?.("after-brain");
  budget.remainingMs();
  const result = buildTreatmentCandidate({ cut, rawIntent: cut.submission.rawIntent, evidence, output: compiler.output });
  const candidateResultHash = retained(dir, operation.execution, "candidate-result.json", result);
  if (result.candidate) createHumanCutIndex(path.join(operation.execution, "candidate-plan.json"), result.candidate);
  return { blocked: result.blockers.length > 0, pendingAssets: result.pendingRequirements?.length ?? 0,
    proof: { evidenceHash, compilerAuthorityHash, compilerResultHash, candidateResultHash } };
}

function budgetObservation(budget: ProposalBudget | undefined) {
  try { return budget?.observe() ?? { state: "not-started" }; }
  catch { return { state: "clock-unavailable" }; }
}

function proposalReceipt(input: { cut: RawAdmission; submission: CompileSubmission; operation: Operation; proof: Record<string, string> }) {
  const { cut, submission, operation, proof } = input;
  return { schemaVersion: 2, kind: "guided-treatment-proposal", scope: PROPOSAL_SCOPE,
    treatmentAdmissionHash: cut.pointer.treatmentAdmissionHash, clockHash: cut.clock.hash, generationStartedAt: cut.generationStartedAt,
    cutDecisionHash: cut.pointer.cutDecisionHash, parentRevisionHash: cut.pointer.pictureLockedRevisionHash,
    submission, beforeJournalHash: cut.sha256, executionId: operation.executionId,
    executionStartHash: readCutPreviewObject(path.join(operation.execution, "start.json")).sha256,
    ...proof, createdAt: new Date().toISOString(), independentReview: "not-run", executable: false };
}

function commitProposal(input: { cut: RawAdmission; guard: () => void; proposalHash: string; createdAt: string; blocked: boolean; pendingAssets: number }) {
  const { cut, guard, proposalHash, createdAt } = input, job = cut.job;
  return commitGuidedJob({ beforeHash: cut.sha256, guard, job: { ...job, updatedAt: createdAt,
    guidedHandoffV2: { ...cut.pointer, treatmentProposalHash: proposalHash },
    message: input.blocked ? "Treatment proposal retained with blocking clauses; no video generation is authorized."
      : input.pendingAssets ? `Native proposal retained with ${input.pendingAssets} pending supplied-asset requirements; local visual decisions are required before publication.`
      : "Full-program proposal retained, unapproved; opening/audio/visual review and body generation are not connected.",
    nextEventId: job.nextEventId + 1, events: [...job.events, { id: job.nextEventId, at: createdAt,
      payload: { event: "treatment_proposal_retained", proposalHash, blocked: input.blocked, executable: false, independentReview: "not-run",
        ...(input.pendingAssets ? { pendingAssetCount: input.pendingAssets } : {}) } }].slice(-256) } });
}
