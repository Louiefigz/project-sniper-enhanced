/** Actual complete journal/Buffer/first-CAS records. Source/claim/native admission remains TEST-stubbed. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import { guidedFixture } from "@/lib/producer/__tests__/_guided-cut-fixture";
import { autoEditRequestKey, canonicalJson, canonicalJsonSha256 } from "../auto-edit-hash";
import { autoEditJobPath, parseAutoEditJobRecord } from "../auto-edit-job-persistence";
import { atomicCreateFileSync } from "../atomic-file";
import { commitGuidedJob } from "../guided-cut-v2";
import { observeHumanCutJob, saveHumanCutJobSnapshot } from "../human-cut-acceptance-store";
import { commitPreparedSourceColorCleanup } from "../guided-source-color-cleanup-pending-commit";
import { readSourceColorCleanupAttempt } from "../guided-source-color-cleanup-attempt-read";
import { readSourceColorCleanupPending, type SourceColorCleanupPendingReadInput } from "../guided-source-color-cleanup-pending-read";
import { snapshotSourceColorMetadata } from "../guided-source-color-staging-hold";
import { cleanupAttemptWriterFixture } from "./_guided-source-color-cleanup-attempt-fixture";

/** Create only a new disjoint TEST job template; no existing staged source/project bytes are overwritten. */
function fullJob(f: ReturnType<typeof cleanupAttemptWriterFixture>) {
  const held = f.input.held, hash = "a".repeat(64), at = held.claim.generationStartedAt;
  const template = guidedFixture(path.join(f.staging.root, "TEST-pending-journal-seed"), {
    schemaVersion: 2, mode: "guided", afterCut: "treatment-then-intro", approvalPolicy: "explicit-human" });
  const job = template.run.job, partial = held.job.ctx.pipeline!;
  job.ctx.dir = f.staging.producerDir;
  job.ctx.pipeline = { schemaVersion: 1, runId: "TEST-pending", digest: hash, snapshotRoot: partial.snapshotRoot,
    lockPath: path.join(f.staging.root, "TEST-original-pipeline-lock.json"), files: partial.files };
  job.requestKey = autoEditRequestKey(job.ctx);
  const core = { schemaVersion: 1 as const, requestKey: job.requestKey, planHash: hash, authorityDigest: hash,
    cutAuthorityDigest: hash, cutApprovalReceiptHash: hash, cutReviewApprovalReceiptHash: hash,
    pictureLockHash: hash, timelineMapHash: hash, projectionReceiptHash: hash, createdAt: at };
  Object.assign(job, { status: "treatment_admitted", checkpoint: "cut_reviewed", requestedAt: at, updatedAt: at,
    cutApprovalWaitStartedAt: at, cutApprovalRequest: { ...core, requestHash: canonicalJsonSha256(core) },
    cutPreview: { executionKey: hash, receiptHash: hash },
    guidedHandoffV2: { schemaVersion: 2, cutDecisionHash: hash, cutActivationHash: hash, pictureLockedRevisionHash: hash,
      treatmentAdmissionHash: hash, treatmentProposalHash: hash, proposalReadinessHash: hash, treatmentDraftRevisionHash: hash,
      openingExecutionClaimHash: held.claimHash, openingProcessOutcomeHash: held.job.guidedHandoffV2!.openingProcessOutcomeHash } });
  job.events = job.events.map(event => ({ ...event, at }));
  return job;
}

