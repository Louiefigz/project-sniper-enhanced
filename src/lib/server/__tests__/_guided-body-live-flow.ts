/** Shared existing TEST CLI chain. Synthetic attestation requires the caller's freshly bound fixture guard. */
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { observeCutPreviewFile, readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parsePrepareGuidedOpening } from "@/lib/producer/contracts/guided-opening-v1";
import { parseGuidedOpeningApprovalSubmission } from "@/lib/producer/contracts/guided-opening-approval-v1";
import { parseContinueApprovedOpening } from "@/lib/producer/contracts/guided-body-v1";
import { parseGuidedBodyRunResult, parseGuidedBodyStatus, type GuidedBodyCandidateV1 } from "@/lib/producer/contracts/guided-body-command-v1";
import { parseGuidedBodyExecutionClaim } from "@/lib/producer/contracts/guided-body-claim-v1";
import { parseOpeningLaunchResult, parseOpeningLaunchStatus } from "@/lib/producer/guided-opening-launch-client";
import { parseGuidedOpeningApprovalResult, parseGuidedOpeningStatus } from "@/lib/producer/guided-opening-client";
import { objectValue } from "@/lib/producer/contracts/validation";
import type { GuidedOpeningStatusV1 } from "@/lib/producer/contracts/guided-opening-status-v1";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { bodyLiveBodyCommand, bodyLiveCommand, retainBodyLive, type BodyLiveLog } from "./_guided-body-live-support";
import { assertBodyLiveConflict, assertBodyLiveStatus, bodyLiveMetadataInventory, observeBodyLiveCandidate } from "./_guided-body-live-result";

type Ready = Extract<GuidedOpeningStatusV1, { state: "ready-for-review" }>;
export const BODY_LIVE_TEST_SCOPE = "TEST-ONLY-fresh-synthetic-CLI-opening-approval-private-body-not-creator-acceptance";
export interface SyntheticLiveFlow { log: BodyLiveLog; dir: string; assertSynthetic: () => void }

async function awaitSelected(log: BodyLiveLog, dir: string): Promise<Ready> {
  const deadline = performance.now() + 30 * 60_000; // Observation cap only, never render credit.
  while (performance.now() < deadline) {
    const launch = parseOpeningLaunchStatus(await bodyLiveCommand({ log, dir, command: "launch-status" }));
    if (launch.state === "failed") throw new Error(launch.detail);
    const status = parseGuidedOpeningStatus(await bodyLiveCommand({ log, dir, command: "status" }), dir);
    if (status.state === "ready-for-review") return status;
    if (status.state === "failed" || launch.state !== "launch-recorded") throw new Error(`No verified selected media: ${launch.detail}; ${status.detail}`);
    await delay(5000);
  }
  throw new Error("TEST observation cap expired; controller/claim state is unknown, retained, and not automatically retried");
}

export async function launchLiveOpening(log: BodyLiveLog, dir: string): Promise<Ready> {
  const status = parseOpeningLaunchStatus(await bodyLiveCommand({ log, dir, command: "launch-status" }));
  assert.equal(status.state, "eligible"); assert.ok(status.request);
  const request = parsePrepareGuidedOpening({ schemaVersion: 1, operation: "prepare-guided-opening", idempotencyKey: randomUUID(), ...status.request });
  const requestPath = retainBodyLive(log, "launch-request.json", request);
  const result = parseOpeningLaunchResult(await bodyLiveCommand({ log, dir, command: "launch", request: requestPath }), request.idempotencyKey);
  assert.equal(result.replayed, false); assert.equal(result.journalHash, request.expectedJournalHash);
  retainBodyLive(log, "launch-acknowledgement.json", result);
  const selected = await awaitSelected(log, dir);
  assert.equal(selected.requestId, request.idempotencyKey); assert.equal(selected.openingApproved, false);
  retainBodyLive(log, "selected-opening.json", selected); return selected;
}

export async function approveLiveSynthetic(scope: SyntheticLiveFlow, selected: Ready): Promise<Ready> {
  scope.assertSynthetic(); const { log, dir } = scope;
  const submission = parseGuidedOpeningApprovalSubmission({ schemaVersion: 1, operation: "approve-guided-opening", idempotencyKey: randomUUID(),
    expectedToken: selected.journal.token, expectedJournalHash: selected.journal.sha256, selectionHash: selected.selectionHash,
    coreMediaSha256: selected.media.core.mediaSha256, reviewMediaSha256: selected.media.review.mediaSha256,
    attestation: { watchedOpening: true, watchedBodyTransition: true, listened: true, approvesOpening: true, understandsBodyPending: true } });
  retainBodyLive(log, "test-attestation-scope.json", { scope: BODY_LIVE_TEST_SCOPE, genuineHumanAcceptance: false,
    subjectiveListeningPerformed: false, approvalPurpose: "Exercise exact production approval transaction on driver-created synthetic source only" });
  const request = retainBodyLive(log, "test-approval-request.json", submission);
  scope.assertSynthetic();
  const result = await bodyLiveCommand({ log, dir, command: "approve", request });
  const { verificationScope, ...approvalResult } = objectValue(result, "TEST approval CLI result");
  assert.equal(verificationScope, "fresh-readback-for-this-human-opening-decision");
  const parsed = parseGuidedOpeningApprovalResult(approvalResult, selected.selectionHash);
  assert.equal(parsed.replayed, false);
  retainBodyLive(log, "test-approval-cli-result.json", { result, scope: BODY_LIVE_TEST_SCOPE, genuineHumanAcceptance: false });
  const approved = parseGuidedOpeningStatus(await bodyLiveCommand({ log, dir, command: "status" }), dir);
  assert.equal(approved.state, "ready-for-review");
  if (approved.state !== "ready-for-review" || !approved.openingApproved || !approved.approval) throw new Error("Actual TEST approval did not verify");
  assert.equal(approved.approval.approvalHash, parsed.approvalHash);
  assert.equal(approved.selectionHash, selected.selectionHash);
  assert.equal(approved.timing.generationStartedAt, selected.timing.generationStartedAt);
  retainBodyLive(log, "approved-opening-test-only.json", approved); return approved;
}

