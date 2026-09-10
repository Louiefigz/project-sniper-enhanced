import path from "node:path";
import { canonicalProducerDir } from "@/app/api/producer/auto-edit/request";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { verifyCutPreviewSources } from "@/app/api/producer/auto-edit/cut-preview-verification";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";
import { REVIEW_STAGE_DEADLINE_MS } from "@/app/api/producer/auto-edit/brain-review-settings";
import { cutApprovalPath } from "@/app/api/producer/auto-edit/cut-approval";
import { gateBundleOperatorIntent, runPlanningGateBundle,
  type GateBundleInput, type GateBundleVerdict } from "@/app/api/producer/auto-edit/planning-gates";
import { parseProposalReadinessSubmission, proposalReadinessChecks,
  PROPOSAL_GATE_BUNDLE_KIND, PROPOSAL_READINESS_SCOPE } from "@/lib/producer/contracts/proposal-readiness-v1";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { captureTemplateUsageAuthority } from "./template-usage-history";
import { readProposalInputs } from "./guided-proposal-inputs";
import { readGuidedTreatmentProposal } from "./guided-proposal-store";
import { acquireGuidedMutation, guidedOperation, finishGuidedOperation, writeGuidedObject } from "./guided-cut-v2-store";
import { commitGuidedJob } from "./guided-cut-v2";
import { createHumanCutIndex, humanCutDirectory, saveHumanCutJobSnapshot } from "./human-cut-acceptance-store";
import { buildProposalReadinessPacket, proposalReadinessAuthority, type ReviewedProposalInput } from "./guided-proposal-review-packet";
import { runProposalReadinessCritic, assertProposalCriticResult } from "./guided-proposal-review-brain";
import { readinessBundle, readGuidedProposalReadiness } from "./guided-proposal-review-store";
import { storeGuidedTreatmentDraft } from "./guided-treatment-draft";
import { timedStage } from "./stage-timing";
import { withStageTimingContext } from "./stage-timing-context";
import { guardGenerationAttempt } from "./generation-clock-watermark";
import { startProposalReadinessDeadline } from "./proposal-readiness-deadline";
import { readinessRenderer, type RendererReconciliation } from "./readiness-render-containers";
import { executeReadinessGates, readinessGatesClean, assertReadinessCleanupSettled, type ReadinessGateExecution } from "./readiness-gate-execution";
import type { DeadlineClocks } from "./generation-attempt-clock";

interface Dependencies {
  verifySources: typeof verifyCutPreviewSources; critic: typeof runProposalReadinessCritic;
  gates: typeof runPlanningGateBundle;
  timeoutMs: number; fault?: (point: "after-critics" | "after-receipt" | "after-commit") => void;
  budgetClocks?: DeadlineClocks;
}
type Submission = ReturnType<typeof parseProposalReadinessSubmission>;
type ReadinessBudget = ReturnType<typeof startProposalReadinessDeadline>;
interface Runtime {
  proposal: ReviewedProposalInput; submission: Submission; guard: () => void;
  lease: Awaited<ReturnType<typeof acquireGuidedMutation>>; operation: ReturnType<typeof guidedOperation>; remaining: () => number;
  budget: ReadinessBudget; budgetAdmissionHash: string;
}
function retained(run: Runtime, root: string, name: string, value: unknown) {
  createHumanCutIndex(path.join(root, name), value); return writeGuidedObject(run.proposal.job.ctx.dir, value);
}

function remainingClock(timeoutMs: number) {
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > REVIEW_STAGE_DEADLINE_MS) throw new Error("Invalid whole readiness execution deadline");
  const wall = Date.now(), mono = performance.now();
  return () => {
    const elapsed = Math.max(Date.now() - wall, performance.now() - mono), left = Math.floor(timeoutMs - elapsed);
    if (Date.now() < wall || elapsed < 0 || left <= 0) throw new Error("Whole proposal readiness execution deadline exceeded");
    return left;
  };
}

