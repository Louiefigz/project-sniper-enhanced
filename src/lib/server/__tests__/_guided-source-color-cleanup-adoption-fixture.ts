/** Actual TEMP writer, current job, both leases and adoption/CAS. Native/claim admission remains TEST leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import type { TestContext } from "node:test";
import { holdCompletedSourceColorCleanup, type CompletedSourceColorCleanupInput } from "../guided-source-color-cleanup-adoption";
import { snapshotSourceColorMetadata } from "../guided-source-color-staging-hold";
import { autoEditJobPath } from "../auto-edit-job-persistence";
import { cleanupPendingCommitFixture } from "./_guided-source-color-cleanup-pending-commit-fixture";

/** The new recovery clock starts at this TEST request, not by renewing the old native attempt. */
export async function cleanupAdoptionFixture(t: TestContext) {
  const f = cleanupPendingCommitFixture(t), recorded = await f.write(), started = performance.now();
  const allowance = { ms: 300_000 }, callbacks = { remaining: () => {}, workspace: () => {}, claim: () => {} };
  const counts = { remaining: 0, workspace: 0, claim: 0 };
  const input: CompletedSourceColorCleanupInput = { held: f.input.held, projectLease: f.projectLease,
    resource: f.staging.resource, attemptId: recorded.fact.cleanupAttemptId, clock: {
      receivedAt: new Date().toISOString(), elapsedMs: () => performance.now() - started,
      remainingMs: () => { counts.remaining++; callbacks.remaining(); return allowance.ms - (performance.now() - started); },
    } };
  const dependencies = { workspace: () => { counts.workspace++; callbacks.workspace(); return f.staging.root; },
    claim: (dir: string) => {
      counts.claim++; assert.equal(dir, f.before.job.ctx.dir); callbacks.claim();
      return snapshotSourceColorMetadata(f.input.held);
    }, history: { ...f.readerDependencies } };
  return { ...f, recorded, adoptionInput: input, adoptionDependencies: dependencies, adoptionCallbacks: callbacks,
    adoptionCounts: counts, allowance, adopt: () => holdCompletedSourceColorCleanup(input, dependencies) };
}
export type CleanupAdoptionFixture = Awaited<ReturnType<typeof cleanupAdoptionFixture>>;

/** Exact original TEST file allowlist. Never use dependency-supplied arbitrary paths as fault targets. */
export function adoptionFaultFile(f: CleanupAdoptionFixture, name: "journal" | "active" | "claim" | "input" | "prepared" | "output"): string {
  const files = { journal: autoEditJobPath(f.before.job.ctx.dir), active: f.staged.reservation.path,
    claim: f.input.held.claimPath, input: f.input.held.claim.inputPath,
    prepared: path.join(f.directory, "prepared.json"), output: path.join(f.directory, "output.json") };
  const file = files[name], root = fs.realpathSync(f.staging.root);
  assert(file.startsWith(root + path.sep)); assert.equal(fs.realpathSync(file), file);
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  return file;
}
export function replaceAdoptionFile(f: CleanupAdoptionFixture, name: Parameters<typeof adoptionFaultFile>[1]): void {
  const file = adoptionFaultFile(f, name), replacement = path.join(path.dirname(file), `TEST-adoption-${randomUUID()}.json`);
  fs.writeFileSync(replacement, fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(replacement, file);
}

/** A new incomplete sibling is unresolved, never a license to replay the already completed attempt. */
export function addPartialAdoptionSibling(f: CleanupAdoptionFixture): void {
  const directory = path.join(path.dirname(f.directory), randomUUID());
  assert(directory.startsWith(fs.realpathSync(f.staging.root) + path.sep)); fs.mkdirSync(directory, { mode: 0o700 });
}
