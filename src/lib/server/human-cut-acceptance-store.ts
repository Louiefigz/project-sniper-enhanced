import { mkdirSync } from "node:fs";
import path from "node:path";
import { autoEditRequestKey, canonicalJsonSha256 } from "./auto-edit-hash";
import { autoEditAuthoritySnapshot, type AutoEditAuthoritySnapshot } from "./auto-edit-authority-snapshot";
import { atomicCreateFileSync, atomicCreateJsonSync } from "./atomic-file";
import { writeContentAddressedJsonSync } from "./content-addressed-json";
import { parseAutoEditJobRecord, autoEditJobPath } from "./auto-edit-job-persistence";
import type { AutoEditJob } from "./auto-edit-job-types";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import type { CompatibilityPictureLockResult } from "@/app/api/producer/auto-edit/compatibility-picture-lock";
import { assertCutPreviewDirectory, readCutPreviewObject, readCurrentCutPreview } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseHumanCutAcceptance, parseHumanCutAcceptancePointer, parseHumanCutActivation,
  type HumanCutAcceptanceV1, type HumanCutAuthorityContext, type HumanCutActivationV1 } from "@/lib/producer/contracts/human-cut-acceptance";

/** Only these existing runtime conversation fields may change during exact-v1 continuation. */
export function humanCutContinuationContextHash(ctx: AutoEditCtx): string {
  const { brainSessionId: _session, brainSessionEstablished: _established, ...context } = ctx;
  void _session; void _established;
  return canonicalJsonSha256(context);
}

export function humanCutAuthorityContext(authority: AutoEditAuthoritySnapshot): HumanCutAuthorityContext {
  if (!authority.manifestHash) throw new Error("Human cut acceptance requires a manifest authority");
  return { schemaVersion: authority.schemaVersion, qualityPolicyVersion: authority.qualityPolicyVersion,
    manifestHash: authority.manifestHash, operatorIntentDigest: authority.operatorIntentDigest,
    transcriptDigest: authority.transcriptDigest, referenceDigest: authority.referenceDigest,
    pipelineDigest: authority.pipelineDigest };
}

export function humanCutDirectory(parent: string, name: string): string {
  assertCutPreviewDirectory(parent);
  if (!/^[a-z0-9-]+$/.test(name)) throw new Error("Human cut private directory name is invalid");
  const directory = path.join(parent, name);
  try { mkdirSync(directory, { mode: 0o700 }); }
  catch (error) { if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error; }
  assertCutPreviewDirectory(directory);
  return directory;
}

export function observeHumanCutJob(dir: string) {
  const observed = readCutPreviewObject(autoEditJobPath(dir));
  const job = parseAutoEditJobRecord(observed.value);
  if (job.ctx.dir !== dir) throw new Error("Human cut job belongs to another producer directory");
  return { ...observed, job };
}

/** Preserve the exact observed pre-attempt journal bytes, not a reserialized approximation. */
export function saveHumanCutJobSnapshot(dir: string, observed: ReturnType<typeof observeHumanCutJob>): void {
  const directory = humanCutDirectory(dir, "human-cut-job-snapshots");
  const file = path.join(directory, `${observed.sha256}.json`);
  try { atomicCreateFileSync(file, observed.bytes); }
  catch (error) { if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error; }
  if (readCutPreviewObject(file).sha256 !== observed.sha256) throw new Error("Human cut job snapshot was replaced");
}

function originalJob(dir: string, fact: HumanCutAcceptanceV1): AutoEditJob {
  const file = path.join(dir, "human-cut-job-snapshots", `${fact.originalJobHash}.json`);
  const observed = readCutPreviewObject(file), job = parseAutoEditJobRecord(observed.value);
  if (observed.sha256 !== fact.originalJobHash || job.status !== "awaiting_cut_approval"
      || job.ctx.dir !== dir || job.token !== fact.originalJobToken || job.attempts !== fact.preview.previewAttempt
      || (job.artifactToken ?? job.token) !== fact.preview.runId || job.requestKey !== fact.request.requestKey
      || canonicalJsonSha256(job.ctx) !== fact.acceptedContextHash
      || humanCutContinuationContextHash(job.ctx) !== fact.continuationContextHash
      || canonicalJsonSha256(job.cutApprovalRequest) !== canonicalJsonSha256(fact.request)
      || (job.cutApprovalWaitStartedAt ?? job.updatedAt) !== fact.waitStartedAt
      || fact.request.createdAt > fact.waitStartedAt
      || job.cutPreview?.executionKey !== fact.preview.executionKey || job.cutPreview.receiptHash !== fact.preview.receiptHash) {
    throw new Error("Human cut acceptance differs from its exact paused journal snapshot");
  }
  return job;
}

