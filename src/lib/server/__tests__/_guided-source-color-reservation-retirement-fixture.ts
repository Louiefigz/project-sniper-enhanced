/** Real TEMP leases, journal writes/readback and exact marker unlink; no native media/daemon admission. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import { commitPreparedSourceColorCleanup } from "../guided-source-color-cleanup-pending-commit";
import { readSourceColorCleanupPending } from "../guided-source-color-cleanup-pending-read";
import { retirePreparedSourceColorReservation, type SourceColorRetirementFaults } from "../guided-source-color-reservation-retirement";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { cleanupPendingCommitFixture } from "./_guided-source-color-cleanup-pending-commit-fixture";
import { cleanupPendingReadLeaves } from "./_guided-source-color-cleanup-pending-read-fixture";

/** Retain the SAME enclosing TEST clock; real project/global guards deliberately do not depend on active.json. */
export async function sourceColorRetirementFixture(t: TestContext) {
  const f = cleanupPendingCommitFixture(t), recorded = await f.write(), committed = commitPreparedSourceColorCleanup(recorded);
  const callbacks = { guard: () => {}, remaining: () => {} }, clock = f.writerInput.clock, originalRemaining = clock.remainingMs;
  const pendingInput = { dir: f.before.job.ctx.dir, guard: () => { callbacks.guard(); f.assertLeases(); },
    remainingMs: () => { callbacks.remaining(); return originalRemaining.call(clock); } };
  const pending = readSourceColorCleanupPending(pendingInput, cleanupPendingReadLeaves(f));
  const retirementInput = { pending, projectLease: f.projectLease, resource: f.staging.resource };
  const dependencies = { workspace: () => f.staging.root };
  const files = { active: f.staged.reservation.path, ack: path.join(f.directory, "retirement-ack.json"),
    archive: recorded.fact.archive.path, media: f.media.files.find(row => row.role === "outcome")!.path };
  return { ...f, recorded, committed, callbacks, pendingInput, pending, retirementInput, retirementDependencies: dependencies, files,
    retire: (faults?: SourceColorRetirementFaults) => retirePreparedSourceColorReservation(retirementInput, dependencies, faults) };
}
export type RetirementFixture = Awaited<ReturnType<typeof sourceColorRetirementFixture>>;

/** Destructive TEST permission is exactly four original canonical files inside this unique fixture. */
function fixtureFile(f: RetirementFixture, name: keyof RetirementFixture["files"]): string {
  const file = f.files[name], root = fs.realpathSync(f.staging.root);
  assert(file.startsWith(root + path.sep)); assert.equal(fs.realpathSync(file), file);
  assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  return file;
}

/** Byte-identical replacement still faults the original inode; no production path comes from an injected reader. */
export function replaceRetirementFile(f: RetirementFixture, name: keyof RetirementFixture["files"], bytes?: Buffer): void {
  const file = fixtureFile(f, name), temporary = path.join(path.dirname(file), `TEST-retirement-replacement-${randomUUID()}.json`);
  fs.writeFileSync(temporary, bytes ?? fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}

/** Simulate only the exact marker's committed-intent crash boundary, never source/job removal. */
export function removeRetirementMarker(f: RetirementFixture): void {
  fs.unlinkSync(fixtureFile(f, "active"));
}

/** Insert only the exact missing TEST marker, including a dangling entry that must still fence retirement. */
export function insertRetirementMarker(f: RetirementFixture, dangling = false): void {
  const file = f.files.active, root = fs.realpathSync(f.staging.root);
  assert(file.startsWith(root + path.sep)); assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  assert.throws(() => fs.lstatSync(file), { code: "ENOENT" });
  if (dangling) fs.symlinkSync(path.join(root, "TEST-never-existing-marker-target"), file);
  else fs.writeFileSync(file, f.activeBytes, { flag: "wx", mode: 0o600 });
}

/** Retirement alone never clears the current claim, records failure or runs cleanup again. */
export function assertRetirementPending(f: RetirementFixture): void {
  const current = observeHumanCutJob(f.before.job.ctx.dir);
  assert.equal(current.sha256, f.committed.pendingJournalHash);
  assert.equal(current.job.guidedHandoffV2!.openingExecutionClaimHash, f.input.held.claimHash);
  assert.equal(current.job.guidedHandoffV2!.openingProcessOutcomeHash, f.before.job.guidedHandoffV2!.openingProcessOutcomeHash);
  assert(!fs.existsSync(path.join(f.directory, "failure.json"))); assert.equal(f.calls.length, 1);
}
