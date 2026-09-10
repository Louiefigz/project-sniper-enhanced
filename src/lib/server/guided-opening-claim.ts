import path from "node:path";
import { mkdirSync } from "node:fs";
import { parseGuidedOpeningExecutionClaim } from "@/lib/producer/contracts/guided-opening-claim-v1";
import { parsePrepareGuidedOpeningRequest } from "@/lib/producer/contracts/guided-source-color-v1";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { readCutPreviewObject, assertCutPreviewDirectory } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import type { ProjectMutationLease } from "./project-mutation-lease";
import { canonicalJson, canonicalJsonSha256 } from "./auto-edit-hash";
import { atomicCreateFileSync } from "./atomic-file";
import { assertOpeningSubmission, type OpeningReadiness } from "./guided-opening-authority";
import { observeGuidedOpeningMediaInput, type writeGuidedOpeningMediaInput } from "./guided-opening-media-input";
import { captureOpeningRuntimeControl } from "./guided-opening-runtime-control";
import { openingDeadlineAdmission } from "./opening-deadline";
import { readGuidedExecution, readGuidedObject, writeGuidedObject, parseGuidedCutDecision, type guidedOperation } from "./guided-cut-v2-store";
import { commitGuidedJob } from "./guided-cut-v2";
import { observeHumanCutJob, saveHumanCutJobSnapshot } from "./human-cut-acceptance-store";
import { parseAutoEditJobRecord } from "./auto-edit-job-persistence";
import { readRawTreatmentClock } from "./guided-raw-treatment-store";
import { readOpeningProcessActivation } from "./guided-opening-process-activation";

type Invocation = ReturnType<typeof writeGuidedOpeningMediaInput>;
interface ClaimInput {
  proposal: OpeningReadiness; operation: ReturnType<typeof guidedOperation>; invocation: Invocation;
  lease: ProjectMutationLease; remainingMs: () => number; budgetAdmissionHash: string;
}

function claimDirectory(dir: string, requestId: string, executionId: string) {
  return path.join(dir, "guided-v2-operations", requestId, "executions", executionId);
}

function selectedOrders(invocation: Invocation): number[] {
  const observed = observeGuidedOpeningMediaInput(invocation.inputPath, invocation.inputSha256);
  const graphics = observed.documents.frameBindings.value.graphics as Array<{ order: number; startFrame: number }>;
  return graphics.filter((row) => row.startFrame < observed.authority.review.endFrameExclusive).map((row) => row.order);
}

function buildClaim(input: ClaimInput) {
  const { proposal, operation, invocation } = input, dir = proposal.job.ctx.dir;
  const submission = parsePrepareGuidedOpeningRequest(operation.record.submission); assertOpeningSubmission(proposal, submission);
  const root = claimDirectory(dir, submission.idempotencyKey, operation.executionId);
  const startFile = readCutPreviewObject(path.join(root, "start.json"));
  const start = readGuidedExecution({ dir, id: submission.idempotencyKey, executionId: operation.executionId, hash: startFile.sha256 });
  if (canonicalJsonSha256(submission) !== start.submissionHash) throw new Error("Opening claim differs from its entire retained prepare request");
  const admission = readGuidedObject(dir, input.budgetAdmissionHash), expected = openingDeadlineAdmission(
    { clockHash: proposal.clock.hash, startedAt: proposal.generationStartedAt }, Date.parse(String(start.receivedAt)));
  if (operation.execution !== root || invocation.inputPath !== path.join(root, "media-input/input.json")
      || invocation.input.executionId !== operation.executionId || !expected.admitted
      || canonicalJsonSha256(admission) !== canonicalJsonSha256(expected)) throw new Error("Opening claim lost its exact execution/input/original budget admission");
  return parseGuidedOpeningExecutionClaim({ schemaVersion: 1, kind: "guided-opening-execution-claim", scope: "private-opening-owned-execution-not-approval",
    requestId: submission.idempotencyKey, executionId: operation.executionId, beforeJournalHash: proposal.sha256,
    inputPath: invocation.inputPath, inputSha256: invocation.inputSha256, executionInputHash: invocation.input.executionInputHash,
    outputRoot: path.join(root, "media-output"), clockHash: proposal.clock.hash, generationStartedAt: proposal.generationStartedAt,
    budgetAdmissionHash: input.budgetAdmissionHash, selectedGraphicOrders: selectedOrders(invocation), runtime: captureOpeningRuntimeControl(proposal) });
}