/** Integrity alone never activates a fact: a durable job pointer is separately required. */
export function readHumanCutAcceptance(dir: string, hash: string): HumanCutAcceptanceV1 {
  parseHumanCutAcceptancePointer({ acceptanceHash: hash });
  const observed = readCutPreviewObject(path.join(dir, "human-cut-acceptances", `${hash}.json`));
  const fact = parseHumanCutAcceptance(observed.value);
  if (fact.producerDir !== dir || observed.sha256 !== hash || canonicalJsonSha256(fact) !== hash) {
    throw new Error("Human cut acceptance file identity changed");
  }
  originalJob(dir, fact);
  return fact;
}

export function writeHumanCutAcceptance(dir: string, value: HumanCutAcceptanceV1): string {
  const fact = parseHumanCutAcceptance(value);
  if (fact.producerDir !== dir) throw new Error("Human cut acceptance directory differs");
  originalJob(dir, fact);
  const written = writeContentAddressedJsonSync(path.join(dir, "human-cut-acceptances"), fact);
  readHumanCutAcceptance(dir, written.hash);
  return written.hash;
}

function assertActivationEvidence(fact: HumanCutAcceptanceV1, activation: HumanCutActivationV1): void {
  const dir = fact.producerDir;
  if (activation.acceptanceHash !== canonicalJsonSha256(fact) || activation.decisionHash !== fact.decisionHash
      || activation.producerDir !== dir) throw new Error("Human cut activation names a different immutable decision");
  const snapshot = readCutPreviewObject(path.join(dir, "human-cut-job-snapshots", `${activation.verifyingJobHash}.json`));
  const job = parseAutoEditJobRecord(snapshot.value), attempt = job.cutAcceptanceAttempt;
  if (snapshot.sha256 !== activation.verifyingJobHash || job.ctx.dir !== dir || job.status !== "awaiting_cut_approval"
      || job.cutAcceptance || job.token !== fact.originalJobToken || job.attempts !== fact.preview.previewAttempt
      || canonicalJsonSha256(job.ctx) !== fact.acceptedContextHash
      || canonicalJsonSha256(job.cutApprovalRequest) !== canonicalJsonSha256(fact.request)
      || job.cutPreview?.executionKey !== fact.preview.executionKey || job.cutPreview.receiptHash !== fact.preview.receiptHash
      || (job.artifactToken ?? job.token) !== fact.preview.runId || job.requestKey !== fact.request.requestKey
      || attempt?.state !== "verifying" || attempt.executionId !== activation.executionId
      || attempt.idempotencyKey !== fact.decision.idempotencyKey || attempt.decisionHash !== activation.decisionHash
      || attempt.receivedAt !== activation.waitStoppedAt || attempt.startedAt !== activation.verificationStartedAt
      || (job.cutApprovalWaitStartedAt ?? job.updatedAt) !== activation.waitStartedAt) {
    throw new Error("Human cut activation differs from its exact verifying journal");
  }
  const start = readCutPreviewObject(path.join(dir, "human-cut-attempts", attempt.idempotencyKey,
    "executions", attempt.executionId, "start.json"));
  if (start.sha256 !== activation.executionStartHash || start.value.schemaVersion !== 1
      || start.value.kind !== "human-cut-verification-start" || start.value.state !== "verifying"
      || start.value.idempotencyKey !== attempt.idempotencyKey
      || start.value.executionId !== attempt.executionId || start.value.decisionHash !== attempt.decisionHash
      || start.value.receivedAt !== attempt.receivedAt || start.value.startedAt !== attempt.startedAt
      || start.value.waitStartedAt !== activation.waitStartedAt) throw new Error("Human cut activation execution evidence changed");
}

/** Missing legacy activation is explicitly unknown; an unreferenced file proves no journal activation. */
export function readHumanCutActivation(job: AutoEditJob, fact: HumanCutAcceptanceV1): HumanCutActivationV1 | null {
  const pointer = parseHumanCutAcceptancePointer(job.cutAcceptance);
  if (!pointer.activationHash) return null;
  const observed = readCutPreviewObject(path.join(job.ctx.dir, "human-cut-activations", `${pointer.activationHash}.json`));
  const activation = parseHumanCutActivation(observed.value);
  if (observed.sha256 !== pointer.activationHash || canonicalJsonSha256(activation) !== pointer.activationHash
      || activation.producerDir !== job.ctx.dir || activation.acceptanceHash !== pointer.acceptanceHash
      || activation.decisionHash !== fact.decisionHash || activation.waitStoppedAt < fact.submittedAt
      || activation.activationRecordedAt > job.updatedAt) throw new Error("Human cut activation identity or clock changed");
  assertActivationEvidence(fact, activation);
  return activation;
}

