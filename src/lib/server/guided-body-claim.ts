import { canonicalProducerDir } from "@/app/api/producer/auto-edit/request";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { parseContinueApprovedOpening } from "@/lib/producer/contracts/guided-body-v1";
import { parseGuidedBodyExecutionClaim } from "@/lib/producer/contracts/guided-body-claim-v1";
import { canonicalJsonSha256 as hash } from "./auto-edit-hash";
import { acquireGuidedMutation, guidedOperation, finishGuidedOperation } from "./guided-cut-v2-store";
import { observeHumanCutJob, saveHumanCutJobSnapshot } from "./human-cut-acceptance-store";
import { holdGuidedBodyInputUnderLease } from "./guided-body-authority";
import { readGuidedProposalReadiness } from "./guided-proposal-review-store";
import { readSelectedOpeningMedia } from "./guided-opening-selection";
import { captureBodyAttemptStart, assertBodyDeadlineProof } from "./guided-body-deadline";
import { guardGenerationAttempt } from "./generation-clock-watermark";
import { bodyClaimJournal, readGuidedBodyClaim } from "./guided-body-lineage";
import { assertFreshBodyRequest, bodyHeldDocument, writeBodyObject, readBodyObject, type BodyOperation } from "./guided-body-store";
import { commitGuidedJob } from "./guided-cut-v2";
import type { ProjectMutationLease } from "./project-mutation-lease";

/** Internal TEST dependencies only. No public command or route invokes this non-executable admission. */
export const bodyClaimServices = { canonicalDir: canonicalProducerDir, hold: holdGuidedBodyInputUnderLease,
  readiness: readGuidedProposalReadiness, selection: readSelectedOpeningMedia, read: readGuidedBodyClaim,
  capture: captureBodyAttemptStart };
type Services = typeof bodyClaimServices;
type Submission = ReturnType<typeof parseContinueApprovedOpening>;
type Budget = ReturnType<typeof prepare>["budget"];
export interface FreshBodyAdmission {
  dir: string; lease: ProjectMutationLease; budget: Budget; operation: BodyOperation;
  admission: ReturnType<typeof summary>;
}
const freshAdmissions = new WeakSet<FreshBodyAdmission>();

/** Consume only a real same-invocation handoff; deserialized or reconstructed admission data cannot spawn. */
export function consumeFreshBodyAdmission(input: FreshBodyAdmission): void {
  if (!freshAdmissions.delete(input)) throw new Error("Body activation needs the actual unused fresh admission handoff");
}

async function continueFresh<T>(handoff: FreshBodyAdmission, continuation: (input: FreshBodyAdmission) => Promise<T>) {
  freshAdmissions.add(handoff);
  try { return await continuation(handoff); }
  finally { freshAdmissions.delete(handoff); }
}

function replay(dir: string, submission: Submission, services: Services) {
  if (!observeHumanCutJob(dir).job.guidedHandoffV2?.bodyExecutionClaimHash) return null;
  const existing = services.read(dir);
  if (hash(existing.input.submission) !== hash(submission)) throw new Error("Another body request owns this checkpoint; no new execution is permitted");
  return summary(existing, true);
}

function summary(held: ReturnType<typeof readGuidedBodyClaim>, replayed: boolean) {
  return { ok: true as const, state: "admission-fenced" as const, replayed, requestId: held.claim.requestId,
    executionId: held.claim.executionId, claimHash: held.claimHash, journalHash: held.current.sha256,
    executable: false as const, workerState: "not-installed" as const, bodyGenerated: false as const, deliveryApproved: false as const };
}

function prepare(input: { dir: string; submission: Submission; lease: ProjectMutationLease;
  start: ReturnType<typeof captureBodyAttemptStart> }, services: Services) {
  const { dir, submission, lease, start } = input, guard = cutPreviewLeaseGuard(dir, lease);
  guard(); assertFreshBodyRequest(dir, submission);
  const before = observeHumanCutJob(dir), proposal = services.readiness(dir);
  if (before.sha256 !== submission.expectedJournalHash || before.job.token !== submission.expectedToken
      || proposal.sha256 !== before.sha256) throw new Error("Body admission lost its exact approved journal");
  const origin = { clockHash: proposal.clock.hash, startedAt: proposal.generationStartedAt };
  const operation = guidedOperation({ dir, id: submission.idempotencyKey, submission, receivedAt: start.receivedAt });
  try {
    const budget = guardGenerationAttempt({ dir, origin, executionId: operation.executionId, guard }, start.start(origin));
    return { ...input, before, origin, operation, budget, guard };
  } catch (error) {
    recordFailure(operation, error, { state: "unverified", receivedAt: start.receivedAt, reason: "original-clock-admission-construction-failed" });
    throw error;
  }
}