/** Internal one-cycle readiness action. No public launch, peer-assisted critique, render or automatic repair. */
export async function reviewGuidedTreatmentProposal(input: { dir: unknown; submission: unknown }, overrides: Partial<Dependencies> = {}) {
  const submission = parseProposalReadinessSubmission(structuredClone(input.submission)), receivedAt = new Date().toISOString();
  const deps = { verifySources: verifyCutPreviewSources, critic: runProposalReadinessCritic,
    gates: runPlanningGateBundle, timeoutMs: REVIEW_STAGE_DEADLINE_MS, ...overrides };
  const remaining = remainingClock(deps.timeoutMs);
  const dir = canonicalProducerDir(input.dir), proposal = readGuidedTreatmentProposal(dir);
  if (proposal.pointer.proposalReadinessHash) {
    const prior = readGuidedProposalReadiness(dir);
    if (canonicalJsonSha256(prior.readinessSubmission) !== canonicalJsonSha256(submission)) throw new Error("Another readiness decision already exists; no implicit new review or repair");
    return { ...prior, replayed: true };
  }
  if (submission.expectedJournalHash !== proposal.sha256 || submission.expectedToken !== proposal.job.token
      || submission.proposalHash !== proposal.proposalHash) throw new Error("Readiness submission names a stale proposal");
  buildProposalReadinessPacket(proposal); // Unresolved proposals never pay critics or acquire another mutation.
  const lease = await acquireGuidedMutation(dir, { workflowVersion: 2, action: "review-post-cut-proposal", expectedStatus: "treatment_admitted",
    expectedToken: submission.expectedToken, expectedJournalHash: submission.expectedJournalHash });
  try {
    const operation = guidedOperation({ dir, id: submission.idempotencyKey, submission, receivedAt });
    return await executeReadiness({ proposal, submission, operation, lease }, { deps, localRemaining: remaining });
  } finally { lease.release(); }
}

async function executeReadiness(input: Pick<Runtime, "proposal" | "submission" | "operation" | "lease">,
  options: { deps: Dependencies; localRemaining: () => number }) {
  const { proposal, operation, lease } = input, dir = proposal.job.ctx.dir, { deps } = options;
  const leaseGuard = cutPreviewLeaseGuard(dir, lease);
  let budget: ReadinessBudget | undefined;
  try {
    budget = guardGenerationAttempt({ dir, origin: { clockHash: proposal.clock.hash, startedAt: proposal.generationStartedAt },
      executionId: operation.executionId, guard: leaseGuard }, startProposalReadinessDeadline(
      { clockHash: proposal.clock.hash, startedAt: proposal.generationStartedAt }, deps.budgetClocks));
    createHumanCutIndex(path.join(operation.execution, "budget-admission.json"), budget.admission);
    const budgetAdmissionHash = writeGuidedObject(dir, budget.admission);
    const remaining = () => Math.min(budget!.remainingMs(), options.localRemaining());
    const guard = () => { leaseGuard(); remaining(); };
    const run = { ...input, budget, budgetAdmissionHash, remaining, guard };
    return await withStageTimingContext({ runId: proposal.fact.runId, attemptId: `proposal-readiness:${operation.executionId}`, attemptNo: proposal.job.attempts },
      () => timedStage(dir, "guided_proposal_readiness", () => reviewUnderLease(run, deps)));
  } catch (error) {
    try { finishGuidedOperation(operation, { state: "failed-or-incomplete", error: String(error).slice(0, 2000),
      generationStartedAt: proposal.generationStartedAt, budget: readinessBudgetObservation(budget),
      ...(error instanceof CutPreviewProcessError ? { subprocess: error.details } : {}) });
    } catch { /* retain prior immutable terminal result */ }
    throw error;
  }
}

function readinessBudgetObservation(budget: ReadinessBudget | undefined) {
  try { return budget?.observe() ?? { state: "not-started" }; }
  catch { return { state: "clock-unavailable" }; }
}

interface GateRecord {
  schemaVersion: 2; kind: typeof PROPOSAL_GATE_BUNDLE_KIND; scope: typeof PROPOSAL_READINESS_SCOPE; ok: boolean;
  planHash: string; budgetMs: number; elapsedMs: number; remainingMs: number; overranBudget: boolean;
  verdict: GateBundleVerdict;
  /** Sealed-renderer gates render inside owned, per-gate named containers; unverified absence fails the bundle. */
  renderer: RendererReconciliation | null;
  cleanup: ReadinessGateExecution["cleanup"]; executionError: string | null;
}

