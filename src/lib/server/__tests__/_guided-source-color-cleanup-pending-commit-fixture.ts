/** Real TEMP project/resource leases and journal CAS, with inherited TEST native/provenance leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import { acquireProjectMutationLease, type ProjectMutationLease } from "../project-mutation-lease";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { mutationProjectRoot } from "@/app/api/_lib/project-mutation";
import { autoEditJobPath } from "../auto-edit-job-persistence";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import type { RecordedSourceColorCleanupAttempt } from "../guided-source-color-cleanup-attempt";
import { cleanupPendingPreRecordFixture } from "./_guided-source-color-cleanup-pending-read-fixture";

/** Register release before the inherited exact-root cleanup, then hold real guards before recording. */
export function cleanupPendingCommitFixture(t: TestContext, initial?: ReturnType<typeof cleanupPendingPreRecordFixture>,
  originalLease?: ProjectMutationLease) {
  const owned: { lease?: ProjectMutationLease } = {};
  t.after(() => owned.lease?.release());
  const f = initial ?? cleanupPendingPreRecordFixture(t), dir = f.before.job.ctx.dir;
  assert.equal(mutationProjectRoot(dir), f.staging.root);
  const acquired = originalLease ? { lease: originalLease } : acquireProjectMutationLease(f.staging.root, "TEST exact prepared cleanup CAS");
  assert(acquired.lease); const lease = acquired.lease;
  if (!originalLease) owned.lease = lease;
  const assertProject = cutPreviewLeaseGuard(dir, lease);
  const assertLeases = () => { assertProject(); f.staging.resource.assertResource(); };
  f.clockCallbacks.guard = assertLeases;
  return { ...f, projectLease: lease, assertProject, assertLeases };
}
export type CleanupPendingCommitFixture = ReturnType<typeof cleanupPendingCommitFixture>;

/** Derive a closed fault allowlist from the actual returned recording and original TEST fixture. */
export function cleanupCommitFiles(f: CleanupPendingCommitFixture, recorded: RecordedSourceColorCleanupAttempt) {
  const dir = f.before.job.ctx.dir, objects = path.join(dir, ".sniper-authority-v1/objects/receipts");
  return { journal: autoEditJobPath(dir), fact: path.join(objects, `${recorded.factHash}.json`),
    result: path.join(objects, `${recorded.fact.cleanupResultHash}.json`),
    snapshot: path.join(dir, "human-cut-job-snapshots", `${f.before.sha256}.json`),
    output: path.join(f.directory, "output.json"), media: f.media.files.find(row => row.role === "outcome")!.path };
}

/** Replace only an explicit original owned TEST target, never a path from a dependency inventory. */
export function replaceCleanupCommitFile(f: CleanupPendingCommitFixture,
  selection: { recorded: RecordedSourceColorCleanupAttempt; name: keyof ReturnType<typeof cleanupCommitFiles>; bytes?: Buffer }): void {
  const file = cleanupCommitFiles(f, selection.recorded)[selection.name], root = fs.realpathSync(f.staging.root);
  assert(file.startsWith(root + path.sep)); assert.equal(fs.realpathSync(file), file);
  assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  const temporary = path.join(path.dirname(file), `TEST-commit-replacement-${randomUUID()}.json`);
  fs.writeFileSync(temporary, selection.bytes ?? fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}

/** Pending failure means retained metadata, never retirement, a second cleanup, or approval. */
export function assertCleanupCommitRetained(f: CleanupPendingCommitFixture, pending: boolean): void {
  const current = observeHumanCutJob(f.before.job.ctx.dir);
  assert.equal(Boolean(current.job.guidedHandoffV2!.openingCleanupHash), pending);
  assert.equal(current.job.guidedHandoffV2!.openingExecutionClaimHash, f.input.held.claimHash);
  assert.equal(current.job.guidedHandoffV2!.openingProcessOutcomeHash, f.before.job.guidedHandoffV2!.openingProcessOutcomeHash);
  assert.deepEqual(fs.readFileSync(f.staged.reservation.path), f.activeBytes);
  assert(!fs.existsSync(path.join(f.directory, "retirement-ack.json")));
  assert(!fs.existsSync(path.join(f.directory, "failure.json"))); assert.equal(f.calls.length, 1);
}