/** Exposed before the actual writer starts, so independent first-CAS tests share complete real journal bytes. */
export function cleanupPendingPreRecordFixture(t: TestContext, f = cleanupAttemptWriterFixture(t),
  parent?: { sha256: string; guard: () => void }, initialize?: (job: ReturnType<typeof fullJob>) => void) {
  const dir = f.staging.producerDir;
  if (parent && initialize) throw new Error("TEST initial job setup cannot change an existing claimed parent");
  const original = parent ? structuredClone(observeHumanCutJob(dir).job) : fullJob(f);
  initialize?.(original);
  const job = parseAutoEditJobRecord(original);
  if (parent) job.guidedHandoffV2!.openingProcessOutcomeHash = f.input.held.job.guidedHandoffV2!.openingProcessOutcomeHash;
  assert(dir.startsWith(f.staging.root + path.sep)); assert.equal(fs.realpathSync(dir), dir);
  if (parent) commitGuidedJob({ job, beforeHash: parent.sha256, guard: parent.guard });
  else atomicCreateFileSync(autoEditJobPath(dir), canonicalJson(job));
  const before = observeHumanCutJob(dir); assert(Buffer.isBuffer(before.bytes));
  saveHumanCutJobSnapshot(dir, before); Object.assign(f.input.held, before);
  return { ...f, before };
}

/** Explicit original-claim and media-provenance TEST leaves, usable with caller's real persistent lease guards. */
export function cleanupPendingReadLeaves(f: Pick<ReturnType<typeof cleanupPendingPreRecordFixture>,
  "before" | "input" | "readerDependencies" | "media">, counts = { claim: 0, attempt: 0 }) {
  return { claim: (dir: string, hash: string) => {
    counts.claim++; assert.equal(dir, f.before.job.ctx.dir); assert.equal(hash, f.before.sha256);
    return { ...snapshotSourceColorMetadata(f.input.held), observationScope: "historical-owned-claim-not-active-or-selectable" as const };
  }, attempt: (value: Parameters<typeof readSourceColorCleanupAttempt>[0]) => {
    counts.attempt++;
    const media: typeof f.readerDependencies.media = (held, capture) => {
      assert.equal(held.sha256, f.before.sha256); assert.deepEqual(held.claim, f.input.held.claim);
      for (const ref of f.media.files) capture(ref);
    };
    return readSourceColorCleanupAttempt(value, { ...f.readerDependencies, media });
  } };
}

/** Actual recording and first CAS; only original claim/OS/tool/native provenance is a code-only stub. */
export async function cleanupPendingReadFixture(t: TestContext) {
  const f = cleanupPendingPreRecordFixture(t), recorded = await f.write();
  const committed = commitPreparedSourceColorCleanup(recorded), current = observeHumanCutJob(f.before.job.ctx.dir);
  const callbacks = { guard: () => {}, remaining: () => 295_000 }, counts = { guard: 0, remaining: 0, claim: 0, attempt: 0 };
  const input: SourceColorCleanupPendingReadInput = { dir: f.before.job.ctx.dir,
    guard: () => { counts.guard++; callbacks.guard(); }, remainingMs: () => { counts.remaining++; return callbacks.remaining(); } };
  const dependencies = cleanupPendingReadLeaves(f, counts);
  const objects = path.join(input.dir, ".sniper-authority-v1/objects/receipts");
  const files = { journal: autoEditJobPath(input.dir), fact: path.join(objects, `${recorded.factHash}.json`),
    result: path.join(objects, `${recorded.fact.cleanupResultHash}.json`),
    snapshot: path.join(input.dir, "human-cut-job-snapshots", `${f.before.sha256}.json`) };
  return { ...f, recorded, committed, current, pendingInput: input, pendingDependencies: dependencies,
    callbacks, counts, files, read: () => readSourceColorCleanupPending(input, dependencies) };
}

/** Faults are restricted to four exact original pending TEST files, never selected source or code paths. */
export function replacePendingFile(f: Awaited<ReturnType<typeof cleanupPendingReadFixture>>, name: keyof typeof f.files, bytes?: Buffer): void {
  const file = f.files[name]; assert(file.startsWith(f.staging.root + path.sep)); assert.equal(fs.realpathSync(file), file);
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  const temporary = path.join(path.dirname(file), `TEST-pending-replacement-${randomUUID()}.json`);
  fs.writeFileSync(temporary, bytes ?? fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}