/** Observe the budget after the bundle without throwing, so an overrun is still retained. */
function remainingOrZero(run: Runtime): number {
  try { return run.remaining(); } catch { return 0; }
}

function proposalExecutionDir(proposal: ReviewedProposalInput): string {
  return path.join(proposal.job.ctx.dir, "guided-v2-operations",
    String(proposal.compileSubmission.idempotencyKey), "executions", String(proposal.receipt.executionId));
}

/** Mirrors the autopilot's planningGateInput, including its stored-intent fail-closed rule.
 * The gates read the ORIGINAL manifest/transcripts rather than the proposal's canonical
 * staged copies: the controller-owned cut-approval receipt binds file_hash(manifest) and the
 * transcript-file digest of those exact admitted bytes, while staging renames and reserializes
 * them, so transcript_cut --approval would fail unconditionally on the staged copies.
 * readProposalInputs still proves the staged copies equal the admitted transcript bytes, and
 * observeGuidedCutV2/assertHumanCutContext already pin the live manifest/transcript digests. */
function gateInput(run: Runtime, planPath: string): GateBundleInput {
  const ctx = run.proposal.job.ctx;
  if (!ctx.intent?.mode || ctx.intent.lanes === undefined) {
    throw new Error("Guided readiness gates require the stored operator intent (mode and lanes) captured with the accepted cut");
  }
  const usage = captureTemplateUsageAuthority(ctx, undefined, {},
    `guided-proposal-readiness-${run.proposal.proposalHash.slice(0, 24)}`);
  return { planPath, manifestPath: ctx.manifestPath, transcriptsDir: ctx.transcriptsDir,
    cutApprovalPath: cutApprovalPath(ctx), templateUsagePath: usage.authority.path,
    templateUsageDigest: usage.authority.digest, operatorIntent: gateBundleOperatorIntent(ctx.scope, ctx.intent),
    ...(ctx.intent.reference && ctx.referenceStudy
      ? { reference: { profilePath: ctx.referenceStudy.profilePath, intent: ctx.intent.reference } } : {}) };
}

/** The accepted cut's hash-verified toolchain names the exact ffmpeg/ffprobe every sealed render proves with. */
function cutPreviewProofTools(proposal: ReviewedProposalInput): { ffmpeg: string; ffprobe: string } {
  const preview = path.join(proposal.job.ctx.dir, "cut-previews", proposal.request.requestHash, proposal.cutReceipt.executionKey);
  const runtime = readCutPreviewObject(path.join(preview, "toolchain.json")).value;
  const binaries = runtime.binaries as Record<string, unknown>;
  const ffmpeg = binaries?.ffmpeg, ffprobe = binaries?.ffprobe;
  if (typeof ffmpeg !== "string" || typeof ffprobe !== "string") throw new Error("Cut preview toolchain names no ffmpeg/ffprobe for readiness proofs");
  return { ffmpeg, ffprobe };
}

/** The renderer's own deterministic wall, run before a single critic is paid. An overrun of
 * the remaining readiness budget is recorded as a failed bundle, never a partial success. */
async function deterministicGates(run: Runtime, deps: Dependencies) {
  const ctx = run.proposal.job.ctx, root = run.operation.execution, plan = run.proposal.result.candidate;
  if (!plan || run.proposal.result.blockers.length) throw new Error("Blocked proposal cannot reach the deterministic full-plan gates");
  readProposalInputs({ ...run.proposal, receipt: run.proposal.cutReceipt }, proposalExecutionDir(run.proposal));
  const planHash = retained(run, root, "gate-plan.json", plan);
  retained(run, root, "gate-manifest.json", readCutPreviewObject(ctx.manifestPath).value);
  const input = gateInput(run, path.join(root, "gate-plan.json"));
  run.guard();
  const budgetMs = run.remaining(), began = Date.now();
  const renderer = readinessRenderer({ executionId: run.operation.executionId, proofTools: () => cutPreviewProofTools(run.proposal) });
  // Every gate receives the REMAINING request budget (not the runner's inherited five-minute default) and, under a
  // configured sealed renderer, its own owned container name; those exact names are reconciled before recording.
  const execution = await executeReadinessGates({ renderer,
    run: () => timedStage(ctx.dir, "guided_proposal_deterministic_gates", () => deps.gates(input,
      { timeoutMs: run.remaining(), ...(renderer ? { env: renderer.env } : {}) })) });
  const elapsedMs = Math.max(0, Date.now() - began), remainingMs = remainingOrZero(run);
  const overranBudget = remainingMs <= 0 || elapsedMs >= budgetMs;
  const record: GateRecord = { schemaVersion: 2, kind: PROPOSAL_GATE_BUNDLE_KIND, scope: PROPOSAL_READINESS_SCOPE,
    ok: readinessGatesClean(execution) && !overranBudget, planHash, budgetMs, elapsedMs, remainingMs, overranBudget,
    verdict: execution.verdict, renderer: execution.renderer, cleanup: execution.cleanup, executionError: execution.error };
  const hash = retained(run, root, "gate-bundle.json", record);
  assertReadinessCleanupSettled(execution);
  return { record, hash, planHash };
}

