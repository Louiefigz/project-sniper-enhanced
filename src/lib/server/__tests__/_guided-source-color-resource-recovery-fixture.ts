/** Actual TEMP lease/raw reservation; process/journal/workspace admission is explicitly TEST-stubbed. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import type { TestContext } from "node:test";
import type { HeldOpeningClaim } from "../guided-opening-process";
import type { PrepareGuidedOpeningV2 } from "../../producer/contracts/guided-source-color-v1";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { acquireProjectMutationLease, type ProjectMutationLease } from "../project-mutation-lease";
import { holdOpeningSourceColorProcess } from "../guided-source-color-process-binding";
import { stageGuidedSourceColor } from "../guided-source-color-staging";
import { sourceColorResourceRecoveryDependencies, type SourceColorResourceRecoveryInput } from "../guided-source-color-resource-recovery";
import { sourceColorStagingFixture } from "./_guided-source-color-staging-fixture";

/** The returned reader is a code-only stub, not actual OS/journal settlement evidence. */
function stoppedFixture(held: HeldOpeningClaim, reference: ReturnType<typeof holdOpeningSourceColorProcess>["reference"]) {
  return { receipt: { schemaVersion: 3, kind: "guided-opening-process-outcome", scope: "owned-process-stop-not-media-or-delivery-approval",
    claimHash: held.claimHash, inputSha256: held.claim.inputSha256, executionId: held.claim.executionId,
    intentHash: "d".repeat(64), startedAt: "2026-09-08T00:00:01.000Z", finishedAt: "2026-09-08T00:00:02.000Z",
    elapsedMs: 1000, status: "failed", error: "TEST stopped leaf", timedOut: false, groupStopped: true, forcedStop: false,
    stdout: "", stderr: "", ledgerSha256: "e".repeat(64) }, receiptSha256: "f".repeat(64), intentHash: "d".repeat(64),
    resourceAbsence: "not-observed" as const, sourceColor: structuredClone(reference), nestedOwnership: "resolved-by-normal-return" as const,
    liveDescendants: [], unknownDescendants: [], unrecordedSpawns: [] };
}

/** All cleanup is confined to this fresh fixture; no real workspace lookup or child is used. */
export function sourceColorRecoveryFixture(t: TestContext, initial?: ReturnType<typeof sourceColorStagingFixture>,
  originalSubmission?: PrepareGuidedOpeningV2) {
  const leases: ProjectMutationLease[] = [];
  t.after(() => { for (const lease of leases) lease.release(); });
  const staging = initial ?? sourceColorStagingFixture(t), staged = stageGuidedSourceColor(staging), { claim } = staging.opening;
  const submission: PrepareGuidedOpeningV2 = originalSubmission ?? { schemaVersion: 2, operation: "prepare-guided-opening", idempotencyKey: claim.requestId,
    expectedToken: "TEST-only-original-token", expectedJournalHash: claim.beforeJournalHash, proposalReadinessHash: "b".repeat(64),
    treatmentDraftRevisionHash: "c".repeat(64), sourceColor: structuredClone(staging.sourceColor) };
  const binding = holdOpeningSourceColorProcess({ staging, staged, submission });
  const held = { ...staging.opening, submission, claimHash: staging.opening.claimSha256,
    job: { ctx: { dir: staging.producerDir } } } as unknown as HeldOpeningClaim;
  observeRecoveryFixtureJob(staging.root, held, "initial");
  const actual = stoppedFixture(held, binding.reference), events = { guards: 0, reads: 0, acquires: 0 };
  const callbacks = { guard: () => {}, read: () => {} };
  const input: SourceColorResourceRecoveryInput = { held, stopped: structuredClone(actual),
    projectGuard: () => { events.guards++; callbacks.guard(); }, remainingMs: () => 300_000 };
  const dependencies = { ...sourceColorResourceRecoveryDependencies, workspace: () => staging.root,
    acquire: (directory: string, operation: string) => {
      assert.equal(directory, staging.resource.resource); events.acquires++;
      const acquired = acquireProjectMutationLease(directory, operation);
      if (acquired.lease) leases.push(acquired.lease);
      return acquired;
    }, stopped: (original: HeldOpeningClaim) => {
      assert.equal(original, held); events.reads++; callbacks.read(); return structuredClone(actual);
    } };
  return { staging, staged, input, actual, dependencies, callbacks, events, leases,
    releaseOriginal: () => staging.resource.lease.release(), lock: path.join(staging.resource.resource, ".sniper-project-mutation.lock") };
}

/** Real raw TEST journal observations; this does not replace the explicit job-admission stub. */
export function observeRecoveryFixtureJob(root: string, held: HeldOpeningClaim, stage: "initial" | "attempt"): void {
  assert.equal(fs.realpathSync(root), root);
  const file = path.join(root, `TEST-${stage}-job.json`);
  assert.equal(fs.realpathSync(path.dirname(file)), root);
  fs.writeFileSync(file, JSON.stringify(held.job), { flag: "wx", mode: 0o600 });
  const observed = readCutPreviewObject(file);
  assert(Buffer.isBuffer(observed.bytes)); assert.deepEqual(observed.value, held.job);
  Object.assign(held, observed);
}

/** Replace only this exact fixture's original single-link reservation, never a dependency. */
export function replaceRecoveryReservation(f: ReturnType<typeof sourceColorRecoveryFixture>): void {
  const file = f.staged.reservation.path;
  assert.equal(file, path.join(f.staging.root, ".sniper-color-resource/active.json"));
  assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  const replacement = path.join(path.dirname(file), "TEST-new-reservation-inode.json");
  fs.writeFileSync(replacement, fs.readFileSync(file), { flag: "wx", mode: 0o400 }); fs.renameSync(replacement, file);
}
