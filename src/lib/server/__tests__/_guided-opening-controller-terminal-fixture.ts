/** Real preclaim parent, live lease and terminal CASes. Original creative/claim/native admission are TEST leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import type { TestContext } from "node:test";
import { guidedFixture } from "@/lib/producer/__tests__/_guided-cut-fixture";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { atomicCreateFileSync } from "../atomic-file";
import { autoEditRequestKey, canonicalJson, canonicalJsonSha256 } from "../auto-edit-hash";
import { autoEditJobPath, parseAutoEditJobRecord } from "../auto-edit-job-persistence";
import { observeHumanCutJob, saveHumanCutJobSnapshot } from "../human-cut-acceptance-store";
import { commitGuidedJob } from "../guided-cut-v2";
import { writeGuidedObject } from "../guided-cut-v2-store";
import { acquireProjectMutationLease, type ProjectMutationLease } from "../project-mutation-lease";
import { beginOpeningControllerClaim, bindOpeningControllerClaim, holdOpeningControllerLifecycle } from "../guided-opening-controller-lifecycle";
import type { OpeningExecutionInput } from "../guided-opening-execution";
import { sourceColorStagingFixture } from "./_guided-source-color-staging-fixture";
import { sourceColorRecoveryFixture } from "./_guided-source-color-resource-recovery-fixture";
import { sourceColorCleanupProcessFixture } from "./_guided-source-color-cleanup-process-fixture";
import { cleanupAttemptPreRecordFixture } from "./_guided-source-color-cleanup-attempt-read-fixture";
import { cleanupAttemptWriterFixture } from "./_guided-source-color-cleanup-attempt-fixture";
import { cleanupPendingPreRecordFixture } from "./_guided-source-color-cleanup-pending-read-fixture";
import { cleanupPendingCommitFixture } from "./_guided-source-color-cleanup-pending-commit-fixture";
import { sourceColorReadIntegrationFixture } from "./_guided-source-color-read-integration-fixture";

type Early = Parameters<NonNullable<Parameters<typeof sourceColorStagingFixture>[1]>>[0];

/** Same inert bytes as the downstream fixture will publish, declared in the parent BEFORE any claim. */
function originalPipeline(root: string) {
  const hash = (bytes: string) => createHash("sha256").update(bytes).digest("hex");
  return { schemaVersion: 1 as const, runId: "TEST-original-controller", digest: "a".repeat(64),
    snapshotRoot: path.join(root, "TEST-original-pipeline"), lockPath: path.join(root, "TEST-original-pipeline-lock.json"),
    files: [{ path: "scripts/producer/guided_opening_cleanup.py", hash: "a".repeat(64) },
      { path: "scripts/producer/headless/process_runner.py", hash: hash("# TEST inert runner; never executed\n") },
      { path: "scripts/producer/guided_opening_media.py", hash: hash("# TEST inert media worker; never executed\n") },
      { path: "scripts/producer/guided_opening_read.py", hash: hash("# TEST inert read worker; never executed\n") }] };
}

/** New-only parent is published BEFORE the claim exists; no sealed input or parent snapshot is repaired. */
function beforeClaim(f: Early) {
  const template = guidedFixture(path.join(f.root, "TEST-controller-journal-seed"), {
    schemaVersion: 2, mode: "guided", afterCut: "treatment-then-intro", approvalPolicy: "explicit-human" });
  const job = structuredClone(template.run.job), dir = f.context.producerDir, hash = "a".repeat(64);
  job.ctx.dir = dir; job.ctx.pipeline = originalPipeline(f.root); job.requestKey = autoEditRequestKey(job.ctx);
  const earlier = new Date(Date.now() - 60_000); earlier.setUTCSeconds(0, 0);
  const at = earlier.toISOString(), core = { schemaVersion: 1 as const, requestKey: job.requestKey, planHash: hash, authorityDigest: hash,
    cutAuthorityDigest: hash, cutApprovalReceiptHash: hash, cutReviewApprovalReceiptHash: hash,
    pictureLockHash: hash, timelineMapHash: hash, projectionReceiptHash: hash, createdAt: at };
  job.status = "treatment_admitted"; job.checkpoint = "cut_reviewed";
  job.cutApprovalWaitStartedAt = at; job.cutApprovalRequest = { ...core, requestHash: canonicalJsonSha256(core) };
  job.cutPreview = { executionKey: hash, receiptHash: hash };
  job.updatedAt = at; job.requestedAt = at; job.events = job.events.map(event => ({ ...event, at }));
  job.guidedHandoffV2 = { schemaVersion: 2, cutDecisionHash: hash, cutActivationHash: hash, pictureLockedRevisionHash: hash,
    treatmentAdmissionHash: hash, treatmentProposalHash: hash, proposalReadinessHash: hash,
    treatmentDraftRevisionHash: hash };
  job.token = "TEST-only-original-token";
  atomicCreateFileSync(autoEditJobPath(dir), canonicalJson(parseAutoEditJobRecord(job)));
  const before = observeHumanCutJob(dir); saveHumanCutJobSnapshot(dir, before); return before;
}

/** The root supplies actual launch construction; this hook can run only before original staging capture. */
export interface TerminalFixtureLaunch {
  start: (input: { dir: string; before: string; sourceColor: Early["context"]["selection"]; token: string }) => {
    held: Parameters<typeof holdOpeningControllerLifecycle>[0]["launch"];
    active: Parameters<typeof holdOpeningControllerLifecycle>[0]["activation"];
  };
}

