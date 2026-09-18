/** Real TEMP live workflow; native tool/claim/daemon admission remains explicit TEST leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import { runSourceColorCleanupWorkflow, sourceColorCleanupWorkflowDependencies,
  type SourceColorCleanupWorkflowInput } from "../guided-source-color-cleanup-workflow";
import { readRetainedSourceColorCleanupPending } from "../guided-source-color-cleanup-pending-read";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { autoEditJobPath } from "../auto-edit-job-persistence";
import { cleanupPendingReadLeaves } from "./_guided-source-color-cleanup-pending-read-fixture";
import { cleanupPendingCommitFixture } from "./_guided-source-color-cleanup-pending-commit-fixture";

/** Remove ONLY the verified empty TEST attempt placeholder; the actual workflow must create it new-only. */
function uncreatedAttempt(f: ReturnType<typeof cleanupPendingCommitFixture>): void {
  assert(f.directory.startsWith(f.staging.root + path.sep)); assert.equal(fs.realpathSync(f.directory), f.directory);
  const stat = fs.lstatSync(f.directory); assert(stat.isDirectory()); assert.equal(stat.uid, process.getuid!());
  assert.deepEqual(fs.readdirSync(f.directory), []); fs.rmdirSync(f.directory);
}

/** All actual stages execute; only their originally documented leaf observations are substituted. */
export function cleanupWorkflowFixture(t: TestContext) {
  const f = cleanupPendingCommitFixture(t); uncreatedAttempt(f);
  const input: SourceColorCleanupWorkflowInput = { held: f.input.held, projectLease: f.projectLease,
    resource: f.staging.resource, clock: f.writerInput.clock };
  const controls = { ...sourceColorCleanupWorkflowDependencies, workspace: () => f.staging.root,
    attemptId: () => f.input.attemptId, stopped: f.writerDependencies.stopped,
    record: f.writerDependencies, pending: cleanupPendingReadLeaves(f), final: {
      history: (value: Parameters<typeof readRetainedSourceColorCleanupPending>[0], hash: string) =>
        readRetainedSourceColorCleanupPending(value, hash, cleanupPendingReadLeaves(f)),
    } };
  const started = performance.now();
  return { ...f, workflowInput: input, workflowControls: controls,
    run: () => runSourceColorCleanupWorkflow(input, controls), measuredMs: () => performance.now() - started };
}
export type CleanupWorkflowFixture = ReturnType<typeof cleanupWorkflowFixture>;

/** Source and original raw reservation data must not become approved media or silently vanish on early failure. */
export function assertWorkflowBeforeCommit(f: CleanupWorkflowFixture): void {
  const current = observeHumanCutJob(f.before.job.ctx.dir);
  assert.equal(current.sha256, f.before.sha256); assert.deepEqual(fs.readFileSync(f.staged.reservation.path), f.activeBytes);
  assert(!fs.existsSync(path.join(f.directory, "retirement-ack.json")));
  assert(!fs.existsSync(path.join(f.directory, "failure.json")));
}

/** Actual final journal remains distinguishable from a successful caller response. */
export function assertWorkflowFinalRetained(f: CleanupWorkflowFixture): void {
  const current = observeHumanCutJob(f.before.job.ctx.dir), pointer = current.job.guidedHandoffV2!;
  assert(pointer.openingCleanupHash); assert(!pointer.openingExecutionClaimHash); assert(!pointer.openingProcessOutcomeHash);
  assert(!pointer.openingMediaSelectionHash); assert(!pointer.openingApprovalHash);
  assert(!fs.existsSync(f.staged.reservation.path)); assert(fs.existsSync(path.join(f.directory, "retirement-ack.json")));
  assert(!fs.existsSync(path.join(f.directory, "failure.json"))); assert.equal(f.calls.length, 1);
}

/** Only the two exact final artifacts inside this original canonical TEST root may be faulted. */
export function replaceWorkflowFinalFile(f: CleanupWorkflowFixture, name: "journal" | "ack"): void {
  const file = name === "journal" ? autoEditJobPath(f.before.job.ctx.dir) : path.join(f.directory, "retirement-ack.json");
  assert(file.startsWith(f.staging.root + path.sep)); assert.equal(fs.realpathSync(file), file);
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  const temporary = path.join(path.dirname(file), `TEST-workflow-tail-${randomUUID()}.json`);
  fs.writeFileSync(temporary, fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}
