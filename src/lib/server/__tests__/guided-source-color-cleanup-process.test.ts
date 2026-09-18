/** Process-boundary stubs; actual raw reservation and real temporary lifecycle parsing. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import test, { type TestContext } from "node:test";
import { runSourceColorCleanupProcess } from "../guided-source-color-cleanup-process";
import { sourceColorCleanupProcessFixture } from "./_guided-source-color-cleanup-process-fixture";
import { observeOwnedWorkerLedger, ownedProcessLedgerPath } from "../guided-opening-process-ledger";
import { CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";

test("all-name V2 cleanup uses exact original arguments and an attempt-scoped wrapped lifecycle", async t => {
  const f = sourceColorCleanupProcessFixture(t), output = await runSourceColorCleanupProcess(f.input, f.dependencies);
  assert.equal(f.calls.length, 1); const call = f.calls[0], ref = f.input.reservation.reference;
  assert.equal(call.held, f.input.held); assert.equal(call.kind, "cleanup"); assert.equal(call.cleanupAttemptId, f.input.attemptId);
  assert.deepEqual(call.extraArgs, ["--source-color-reservation", ref.reservation.path,
    "--source-color-reservation-sha256", ref.reservation.sha256, "--source-color-request-sha256", ref.sourceColorHash]);
  assert.equal(output.ledger.path, ownedProcessLedgerPath(f.directory, "cleanup")); assert.match(output.ledger.sha256, /^[a-f0-9]{64}$/);
  assert.equal(output.processOutcomeSha256, f.actual.receiptSha256); assert.deepEqual(output.result, f.result);
  assert.equal(output.mediaSelected, false); assert.equal(output.deliveryApproved, false); assert(Object.isFrozen(output.result));
  assert(fs.existsSync(ref.reservation.path)); assert(f.events.stoppedReads >= 5); assert(f.events.toolsChecked >= 5);
  assert.equal(output.invocation.path, path.join(f.directory, "invocation.json"));
  assert.deepEqual(output.invocation.value.tools, output.tools); assert.deepEqual(output.tools, f.tools);
  assert.equal(createHash("sha256").update(fs.readFileSync(output.invocation.path)).digest("hex"), output.invocation.sha256);
});

test("same cleanup attempt cannot replay even a complete prior lifecycle", async t => {
  const f = sourceColorCleanupProcessFixture(t); await runSourceColorCleanupProcess(f.input, f.dependencies);
  await assert.rejects(runSourceColorCleanupProcess(f.input, f.dependencies), /already have started/); assert.equal(f.calls.length, 1);
});

test("forged hold, replaced original callback and nonprivate attempt refuse before tool/native work", async t => {
  const f = sourceColorCleanupProcessFixture(t), reservation = f.input.reservation;
  f.input.reservation = { ...reservation }; await assert.rejects(runSourceColorCleanupProcess(f.input, f.dependencies), /actual original metadata hold/);
  f.input.reservation = reservation;
  f.input.guard = () => { f.input.remainingMs = () => 300_000; };
  await assert.rejects(runSourceColorCleanupProcess(f.input, f.dependencies), /caller identity/);
  fs.chmodSync(f.directory, 0o755);
  await assert.rejects(runSourceColorCleanupProcess(f.input, f.dependencies), /private and canonical/);
  assert.equal(f.calls.length, 0); assert.equal(f.events.toolReads, 0);
});

test("forced, unknown, incomplete or changed media settlement cannot start cleanup", async t => {
  const f = sourceColorCleanupProcessFixture(t), original = structuredClone(f.actual);
  for (const patch of [{ receipt: { ...original.receipt, forcedStop: true } }, { unknownDescendants: [{ pid: 1, argv0: "/TEST", reason: "unknown" }] },
    { unrecordedSpawns: ["/TEST"] }, { sourceColor: { ...original.sourceColor, sourceColorHash: "0".repeat(64) } }]) {
    Object.assign(f.actual, original, patch); await assert.rejects(runSourceColorCleanupProcess(f.input, f.dependencies));
  }
  assert.equal(f.calls.length, 0); assert.equal(f.events.toolReads, 0);
});

test("deadline values cannot renew, remove or overrun the original protected allowance", async t => {
  const f = sourceColorCleanupProcessFixture(t);
  for (const remaining of [0, 250, -1, NaN, Infinity, 300_001]) {
    f.input.remainingMs = () => remaining;
    await assert.rejects(runSourceColorCleanupProcess(f.input, f.dependencies), /protected remainder/);
  }
  assert.equal(f.calls.length, 0);
});

test("media settlement changing during native cleanup is rejected with reservation retained", async t => {
  const f = sourceColorCleanupProcessFixture(t); f.events.afterInvoke = () => { f.actual.receiptSha256 = "0".repeat(64); };
  await assert.rejects(runSourceColorCleanupProcess(f.input, f.dependencies), /stopped evidence/);
  assert.equal(f.calls.length, 1); assert(fs.existsSync(f.staged.reservation.path));
});

test("normal outer return is insufficient without complete cleanup worker lifecycle", async t => {
  const f = sourceColorCleanupProcessFixture(t); f.events.incomplete = true;
  await assert.rejects(runSourceColorCleanupProcess(f.input, f.dependencies), /lifecycle is missing, incomplete/);
  assert(fs.existsSync(f.staged.reservation.path));
});

test("live, unknown or unrecorded cleanup descendants never become a successful output", async t => {
  const f = sourceColorCleanupProcessFixture(t);
  f.dependencies.descendants = () => ({ live: [], unknown: [], unrecordedSpawns: ["/TEST/unrecorded"] });
  await assert.rejects(runSourceColorCleanupProcess(f.input, f.dependencies), /unresolved nested ownership/);
  assert(fs.existsSync(f.staged.reservation.path));
});

test("outer forced-stop failure never runs the success ledger or output path", async t => {
  const f = sourceColorCleanupProcessFixture(t);
  const failure = new CutPreviewProcessError("TEST forced outer stop", { timedOut: true, forcedStop: true,
    groupStopped: true, stdout: JSON.stringify(f.result), stderr: "" });
  f.dependencies.invoke = async () => { throw failure; };
  await assert.rejects(runSourceColorCleanupProcess(f.input, f.dependencies), error => error === failure);
  assert(f.events.toolsChecked > 0); assert(fs.existsSync(f.staged.reservation.path));
  assert(fs.existsSync(path.join(f.directory, "invocation.json")));
  assert(!fs.existsSync(ownedProcessLedgerPath(f.directory, "cleanup")));
});

test("partial native result cannot clear complete original name reservation", async t => {
  const f = sourceColorCleanupProcessFixture(t); f.result.sourceColor.batch.jobs.pop();
  await assert.rejects(runSourceColorCleanupProcess(f.input, f.dependencies), /complete ordered names/);
  assert(fs.existsSync(f.staged.reservation.path));
});

test("captured invocation tools cannot be redirected by a later caller metadata change", async t => {
  const f = sourceColorCleanupProcessFixture(t), original = structuredClone(f.tools); let calls = 0;
  f.input.guard = () => { if (++calls === 2) f.tools.script = "/TEST/not-the-original-worker.py"; };
  f.dependencies.invoke = async request => { assert.deepEqual(request.tools, original); throw new Error("TEST stop before native"); };
  await assert.rejects(runSourceColorCleanupProcess(f.input, f.dependencies), /TEST stop before native/);
  const invocation = JSON.parse(fs.readFileSync(path.join(f.directory, "invocation.json"), "utf8"));
  assert.deepEqual(invocation.tools, original); assert.notEqual(invocation.tools.script, f.tools.script);
});

test("missing captured tool evidence rejects before a cleanup invocation or child can start", async t => {
  const f = sourceColorCleanupProcessFixture(t);
  f.dependencies.toolsUnchanged = () => { throw new Error("TEST original tool bytes changed"); };
  await assert.rejects(runSourceColorCleanupProcess(f.input, f.dependencies), /original tool bytes changed/);
  assert.equal(f.calls.length, 0); assert(!fs.existsSync(path.join(f.directory, "invocation.json")));
});

test("a new attempt cannot hide any prior orphan, malformed or incomplete cleanup attempt", async t => {
  const f = sourceColorCleanupProcessFixture(t), prior = path.join(path.dirname(f.directory), "00000000-0000-4000-8000-000000000010");
  fs.mkdirSync(prior, { mode: 0o700 });
  await assert.rejects(runSourceColorCleanupProcess(f.input, f.dependencies), /prior or unknown attempts/);
  assert.equal(f.calls.length, 0); assert.equal(f.events.toolReads, 0); assert(fs.existsSync(f.staged.reservation.path));
});

test("a sibling cleanup attempt appearing during callbacks is not adopted", async t => {
  const f = sourceColorCleanupProcessFixture(t); let created = false;
  f.input.guard = () => {
    if (created) return;
    created = true; fs.mkdirSync(path.join(path.dirname(f.directory), "TEST-unknown-attempt"), { mode: 0o700 });
  };
  await assert.rejects(runSourceColorCleanupProcess(f.input, f.dependencies), /prior or unknown attempts/);
  assert.equal(f.calls.length, 0); assert.equal(f.events.toolReads, 0);
});

/** Mutate only the explicitly named canonical, owned TEST file after its last normal read. */
async function finalGuardFileMutation(t: TestContext, kind: "reservation" | "ledger"): Promise<void> {
  const f = sourceColorCleanupProcessFixture(t), descendants = f.dependencies.descendants;
  const file = kind === "reservation" ? path.join(f.staging.root, ".sniper-color-resource", "active.json")
    : ownedProcessLedgerPath(f.directory, "cleanup");
  let armed = false, before: Buffer | undefined;
  f.dependencies.descendants = (...args) => { const result = descendants(...args); armed = true; return result; };
  f.input.guard = () => {
    if (!armed || before) return;
    assert(file.startsWith(fs.realpathSync(f.staging.root) + path.sep)); assert.equal(fs.realpathSync(file), file);
    const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
    f.input.reservation.assertCurrent();
    const ledgerSha = observeOwnedWorkerLedger(f.directory, "cleanup", f.tools.script);
    before = fs.readFileSync(file);
    const expected = kind === "reservation" ? f.input.reservation.reference.reservation.sha256 : ledgerSha;
    assert.equal(createHash("sha256").update(before).digest("hex"), expected);
    fs.chmodSync(file, 0o600); fs.appendFileSync(file, "\n");
  };
  await assert.rejects(runSourceColorCleanupProcess(f.input, f.dependencies), /changed|ledger|original/);
  assert(before); const after = fs.readFileSync(file);
  assert.deepEqual(after, Buffer.concat([before, Buffer.from("\n")]));
  assert.notEqual(createHash("sha256").update(after).digest("hex"), createHash("sha256").update(before).digest("hex"));
  assert.equal(f.calls.length, 1); assert(fs.existsSync(f.staged.reservation.path));
  if (kind === "reservation") {
    assert.throws(() => f.input.reservation.assertCurrent(), /original file changed/);
    return;
  }
  f.input.reservation.assertCurrent();
  assert.throws(() => observeOwnedWorkerLedger(f.directory, "cleanup", f.tools.script), /ledger/);
}

test("final original guard cannot change the held reservation after its last read", async t => {
  await finalGuardFileMutation(t, "reservation");
});

test("final original guard cannot change the settled cleanup ledger after its last read", async t => {
  await finalGuardFileMutation(t, "ledger");
});
