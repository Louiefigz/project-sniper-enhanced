/** Actual TEST staged raw metadata; no real source, journal, process settlement or Docker authority. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test, { type TestContext } from "node:test";
import { sourceColorStagingFixture } from "./_guided-source-color-staging-fixture";
import { stageGuidedSourceColor } from "../guided-source-color-staging";
import { holdOpeningSourceColorProcess } from "../guided-source-color-process-binding";
import { assertSourceColorCleanupReservationMetadata, copySourceColorCleanupReservation,
  holdSourceColorCleanupReservation } from "../guided-source-color-cleanup-hold";
import type { HeldOpeningClaim } from "../guided-opening-process";
import type { PrepareGuidedOpeningV2 } from "../../producer/contracts/guided-source-color-v1";
import { parseCurrentOpeningCleanupResult, type OpeningCleanupResultV2 } from "../../producer/contracts/guided-opening-cleanup-v2";

function fixture(t: TestContext) {
  const staging = sourceColorStagingFixture(t), staged = stageGuidedSourceColor(staging), { claim } = staging.opening;
  const submission: PrepareGuidedOpeningV2 = { schemaVersion: 2, operation: "prepare-guided-opening", idempotencyKey: claim.requestId,
    expectedToken: "TEST-only-original-token", expectedJournalHash: claim.beforeJournalHash, proposalReadinessHash: "b".repeat(64),
    treatmentDraftRevisionHash: "c".repeat(64), sourceColor: structuredClone(staging.sourceColor) };
  const binding = holdOpeningSourceColorProcess({ staging, staged, submission });
  const held = { ...staging.opening, submission, claimHash: staging.opening.claimSha256,
    job: { ctx: { dir: staging.producerDir } } } as unknown as HeldOpeningClaim;
  const context = { held, reference: structuredClone(binding.reference), resourceDir: staging.resource.resource,
    guard: () => {}, remainingMs: () => 300_000 };
  return { staging, staged, context, hold: () => holdSourceColorCleanupReservation(context) };
}

function completion(f: ReturnType<typeof fixture>): OpeningCleanupResultV2 {
  const { held, reference } = f.context, stages = ["cleanup-claim-and-controls", "source-color-reservation-read", "cleanup-controls-after",
    "reconcile-source-color-batch", "source-color-reservation-after"];
  return parseCurrentOpeningCleanupResult({ schemaVersion: 2, kind: "guided-opening-cleanup-result", claimPath: held.claimPath,
    claimSha256: held.claimSha256, inputSha256: held.claim.inputSha256, outputRoot: held.claim.outputRoot, executionId: held.claim.executionId,
    cleanupVerified: true, graphics: [], elapsedMs: 4000, stages: stages.map(stage => ({ stage, status: "complete",
      elapsedMs: stage === "reconcile-source-color-batch" ? 3020 : 20 })), budgetScope: "separate-protected-cleanup-not-render-allowance",
    processGroupStopped: "requires-owned-server-observation", openingApproved: false,
    sourceColor: { reservation: reference.reservation, sourceColorHash: reference.sourceColorHash,
      batch: { schemaVersion: 1, kind: "grade-batch-cleanup-result", scope: "reserved-name-cleanup-not-process-settlement-work-or-approval",
        cleanupVerified: true, elapsedMs: 3010, stableAbsenceMs: 3000, passes: 14,
        jobs: f.staged.jobs.map(job => ({ containerName: job.containerName, inspections: 28, removalAttempts: 14,
          successfulRemovalResponses: 0, lastObservation: "absent", canonicalAbsenceProved: true })) } } }) as OpeningCleanupResultV2;
}

/** Every fault write is limited to this fixture's actual regular metadata, never a referenced dependency. */
function rewrite(f: ReturnType<typeof fixture>, file: string): void {
  const allowed = [f.staged.reservation.path, f.context.held.claimPath, f.context.held.claim.inputPath];
  assert(allowed.includes(file)); assert(file.startsWith(f.staging.root + path.sep));
  assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  const replacement = path.join(path.dirname(file), "TEST-new-inode.json");
  fs.writeFileSync(replacement, fs.readFileSync(file), { flag: "wx", mode: 0o400 }); fs.renameSync(replacement, file);
}

test("cold reservation uses original three metadata files and all names even with every sidecar/job file missing", t => {
  const f = fixture(t);
  const files = [f.staged.input.path, ...f.staged.jobs.flatMap(job => [job.input.path, job.implementation.path, job.launchClaim.path])];
  for (const file of files) { assert(file.startsWith(f.staging.root + path.sep)); fs.unlinkSync(file); }
  const held = f.hold(); held.assertCurrent(); held.assertResult(completion(f));
  assert.deepEqual(held.containerNames, f.staged.jobs.map(job => job.containerName));
  assert(Object.isFrozen(held.containerNames)); assert(Object.isFrozen(held.reference));
  assert(fs.existsSync(f.staged.reservation.path));
});

test("first callback cannot adopt replacement reservation/claim/input files", async t => {
  for (const role of ["reservation", "claim", "input"] as const) await t.test(role, t => {
    const f = fixture(t), file = role === "reservation" ? f.staged.reservation.path
      : role === "claim" ? f.context.held.claimPath : f.context.held.claim.inputPath;
    let written = false;
    f.context.guard = () => { if (!written) { written = true; rewrite(f, file); } };
    assert.throws(f.hold, /original file changed/);
  });
});