/** Commit possible external-resource ownership BEFORE any child launch. No worker or approval is created here. */
export function claimGuidedOpeningExecution(input: ClaimInput) {
  const { proposal, operation } = input, dir = proposal.job.ctx.dir, leaseGuard = cutPreviewLeaseGuard(dir, input.lease);
  const guard = () => { leaseGuard(); input.remainingMs(); };
  guard();
  if (proposal.pointer.openingExecutionClaimHash) throw new Error("Opening renderer ownership is unresolved; exact cleanup is required before another attempt");
  const claim = buildClaim(input); guard();
  if (observeHumanCutJob(dir).sha256 !== proposal.sha256) throw new Error("Opening journal changed before resource claim");
  assertCutPreviewDirectory(operation.execution); mkdirSync(claim.outputRoot, { mode: 0o700 });
  const claimPath = path.join(operation.execution, "execution-claim.json"); atomicCreateFileSync(claimPath, canonicalJson(claim));
  const claimHash = writeGuidedObject(dir, claim); saveHumanCutJobSnapshot(dir, proposal); guard();
  const at = new Date().toISOString(), job = proposal.job;
  commitGuidedJob({ beforeHash: proposal.sha256, guard, job: { ...job, updatedAt: at,
    guidedHandoffV2: { ...proposal.pointer, openingExecutionClaimHash: claimHash },
    message: "Private opening execution owns a pending renderer claim; media selection and another attempt require exact resource cleanup.",
    nextEventId: job.nextEventId + 1, events: [...job.events, { id: job.nextEventId, at,
      payload: { event: "opening_execution_claimed", executionId: operation.executionId, claimHash, openingApproved: false } }].slice(-256) } });
  return { claim, claimHash, claimPath, claimSha256: readCutPreviewObject(claimPath).sha256, journalHash: observeHumanCutJob(dir).sha256 };
}

function historicalClaimBindings(input: { dir: string; claim: ReturnType<typeof parseGuidedOpeningExecutionClaim>;
  prior: ReturnType<typeof parseAutoEditJobRecord>; start: ReturnType<typeof readGuidedExecution> }) {
  const { dir, claim, prior, start } = input, pointer = prior.guidedHandoffV2!;
  const intake = readCutPreviewObject(path.join(dir, "guided-v2-operations", claim.requestId, "submission.json")).value;
  const submission = parsePrepareGuidedOpeningRequest(intake.submission);
  if (canonicalJsonSha256(submission) !== start.submissionHash || submission.idempotencyKey !== claim.requestId
      || submission.expectedToken !== prior.token || submission.expectedJournalHash !== claim.beforeJournalHash
      || submission.proposalReadinessHash !== pointer.proposalReadinessHash
      || submission.treatmentDraftRevisionHash !== pointer.treatmentDraftRevisionHash) throw new Error("Opening claimed execution differs from its exact prior prepare request");
  const fact = parseGuidedCutDecision(readGuidedObject(dir, pointer.cutDecisionHash));
  const activation = readGuidedObject(dir, pointer.cutActivationHash);
  if (fact.contextHash !== canonicalJsonSha256(prior.ctx) || fact.nextToken !== prior.token
      || activation.decisionHash !== pointer.cutDecisionHash || activation.revisionHash !== pointer.pictureLockedRevisionHash) {
    throw new Error("Opening claim retained cut/activation identity changed");
  }
  const clock = readRawTreatmentClock({ job: prior, fact, pointer, activation }, claim.clockHash);
  const proposal = readGuidedObject(dir, pointer.treatmentProposalHash!), readiness = readGuidedObject(dir, pointer.proposalReadinessHash!);
  const admission = readGuidedObject(dir, pointer.treatmentAdmissionHash!);
  if (clock.value.startedAt !== claim.generationStartedAt || proposal.clockHash !== clock.hash || readiness.clockHash !== clock.hash
      || admission.clockHash !== clock.hash || proposal.generationStartedAt !== claim.generationStartedAt
      || readiness.generationStartedAt !== claim.generationStartedAt || readiness.proposalHash !== pointer.treatmentProposalHash
      || readiness.treatmentDraftRevisionHash !== pointer.treatmentDraftRevisionHash
      || proposal.treatmentAdmissionHash !== pointer.treatmentAdmissionHash || proposal.cutDecisionHash !== pointer.cutDecisionHash) {
    throw new Error("Opening claim moved away from its original retained proposal clock");
  }
  return submission;
}