function bodyRequest(scope: SyntheticLiveFlow, approved: Ready) {
  scope.assertSynthetic(); const { log, dir } = scope; assert.ok(approved.approval);
  const before = observeHumanCutJob(dir), pointer = before.job.guidedHandoffV2!;
  assert.equal(before.sha256, approved.journal.sha256);
  const submission = parseContinueApprovedOpening({ schemaVersion: 1, operation: "continue-approved-opening", idempotencyKey: randomUUID(),
    expectedToken: before.job.token, expectedJournalHash: before.sha256, openingApprovalHash: approved.approval.approvalHash,
    selectionHash: approved.selectionHash, proposalReadinessHash: pointer.proposalReadinessHash, treatmentDraftRevisionHash: pointer.treatmentDraftRevisionHash });
  return { submission, before, request: retainBodyLive(log, "body-request.json", submission) };
}

async function bodyReplay(input: { log: BodyLiveLog; dir: string; result: GuidedBodyCandidateV1;
  request: ReturnType<typeof bodyRequest>; generationStartedAt: string }) {
  const { log, dir, result, request, generationStartedAt } = input;
  const inventoryRoot = path.join(dir, "guided-v2-operations"), inventory = bodyLiveMetadataInventory(inventoryRoot);
  const status = parseGuidedBodyStatus(await bodyLiveBodyCommand({ log, dir, command: "status", generationStartedAt }));
  assertBodyLiveStatus(status, result);
  const replay = parseGuidedBodyRunResult(await bodyLiveBodyCommand({ log, dir, command: "run", request: request.request, generationStartedAt }));
  assert.equal(replay.replayed, true);
  if (!replay.replayed) throw new Error("Identical body request unexpectedly ran fresh work");
  assertBodyLiveStatus(replay.status, result);
  const changed = retainBodyLive(log, "body-different-request.json", { ...request.submission, idempotencyKey: randomUUID() });
  await assert.rejects(bodyLiveBodyCommand({ log, dir, command: "run", request: changed, generationStartedAt }), (failure) => {
    assertBodyLiveConflict(failure); return true;
  });
  assert.deepEqual(bodyLiveMetadataInventory(inventoryRoot), inventory);
  assert.equal(observeHumanCutJob(dir).sha256, result.journalHash);
  assert.equal(observeCutPreviewFile(result.candidate.path, 2 * 1024 ** 3).sha256, result.candidate.sha256);
  retainBodyLive(log, "body-read-only-replay.json", { status, replay, differentRequestRejected: true,
    inventoryScope: "all-operation-stat-metadata-plus-final-streamed-sha-not-all-media-redecode", scope: BODY_LIVE_TEST_SCOPE, genuineHumanAcceptance: false });
}

export async function generateLiveBody(scope: SyntheticLiveFlow, approved: Ready, captioned: boolean) {
  scope.assertSynthetic();
  const { log, dir } = scope, generationStartedAt = approved.timing.generationStartedAt;
  if (typeof generationStartedAt !== "string") throw new Error("Approved TEST opening omitted its original generation clock");
  const request = bodyRequest(scope, approved);
  const result = parseGuidedBodyRunResult(await bodyLiveBodyCommand({ log, dir, command: "run", request: request.request, generationStartedAt }));
  assert.equal(result.replayed, false);
  if (result.replayed) throw new Error("New TEST body request unexpectedly replayed");
  assert.equal(result.requestId, request.submission.idempotencyKey);
  const observed = observeBodyLiveCandidate({ log, dir, requestId: result.requestId, executionId: result.executionId,
    candidate: result.candidate, generationStartedAt, requireCaptions: captioned });
  const raw = readCutPreviewObject(path.join(observed.execution, "claim.json")), claim = parseGuidedBodyExecutionClaim(raw.value);
  assert.equal(raw.sha256, result.admissionClaimHash); assert.equal(claim.beforeJournalHash, request.before.sha256);
  assert.equal(claim.generationStartedAt, generationStartedAt);
  assert.equal(claim.executable, false); assert.equal(claim.workerState, "not-installed", "Separate activation must not rewrite admission v1");
  const held = readCutPreviewObject(path.join(observed.execution, "held-input.json"));
  assert.equal(held.sha256, claim.heldInputHash);
  retainBodyLive(log, "body-actual-result.json", { result, heldReferences: held.value, originalClock: generationStartedAt,
    observation: observed.observation, scope: BODY_LIVE_TEST_SCOPE, genuineHumanAcceptance: false });
  scope.assertSynthetic();
  await bodyReplay({ log, dir, result, request, generationStartedAt });
  return result;
}