/** Capture the actual controller owner on the untouched preclaim journal, not from a later cleanup DTO. */
function controllerParent(f: Early, launch: TerminalFixtureLaunch) {
  const before = beforeClaim(f), dir = before.job.ctx.dir;
  const records = launch.start({ dir, before: before.sha256, sourceColor: f.context.selection, token: before.job.token });
  const acquired = acquireProjectMutationLease(f.root, "TEST original controller terminal lifecycle"); assert(acquired.lease);
  const lease = acquired.lease, guard = cutPreviewLeaseGuard(dir, lease);
  const lifecycle = holdOpeningControllerLifecycle({ launch: records.held, activation: records.active, lease });
  return { before, records, lease, guard, lifecycle };
}

/** Original claim bytes are new-only objects; the actual parent CAS is observed, never inferred from a hash. */
function enterClaim(staging: ReturnType<typeof sourceColorStagingFixture>, owner: ReturnType<typeof controllerParent>) {
  const { claim, claimPath, claimSha256 } = staging.opening, before = owner.before;
  assert.equal(claim.beforeJournalHash, before.sha256);
  assert.equal(observeHumanCutJob(staging.producerDir).sha256, before.sha256);
  const input = { proposal: { ...before, clock: { hash: claim.clockHash }, generationStartedAt: claim.generationStartedAt },
    operation: { executionId: claim.executionId, execution: path.dirname(claimPath), record: { submission: owner.records.held.intent.submission } },
    invocation: { inputPath: claim.inputPath, inputSha256: claim.inputSha256,
      input: { executionId: claim.executionId, executionInputHash: claim.executionInputHash } },
    lease: owner.lease, remainingMs: () => 1000, budgetAdmissionHash: claim.budgetAdmissionHash } as unknown as OpeningExecutionInput;
  beginOpeningControllerClaim(owner.lifecycle, input);
  const claimHash = writeGuidedObject(staging.producerDir, claim); assert.equal(claimHash, claimSha256);
  commitGuidedJob({ beforeHash: before.sha256, guard: owner.guard, job: { ...before.job,
    guidedHandoffV2: { ...before.job.guidedHandoffV2!, openingExecutionClaimHash: claimHash } } });
  const claimed = observeHumanCutJob(staging.producerDir); saveHumanCutJobSnapshot(staging.producerDir, claimed);
  const bound = { claim, claimPath, claimSha256, claimHash, journalHash: claimed.sha256 };
  bindOpeningControllerClaim(owner.lifecycle, bound); return { input, claimed, bound };
}

/** Actual bound claim before source-color staging starts; no media, reservation or cleanup is created. */
export function openingControllerPrelaunchFixture(t: TestContext, launch: TerminalFixtureLaunch) {
  const owned: { lease?: ProjectMutationLease; parent?: ReturnType<typeof controllerParent> } = {};
  t.after(() => owned.lease?.release());
  const staging = sourceColorStagingFixture(t, f => {
    const parent = controllerParent(f, launch); owned.parent = parent; owned.lease = parent.lease;
    return { beforeJournalHash: parent.before.sha256, clockHash: parent.records.held.intent.origin.clockHash,
      generationStartedAt: parent.records.held.intent.origin.startedAt };
  });
  const parent = owned.parent!; assert(parent);
  const entered = enterClaim(staging, parent);
  return { staging, parent, entered };
}

/** Actual cleanup writer/readers and project/resource guards; only native and original admission are TEST stubs. */
export async function openingControllerTerminalFixture(t: TestContext, launch: TerminalFixtureLaunch) {
  const { staging, parent, entered } = openingControllerPrelaunchFixture(t, launch);
  const original = fs.readFileSync(staging.opening.claimPath);
  assert(parent.records.held.intent.schemaVersion === 2);
  const recovery = sourceColorRecoveryFixture(t, staging, parent.records.held.intent.submission);
  const process = sourceColorCleanupProcessFixture(t, recovery);
  const preRecord = cleanupAttemptPreRecordFixture(t, process), writer = cleanupAttemptWriterFixture(t, preRecord);
  const pending = cleanupPendingPreRecordFixture(t, writer, { sha256: entered.claimed.sha256, guard: parent.guard });
  const fixture = await sourceColorReadIntegrationFixture(t, cleanupPendingCommitFixture(t, pending, parent.lease));
  assert.deepEqual(fs.readFileSync(staging.opening.claimPath), original);
  assert.equal(fixture.cleanup.held.claim.beforeJournalHash, parent.before.sha256);
  assert.deepEqual(fixture.cleanup.held.job.ctx, parent.before.job.ctx);
  assert.equal(fixture.cleanup.held.job.token, parent.before.job.token);
  assert.deepEqual(fixture.cleanup.held.submission, parent.records.held.intent.submission);
  const { openingExecutionClaimHash: claimHash, openingProcessOutcomeHash: _outcome, ...pointer } = fixture.cleanup.held.job.guidedHandoffV2!;
  assert.equal(claimHash, entered.bound.claimHash); void _outcome;
  assert.deepEqual(pointer, parent.before.job.guidedHandoffV2);
  return { ...fixture, parent, entered };
}