/** Read exact ownership without re-rendering, contacting Docker, clearing a claim or asserting absence. */
function claimFromJournal(dir: string, current: ReturnType<typeof observeHumanCutJob>) {
  const hash = current.job.guidedHandoffV2?.openingExecutionClaimHash;
  if (!hash) throw new Error("No durable opening execution claim exists");
  const claim = parseGuidedOpeningExecutionClaim(readGuidedObject(dir, hash)), root = claimDirectory(dir, claim.requestId, claim.executionId);
  const privateClaim = readCutPreviewObject(path.join(root, "execution-claim.json"));
  const before = readCutPreviewObject(path.join(dir, "human-cut-job-snapshots", `${claim.beforeJournalHash}.json`));
  const prior = parseAutoEditJobRecord(before.value), startFile = readCutPreviewObject(path.join(root, "start.json"));
  const start = readGuidedExecution({ dir, id: claim.requestId, executionId: claim.executionId, hash: startFile.sha256 });
  const { openingExecutionClaimHash: _claim, openingProcessOutcomeHash: _outcome, ...currentPointer } = current.job.guidedHandoffV2!; void _claim;
  const admission = readGuidedObject(dir, claim.budgetAdmissionHash), expected = openingDeadlineAdmission(
    { clockHash: claim.clockHash, startedAt: claim.generationStartedAt }, Date.parse(String(start.receivedAt)));
  if (privateClaim.sha256 !== hash || canonicalJsonSha256(privateClaim.value) !== hash || before.sha256 !== claim.beforeJournalHash
      || prior.status !== "treatment_admitted" || current.job.status !== "treatment_admitted" || prior.guidedHandoffV2?.openingExecutionClaimHash
      || current.job.token !== prior.token || current.job.attempts !== prior.attempts || current.job.artifactToken !== prior.artifactToken
      || current.job.workerPid || current.job.workerIdentity || canonicalJsonSha256(current.job.ctx) !== canonicalJsonSha256(prior.ctx)
      || canonicalJsonSha256(currentPointer) !== canonicalJsonSha256(prior.guidedHandoffV2)
      || claim.inputPath !== path.join(root, "media-input/input.json") || claim.outputRoot !== path.join(root, "media-output")
      || !expected.admitted || canonicalJsonSha256(admission) !== canonicalJsonSha256(expected)) throw new Error("Opening durable claim lost its exact journal/input/clock lineage");
  const submission = historicalClaimBindings({ dir, claim, prior, start });
  if (_outcome) {
    const activation = readOpeningProcessActivation(dir, current).fact;
    if (activation.claimHash !== hash || activation.executionId !== claim.executionId || activation.inputSha256 !== claim.inputSha256
        || activation.clockHash !== claim.clockHash || activation.generationStartedAt !== claim.generationStartedAt) throw new Error("Opening process outcome moved to another claim");
  }
  return { ...current, submission, claim, claimHash: hash, claimPath: path.join(root, "execution-claim.json"), claimSha256: privateClaim.sha256,
    resourceAbsence: "not-observed" as const, selectable: false as const };
}

/** Current ownership only; historical facts are never silently substituted. */
export function readGuidedOpeningExecutionClaim(dir: string) {
  const current = observeHumanCutJob(dir), held = claimFromJournal(dir, current);
  if (observeHumanCutJob(dir).sha256 !== current.sha256) throw new Error("Opening claim changed during observation");
  return held;
}

/** Explicit historical lineage for an already committed cleanup fact, never active ownership or media selection. */
export function readRetainedOpeningExecutionClaim(dir: string, journalHash: string) {
  if (!/^[0-9a-f]{64}$/u.test(journalHash)) throw new Error("Retained opening journal hash is malformed");
  const file = readCutPreviewObject(path.join(dir, "human-cut-job-snapshots", `${journalHash}.json`));
  if (file.sha256 !== journalHash) throw new Error("Retained opening journal bytes changed");
  const held = claimFromJournal(dir, { ...file, job: parseAutoEditJobRecord(file.value) });
  return { ...held, observationScope: "historical-owned-claim-not-active-or-selectable" as const };
}