function gateFindings(record: GateRecord): string[] {
  const findings = record.verdict.errors.slice(0, 3).map((item) => `${item.gate}: ${item.message}`);
  if (record.overranBudget) {
    findings.unshift(`readiness budget overrun (${record.elapsedMs}ms spent of ${record.budgetMs}ms, ${record.remainingMs}ms left)`);
  }
  if (record.renderer && !record.renderer.verifiedAbsent) findings.unshift(`sealed renderer cleanup unverified: ${record.renderer.detail}`);
  if (record.cleanup === "not-run-process-stop-unknown" || record.cleanup === "unverified-absence") findings.unshift(record.executionError ?? record.cleanup);
  return findings.length ? findings : ["gate bundle failed without diagnostics"];
}

function packetProof(run: Runtime) {
  const packet = buildProposalReadinessPacket(run.proposal), authority = proposalReadinessAuthority(run.proposal);
  return { packet, authority, packetHash: retained(run, run.operation.execution, "packet.json", packet),
    implementationHash: retained(run, run.operation.execution, "implementation.json", authority) };
}

/** Same retained evidence with zero critic slots, proving no independent critic was paid. */
function blockedGateProof(run: Runtime) {
  const base = packetProof(run), bundle = readinessBundle(base.packetHash, [], [], false);
  return { packetHash: base.packetHash, implementationHash: base.implementationHash,
    reviewBundleHash: retained(run, run.operation.execution, "review-bundle.json", bundle), clean: false };
}

async function criticBatch(run: Runtime, deps: Dependencies) {
  const { packet, authority, packetHash, implementationHash } = packetProof(run);
  const results = await Promise.allSettled([0, 1].map(async (criticIndex) => {
    const cwd = humanCutDirectory(run.operation.execution, `critic-${criticIndex + 1}`);
    createHumanCutIndex(path.join(cwd, "packet.json"), packet);
    try {
      const result = await timedStage(run.proposal.job.ctx.dir, "proposal_independent_critic", () => deps.critic({ packet, criticIndex,
        ctx: run.proposal.job.ctx, cwd, schema: authority.schema, timeoutMs: run.remaining() }), { round: criticIndex + 1 });
      assertProposalCriticResult(result, { packet, criticIndex });
      return { result, hash: retained(run, cwd, "result.json", result) };
    } catch (error) {
      createHumanCutIndex(path.join(cwd, "failure.json"), { criticIndex, packetHash, error: String(error).slice(0, 2000), at: new Date().toISOString() });
      throw error;
    }
  }));
  const rejected = results.find((result) => result.status === "rejected");
  if (rejected?.status === "rejected") throw rejected.reason;
  const values = results.map((result) => { if (result.status !== "fulfilled") throw new Error("Missing independent critic"); return result.value; });
  const bundle = readinessBundle(packetHash, values.map((item) => item.hash), values.map((item) => item.result), true);
  const reviewBundleHash = retained(run, run.operation.execution, "review-bundle.json", bundle);
  return { packetHash, implementationHash, reviewBundleHash, clean: bundle.verdict === "clean" };
}

async function reobserve(run: Runtime, deps: Dependencies) {
  run.remaining();
  await deps.verifySources({ job: run.proposal.job, request: run.proposal.request,
    executionKey: run.proposal.cutReceipt.executionKey, lease: run.lease, remainingMs: run.remaining });
  run.guard(); run.remaining();
  const current = readGuidedTreatmentProposal(run.proposal.job.ctx.dir);
  if (current.sha256 !== run.proposal.sha256) throw new Error("Proposal source/cut/journal changed during independent review");
  return current;
}