async function commitAdmission(context: ReturnType<typeof prepare>, services: Services) {
  const { dir, submission, lease, operation, budget, before, guard } = context;
  budget.remainingMs();
  const budgetAdmissionHash = writeBodyObject(dir, operation, "budget-admission.json", budget.admission);
  const held = await services.hold({ dir, submission, lease, remainingMs: budget.remainingMs });
  if (hash(held.origin) !== hash(context.origin)) throw new Error("Body hold returned a different original request clock");
  held.assertUnchanged(); guard(); budget.remainingMs();
  const selected = services.selection(dir), document = bodyHeldDocument(held, selected);
  const heldInputHash = writeBodyObject(dir, operation, "held-input.json", document);
  const precommit = budget.observe(), budgetPrecommitHash = writeBodyObject(dir, operation, "budget-precommit.json", precommit);
  const createdAt = new Date().toISOString(), claim = parseGuidedBodyExecutionClaim({ schemaVersion: 1, kind: "guided-body-execution-claim",
    scope: "private-body-admission-not-execution-or-approval", requestId: submission.idempotencyKey, executionId: operation.executionId,
    beforeJournalHash: before.sha256, heldInputHash, budgetAdmissionHash, budgetPrecommitHash,
    clockHash: held.origin.clockHash, generationStartedAt: held.origin.startedAt, createdAt,
    executable: false, workerState: "not-installed", bodyGenerated: false, deliveryApproved: false });
  assertBodyDeadlineProof({ admission: budget.admission, precommit }, { origin: context.origin,
    executionReceivedAt: operation.receivedAt, executionStartedAt: operation.startedAt, createdAt });
  const claimHash = writeBodyObject(dir, operation, "claim.json", claim); saveHumanCutJobSnapshot(dir, before);
  const commitGuard = () => {
    guard(); held.assertUnchanged(); budget.remainingMs();
    for (const [name, expected] of Object.entries({ "claim.json": claimHash, "held-input.json": heldInputHash,
      "budget-admission.json": budgetAdmissionHash, "budget-precommit.json": budgetPrecommitHash })) readBodyObject(dir, operation.execution, name, expected);
    if (new Date().toISOString() < createdAt) throw new Error("Body clock moved backwards before claim CAS");
    guard(); budget.remainingMs();
  };
  commitGuidedJob({ beforeHash: before.sha256, guard: commitGuard, job: bodyClaimJournal(before, claim, claimHash) });
  return summary(services.read(dir), false);
}

function failedAdmission(operation: BodyOperation, budget: Budget, error: unknown): void {
  let clock: unknown;
  try { clock = budget.observe(); } catch (failure) { clock = { state: "unverified", error: String(failure).slice(0, 2000) }; }
  recordFailure(operation, error, clock);
}

function recordFailure(operation: BodyOperation, error: unknown, clock: unknown): void {
  finishGuidedOperation(operation, { status: "failed", error: String(error).slice(0, 4000), clock,
    claimCleared: false, executable: false, bodyGenerated: false, deliveryApproved: false });
}

async function admitBody<T>(input: { dir: unknown; submission: unknown }, services: Services,
  continuation: (input: FreshBodyAdmission) => Promise<T>, capturedStart?: ReturnType<typeof captureBodyAttemptStart>) {
  const submission = parseContinueApprovedOpening(structuredClone(input.submission)), start = capturedStart ?? services.capture();
  const dir = services.canonicalDir(input.dir), existing = replay(dir, submission, services);
  if (existing) return { admission: existing, continuation: null };
  const lease = await acquireGuidedMutation(dir, { workflowVersion: 2, action: "continue-approved-opening", expectedStatus: "treatment_admitted",
    expectedToken: submission.expectedToken, expectedJournalHash: submission.expectedJournalHash });
  try {
    const context = prepare({ dir, submission, lease, start }, services);
    let admission: ReturnType<typeof summary>;
    try {
      admission = await commitAdmission(context, services);
      finishGuidedOperation(context.operation, { status: "admission-fenced", claimHash: admission.claimHash, executable: false });
    } catch (error) { failedAdmission(context.operation, context.budget, error); throw error; }
    // A later owned execution has its own failure records. Never overwrite the immutable admission result.
    const handoff = { dir, lease, budget: context.budget, operation: context.operation, admission };
    const result = await continueFresh(handoff, continuation);
    return { admission, continuation: result };
  } finally { lease.release(); }
}

/** Internal admission only. Same-request replay is read-only; V1 remains non-executable. */
export async function admitGuidedBodyClaim(input: { dir: unknown; submission: unknown }, services = bodyClaimServices) {
  return (await admitBody(input, services, async () => null)).admission;
}

/** Owned foreground service seam: fresh admission only, the SAME actual lease and original live body clock.
 * A replay cannot call this continuation; a V1 admission retained from another invocation is never activated. */
export function withFreshGuidedBodyAdmission<T>(input: { dir: unknown; submission: unknown },
  continuation: (input: FreshBodyAdmission) => Promise<T>, services = bodyClaimServices, start?: ReturnType<typeof captureBodyAttemptStart>) {
  return admitBody(input, services, continuation, start);
}
