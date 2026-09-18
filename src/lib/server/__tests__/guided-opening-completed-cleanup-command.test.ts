/** Actual CLI completion status/recovery on TEMP leases; original claim/native leaves remain TEST-only. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test, { type TestContext } from "node:test";
import { executeOpeningCommand, openingCommandServices } from "../../../../scripts/producer/guided-opening";
import { parseRecoverCompletedOpeningCleanup } from "../../producer/contracts/guided-opening-v1";
import { readCompletedOpeningCleanup, assertCompletedOpeningCleanupRead, openingCleanupStoreDependencies } from "../guided-opening-cleanup-store";
import { reconcileCompletedSourceColorCleanup, sourceColorCleanupRecoveryDependencies } from "../guided-source-color-cleanup-recovery";
import { completedRecoveryFixture } from "./_guided-source-color-completed-recovery-fixture";
import { replaceAdoptionFile, addPartialAdoptionSibling } from "./_guided-source-color-cleanup-adoption-fixture";

/** Keep every lazy default identity intact; override and restore only its existing TEST leaves. */
function commandDependencies(t: TestContext, controls: Awaited<ReturnType<typeof completedRecoveryFixture>>["recoveryControls"]): void {
  const recovery = sourceColorCleanupRecoveryDependencies, store = openingCleanupStoreDependencies;
  const groups: Array<[object, object]> = [
    [recovery, { acquireProject: controls.acquireProject }], [recovery.pending, controls.pending],
    [recovery.resource, controls.resource], [recovery.final, controls.final], [recovery.read, controls.read],
    [recovery.completed, { workspace: controls.completed.workspace, claim: controls.completed.claim }],
    [recovery.completed.history, controls.completed.history], [recovery.completed.resource, controls.completed.resource],
    [store, { completedClaim: controls.completed.claim }], [store.completedHistory, controls.completed.history],
  ];
  const originals = groups.map(([target, changes]) => ({ target,
    values: Object.fromEntries(Object.keys(changes).map(key => [key, (target as Record<string, unknown>)[key]])) }));
  const getters = ["pending", "resource", "final", "read", "completed"].map(key => ({ key,
    descriptor: Object.getOwnPropertyDescriptor(recovery, key), value: recovery[key as keyof typeof recovery] }));
  const history = store.completedHistory, historyDescriptor = Object.getOwnPropertyDescriptor(store, "completedHistory");
  t.after(() => {
    for (const original of originals) Object.assign(original.target, original.values);
    for (const original of originals) {
      for (const [key, value] of Object.entries(original.values)) assert.equal((original.target as Record<string, unknown>)[key], value);
    }
    for (const { key, descriptor, value } of getters) {
      assert.deepEqual(Object.getOwnPropertyDescriptor(recovery, key), descriptor);
      assert.equal(recovery[key as keyof typeof recovery], value);
    }
    assert.deepEqual(Object.getOwnPropertyDescriptor(store, "completedHistory"), historyDescriptor);
    assert.equal(store.completedHistory, history);
  });
  for (const [target, changes] of groups) Object.assign(target, changes);
}

/** Only default native/claim/acquisition leaves change; actual CLI, status, history, service and CAS always execute. */
async function commandFixture(t: TestContext) {
  const f = await completedRecoveryFixture(t); commandDependencies(t, f.recoveryControls);
  const status = () => executeOpeningCommand(["completed-cleanup-status", f.recoveryInput.dir]);
  const saveRequest = async () => {
    const value = await status() as { state: string; requests: unknown[] };
    assert.equal(value.state, "completed-not-committed"); assert.equal(value.requests.length, 1);
    const submission = parseRecoverCompletedOpeningCleanup(value.requests[0]), file = path.join(f.staging.root, "TEST-completed-recovery-request.json");
    assert(file.startsWith(fs.realpathSync(f.staging.root) + path.sep));
    fs.writeFileSync(file, JSON.stringify(submission), { flag: "wx", mode: 0o600 });
    return { file, submission, bytes: fs.readFileSync(file) };
  };
  return { ...f, status, saveRequest };
}

test("CLI completed status and recovery defaults are actual production implementations", () => {
  assert.equal(openingCommandServices.completedCleanup, readCompletedOpeningCleanup);
  assert.equal(openingCommandServices.recoverCompletedCleanup, reconcileCompletedSourceColorCleanup);
});