function readinessMessage(gates: GateRecord, draftHash: string | null): string {
  if (!gates.ok) {
    return `Deterministic full-plan gates rejected this treatment proposal; no independent critic was paid and no treatment draft, render or approval was produced. ${gateFindings(gates).join(" | ")}`.slice(0, 2000);
  }
  return draftHash ? "Deterministic full-plan gates passed and independent proposal review passed; isolated TREATMENT_DRAFT retained. Opening playback and body generation remain pending."
    : "Independent proposal review found blocking issues; no treatment draft, render or approval was promoted.";
}

async function reviewUnderLease(run: Runtime, deps: Dependencies) {
  const dir = run.proposal.job.ctx.dir;
  await reobserve(run, deps);
  const gates = await deterministicGates(run, deps);
  const proof = gates.record.ok ? await criticBatch(run, deps) : blockedGateProof(run); deps.fault?.("after-critics");
  run.remaining(); const current = await reobserve(run, deps); proposalReadinessAuthority(current); run.remaining();
  const draftHash = proof.clean ? storeGuidedTreatmentDraft(current, proof.reviewBundleHash) : null;
  saveHumanCutJobSnapshot(dir, current);
  run.remaining();
  const budgetPrecommitHash = retained(run, run.operation.execution, "budget-precommit.json", run.budget.observe());
  const createdAt = new Date().toISOString(), receipt = { schemaVersion: 3, kind: "guided-proposal-readiness", scope: PROPOSAL_READINESS_SCOPE,
    submission: run.submission, beforeJournalHash: current.sha256, proposalHash: current.proposalHash, clockHash: current.clock.hash,
    generationStartedAt: current.generationStartedAt, executionId: run.operation.executionId,
    executionStartHash: readCutPreviewObject(path.join(run.operation.execution, "start.json")).sha256,
    deterministicGates: { ok: gates.record.ok, hash: gates.hash, planHash: gates.planHash, ...proposalReadinessChecks(gates.record.ok) },
    packetHash: proof.packetHash, implementationHash: proof.implementationHash, reviewBundleHash: proof.reviewBundleHash,
    budgetAdmissionHash: run.budgetAdmissionHash, budgetPrecommitHash,
    treatmentDraftRevisionHash: draftHash, createdAt, executable: false };
  const readinessHash = writeGuidedObject(dir, receipt); deps.fault?.("after-receipt"); run.guard(); run.remaining();
  commitReadiness(run, { current, readinessHash, draftHash, createdAt, message: readinessMessage(gates.record, draftHash) });
  finishGuidedOperation(run.operation, { state: !gates.record.ok ? "blocked-deterministic-gates"
      : proof.clean ? "isolated-treatment-draft-preview-pending" : "blocked-proposal-review",
    readinessHash, deterministicGates: { ok: gates.record.ok, hash: gates.hash, findings: gates.record.ok ? [] : gateFindings(gates.record) },
    generationStartedAt: current.generationStartedAt, budget: readinessBudgetObservation(run.budget),
    generationBudgetQualification: "proposal-phase-only-not-full-request-accounting", executable: false });
  deps.fault?.("after-commit"); return { ...readGuidedProposalReadiness(dir), replayed: false };
}

function commitReadiness(run: Runtime, input: { current: ReviewedProposalInput; readinessHash: string;
  draftHash: string | null; createdAt: string; message: string }) {
  const { current, readinessHash, draftHash, createdAt } = input, job = current.job;
  return commitGuidedJob({ beforeHash: current.sha256, guard: run.guard, job: { ...job, updatedAt: createdAt,
    guidedHandoffV2: { ...current.pointer, proposalReadinessHash: readinessHash, ...(draftHash ? { treatmentDraftRevisionHash: draftHash } : {}) },
    message: input.message,
    nextEventId: job.nextEventId + 1, events: [...job.events, { id: job.nextEventId, at: createdAt,
      payload: { event: "proposal_readiness_retained", readinessHash, treatmentDraftRevisionHash: draftHash,
        acceptedRootUnchanged: true, executable: false } }].slice(-256) } });
}