/** Persist execution evidence before the short CAS; only its later journal pointer activates it. */
export function writeHumanCutActivation(input: {
  observed: ReturnType<typeof observeHumanCutJob>; fact: HumanCutAcceptanceV1; acceptanceHash: string; recordedAt: string;
}): string {
  const { observed, fact } = input, attempt = observed.job.cutAcceptanceAttempt;
  if (!attempt || attempt.state !== "verifying") throw new Error("Human cut activation needs a verifying execution");
  const dir = fact.producerDir;
  const start = readCutPreviewObject(path.join(dir, "human-cut-attempts", attempt.idempotencyKey,
    "executions", attempt.executionId, "start.json"));
  const activation = parseHumanCutActivation({ schemaVersion: 1, kind: "human-cut-activation", scope: fact.scope,
    producerDir: dir, acceptanceHash: input.acceptanceHash, verifyingJobHash: observed.sha256,
    decisionHash: attempt.decisionHash, executionId: attempt.executionId, executionStartHash: start.sha256,
    waitStartedAt: observed.job.cutApprovalWaitStartedAt ?? observed.job.updatedAt,
    waitStoppedAt: attempt.receivedAt, verificationStartedAt: attempt.startedAt, activationRecordedAt: input.recordedAt });
  saveHumanCutJobSnapshot(dir, observed);
  assertActivationEvidence(fact, activation);
  return writeContentAddressedJsonSync(path.join(dir, "human-cut-activations"), activation).hash;
}

/** Existing indices are immutable; an unreferenced index/fact cannot launch a worker. */
export function createHumanCutIndex(file: string, value: unknown): void {
  assertCutPreviewDirectory(path.dirname(file));
  try { atomicCreateJsonSync(file, value); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
    if (canonicalJsonSha256(readCutPreviewObject(file).value) !== canonicalJsonSha256(value)) {
      throw new Error("Human cut immutable index conflicts with its existing value");
    }
  }
}

export function assertHumanCutContext(job: AutoEditJob, fact: HumanCutAcceptanceV1): void {
  if (job.ctx.workflowPolicy !== "cut-first" || job.ctx.deliveryPolicy !== "mp4-only"
      || job.ctx.dir !== fact.producerDir || job.requestKey !== fact.request.requestKey
      || autoEditRequestKey(job.ctx) !== fact.request.requestKey
      || humanCutContinuationContextHash(job.ctx) !== fact.continuationContextHash
      || (job.artifactToken ?? job.token) !== fact.preview.runId
      || canonicalJsonSha256(job.cutApprovalRequest) !== canonicalJsonSha256(fact.request)
      || job.cutPreview?.executionKey !== fact.preview.executionKey || job.cutPreview.receiptHash !== fact.preview.receiptHash
      || canonicalJsonSha256(humanCutAuthorityContext(autoEditAuthoritySnapshot(job.ctx))) !== canonicalJsonSha256(fact.authorityContext)) {
    throw new Error("Human accepted cut context, sources, intent or pipeline changed; an explicit new cut decision is required");
  }
}

export function activeHumanCutAcceptance(job: AutoEditJob): HumanCutAcceptanceV1 {
  const pointer = parseHumanCutAcceptancePointer(job.cutAcceptance);
  const fact = readHumanCutAcceptance(job.ctx.dir, pointer.acceptanceHash);
  if (!Number.isSafeInteger(job.attempts) || job.attempts < fact.continuationAttempt || job.attempts > 10000
      || !job.token || job.token.length > 200 || job.token === fact.originalJobToken) {
    throw new Error("Human cut acceptance is not active in this continuation attempt");
  }
  assertHumanCutContext(job, fact);
  readHumanCutActivation(job, fact);
  return fact;
}

/** Historical preview remains pinned to its original attempt, never the resumed counter. */
export function verifyHumanCutPreview(job: AutoEditJob, fact: HumanCutAcceptanceV1): void {
  const directory = path.join(job.ctx.dir, "cut-previews", fact.request.requestHash, fact.preview.executionKey);
  const preview = readCurrentCutPreview(directory, fact.request);
  const actual = { executionKey: preview.executionKey, receiptHash: preview.receiptHash, mediaSha256: preview.media.sha256,
    runId: preview.runId, previewAttempt: preview.attempt, manifestHash: preview.manifestHash,
    sourceSetDigest: preview.sourceSetDigest, sourceSetReceiptHash: preview.sourceSetReceiptHash,
    toolchainHash: preview.toolchainHash, audioClockHash: preview.audioClockHash };
  if (canonicalJsonSha256(actual) !== canonicalJsonSha256(fact.preview)) throw new Error("Human accepted preview evidence changed");
}

/** Run only after the independent deterministic+critic walls returned this fresh lock. */
export function verifyHumanAcceptedCut(job: AutoEditJob, verified: CompatibilityPictureLockResult): boolean {
  const fact = activeHumanCutAcceptance(job);
  if (verified.hash !== fact.request.pictureLockHash || verified.projectionHash !== fact.request.projectionReceiptHash
      || verified.lock.timelineMapHash !== fact.request.timelineMapHash
      || verified.lock.cutAuthorityDigest !== fact.request.cutAuthorityDigest
      || verified.lock.cutApprovalReceiptHash !== fact.request.cutApprovalReceiptHash
      || verified.lock.cutReviewApprovalReceiptHash !== fact.request.cutReviewApprovalReceiptHash) {
    throw new Error("The current cut differs from the human-accepted picture lock; no automatic recut is authorized");
  }
  verifyHumanCutPreview(job, fact);
  return true;
}