test("completed status produces exact persisted request and actual CLI recovery finishes without native replay", async t => {
  const f = await commandFixture(t), request = await f.saveRequest();
  assert.equal(request.submission.cleanupAttemptId, f.recorded.fact.cleanupAttemptId);
  assert.equal(request.submission.preparedSha256, f.recorded.preparedRef.sha256);
  assert.equal(request.submission.expectedJournalHash, f.before.sha256);
  const result = await executeOpeningCommand(["recover-completed-cleanup", f.recoveryInput.dir, request.file]) as { claimRetained: boolean };
  assert.equal(result.claimRetained, false); assert.equal(f.calls.length, 1); assert.equal(f.projects.length, 1);
  assert.equal(f.resources.length, 1); assert.deepEqual(fs.readFileSync(request.file), request.bytes);
  assert(!fs.existsSync(f.files.project)); assert(!fs.existsSync(f.files.resource)); assert(fs.existsSync(f.files.ack));
  await assert.rejects(f.status(), /claim|precleanup/);
  await assert.rejects(executeOpeningCommand(["recover-completed-cleanup", f.recoveryInput.dir, request.file]), /original bytes or identity/);
  assert.equal(f.projects.length, 1); assert.equal(f.calls.length, 1);
});

test("completed status private proof denies DTOs and original-file replacement after the read", async t => {
  const f = await commandFixture(t), value = readCompletedOpeningCleanup(f.recoveryInput.dir);
  assertCompletedOpeningCleanupRead(value);
  assert.throws(() => assertCompletedOpeningCleanupRead({ ...value }), /actual original bounded read/);
  replaceAdoptionFile(f, "prepared"); assert.throws(() => assertCompletedOpeningCleanupRead(value), /identity/);
  assert.equal(f.projects.length, 0); assert.equal(f.calls.length, 1);
});

test("partial history cannot manufacture a status request or acquire ownership", async t => {
  const f = await commandFixture(t); addPartialAdoptionSibling(f);
  await assert.rejects(f.status(), /file set/); assert.equal(f.projects.length, 0); assert.equal(f.resources.length, 0);
});

test("completed status original claim callback cannot rebaseline the current journal", async t => {
  const f = await commandFixture(t); f.adoptionCallbacks.claim = () => replaceAdoptionFile(f, "journal");
  await assert.rejects(f.status(), /identity/); assert.equal(f.projects.length, 0);
});

test("completed request parser is closed and never accepts native, approval or clock overrides", () => {
  const value = { schemaVersion: 1, operation: "recover-completed-guided-opening-cleanup", expectedToken: "TEST-token",
    expectedJournalHash: "a".repeat(64), claimHash: "b".repeat(64), cleanupAttemptId: "11111111-1111-4111-8111-111111111111",
    preparedSha256: "c".repeat(64) };
  assert.equal(parseRecoverCompletedOpeningCleanup(value), value);
  for (const key of ["force", "remainingMs", "clock", "nativeReplay", "approval", "path", "idempotencyKey"]) {
    assert.throws(() => parseRecoverCompletedOpeningCleanup({ ...value, [key]: true }));
  }
  assert.throws(() => parseRecoverCompletedOpeningCleanup({ ...value, preparedSha256: "" }));
  assert.throws(() => parseRecoverCompletedOpeningCleanup({ ...value, cleanupAttemptId: "11111111-1111-1111-8111-111111111111" }));
});

for (const name of ["expectedToken", "preparedSha256"] as const) {
  test(`actual completed CLI refuses stale ${name} without rewriting its request`, async t => {
    const f = await commandFixture(t), request = await f.saveRequest();
    const changed = { ...request.submission, [name]: name === "expectedToken" ? "TEST-stale" : "0".repeat(64) };
    fs.writeFileSync(request.file, JSON.stringify(changed)); const bytes = fs.readFileSync(request.file);
    await assert.rejects(executeOpeningCommand(["recover-completed-cleanup", f.recoveryInput.dir, request.file]), /stale/);
    assert.deepEqual(fs.readFileSync(request.file), bytes); assert.equal(f.resources.length, 0); assert.equal(f.calls.length, 1);
  });
}

test("completed CLI creates its sole protected clock before path/request parsing and never calls pending/native fallbacks", async t => {
  const f = await commandFixture(t), request = await f.saveRequest(), calls: string[] = [], clock = f.recoveryInput.clock;
  const services = { ...openingCommandServices, cleanupClock: () => { calls.push("clock"); return clock; },
    canonicalDir: (dir: unknown) => { calls.push("canonical"); assert.equal(dir, f.recoveryInput.dir); return f.recoveryInput.dir; },
    recoverCompletedCleanup: async (input: Parameters<typeof reconcileCompletedSourceColorCleanup>[0]) => {
      calls.push("completed"); assert.equal(input.clock, clock); assert.equal(input.preparedSha256, request.submission.preparedSha256);
      throw new Error("TEST ambiguous completed response");
    }, recoverCleanup: async () => { throw new Error("TEST forbidden pending fallback"); } };
  await assert.rejects(executeOpeningCommand(["recover-completed-cleanup", f.recoveryInput.dir, request.file], services), /TEST ambiguous/);
  assert.deepEqual(calls, ["clock", "canonical", "completed"]); assert.equal(f.projects.length, 0);
  assert.deepEqual(fs.readFileSync(request.file), request.bytes);
});