test("original request, reference and callback identities remain live after a successful cold read", t => {
  const f = fixture(t), held = f.hold(), original = f.context.remainingMs;
  f.context.remainingMs = () => 300_000; assert.throws(held.assertCurrent, /caller identity/);
  f.context.remainingMs = original; f.context.held.submission.expectedToken = "TEST changed";
  assert.throws(held.assertCurrent, /claim\/request\/reference/);
});

test("partial, reordered and substituted cleanup names cannot clear a full reservation", t => {
  const f = fixture(t), held = f.hold(), result = completion(f);
  for (const jobs of [result.sourceColor.batch.jobs.slice(1), [...result.sourceColor.batch.jobs].reverse(),
    [{ ...result.sourceColor.batch.jobs[0], containerName: "sniper-grade-observation-00000000000040008000000000000001" }, ...result.sourceColor.batch.jobs.slice(1)]]) {
    assert.throws(() => held.assertResult({ ...result, sourceColor: { ...result.sourceColor, batch: { ...result.sourceColor.batch, jobs } } }));
  }
  assert.throws(() => held.assertResult({ ...result, sourceColor: { ...result.sourceColor, sourceColorHash: "a".repeat(64) } }));
  assert.throws(() => held.assertResult({ ...result, sourceColor: { ...result.sourceColor,
    reservation: { ...result.sourceColor.reservation, sizeBytes: result.sourceColor.reservation.sizeBytes + 1 } } }));
});

test("raw hash/size, wrong namespace, expired original clock and changed metadata fail closed", async t => {
  for (const kind of ["hash", "size", "namespace", "deadline", "after-read"] as const) await t.test(kind, t => {
    const f = fixture(t);
    if (kind === "hash") f.context.reference.reservation = { ...f.context.reference.reservation, sha256: "a".repeat(64) };
    if (kind === "size") f.context.reference.reservation = { ...f.context.reference.reservation, sizeBytes: f.context.reference.reservation.sizeBytes + 1 };
    if (kind === "namespace") f.context.resourceDir = f.staging.root;
    if (kind === "deadline") f.context.remainingMs = () => { throw new Error("TEST original deadline expired"); };
    if (kind !== "after-read") { assert.throws(f.hold); return; }
    const held = f.hold(); rewrite(f, f.staged.reservation.path); assert.throws(held.assertCurrent);
    assert.throws(() => held.assertResult(completion(f)));
  });
});

test("numeric returned deadline values cannot renew or erase the protected allowance", t => {
  const f = fixture(t);
  for (const remaining of [0, -1, NaN, Infinity, 300_001]) {
    f.context.remainingMs = () => remaining; assert.throws(f.hold, /protected deadline/);
  }
});

test("actual cleanup result remains bound across its first and final owner callbacks", async t => {
  for (const target of [1, 2]) await t.test(`callback ${target}`, t => {
    const f = fixture(t), result = completion(f); let armed = false, calls = 0;
    f.context.guard = () => { if (armed && ++calls === target) result.sourceColor.sourceColorHash = "0".repeat(64); };
    const held = f.hold(); armed = true;
    assert.throws(() => held.assertResult(result), /cleanup result/); assert.equal(calls, target);
  });
});

test("source cleanup cannot authenticate another top-level execution with matching color fields", t => {
  const f = fixture(t), held = f.hold(), original = completion(f);
  for (const patch of [{ claimPath: path.join(f.staging.root, "TEST-other.json") }, { claimSha256: "0".repeat(64) },
    { inputSha256: "0".repeat(64) }, { outputRoot: path.join(f.staging.root, "TEST-other-output") },
    { executionId: "00000000-0000-4000-8000-000000000001" }]) {
    assert.throws(() => held.assertResult({ ...original, ...patch }), /full claim/);
  }
});

test("archive copies preserve original literal bytes and cannot mutate the held original", t => {
  const f = fixture(t), held = f.hold(), original = fs.readFileSync(f.staged.reservation.path);
  const copy = copySourceColorCleanupReservation(held);
  assert.deepEqual(copy, original); copy.fill(0);
  assert.deepEqual(copySourceColorCleanupReservation(held), original);
  assert.deepEqual(fs.readFileSync(f.staged.reservation.path), original);
  assert.throws(() => copySourceColorCleanupReservation({ ...held }), /actual original metadata hold/);
  assert.throws(() => copySourceColorCleanupReservation(JSON.parse(JSON.stringify(held))), /actual original metadata hold/);
});

test("copy cannot hide lost original metadata lifetime or caller expiry", t => {
  const f = fixture(t); let expired = false;
  f.context.remainingMs = () => { if (expired) throw new Error("TEST original deadline"); return 300_000; };
  const held = f.hold(); expired = true;
  assert.throws(() => copySourceColorCleanupReservation(held), /original deadline/);
});

test("final metadata-only sweep authenticates actual hold without renewing or calling owner callbacks", t => {
  const f = fixture(t); let calls = 0;
  f.context.guard = () => { calls++; }; const held = f.hold(), initialCalls = calls;
  assertSourceColorCleanupReservationMetadata(held); assert.equal(calls, initialCalls);
  assert.throws(() => assertSourceColorCleanupReservationMetadata({ ...held }), /actual original metadata hold/);
  rewrite(f, f.staged.reservation.path);
  assert.throws(() => assertSourceColorCleanupReservationMetadata(held), /original file changed/);
  assert.equal(calls, initialCalls);
});
