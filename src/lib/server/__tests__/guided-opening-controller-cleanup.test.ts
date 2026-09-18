/** Actual final cleanup chain and finite lifetime only; no live controller release or native qualification is fabricated. */
import assert from "node:assert/strict";
import test, { type TestContext } from "node:test";
import childProcess from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { commitGuidedJob } from "../guided-cut-v2";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { writeGuidedObject } from "../guided-cut-v2-store";
import { holdOpeningControllerCleanup } from "../guided-opening-controller-cleanup";
import { sourceColorReadIntegrationFixture, replaceReadIntegrationArchive } from "./_guided-source-color-read-integration-fixture";

/** Original claim admission is a TEST leaf; add its identical actual content object before this new hold begins. */
async function fixture(t: TestContext) {
  t.mock.method(childProcess, "spawn", () => { throw new Error("TEST native forbidden"); });
  const f = await sourceColorReadIntegrationFixture(t);
  assert.equal(writeGuidedObject(f.cleanup.job.ctx.dir, f.cleanup.held.claim), f.cleanup.held.claimHash);
  return f;
}

/** Only these two literal attempt-owned TEST artifacts are eligible, never an inventory-derived path. */
function faultFile(f: Awaited<ReturnType<typeof fixture>>, name: "failure.json" | "owned-process-ledger.cleanup.jsonl"): string {
  const directory = path.join(path.dirname(f.cleanup.held.claimPath), "cleanup-attempts", f.recorded.fact.cleanupAttemptId);
  assert(directory.startsWith(fs.realpathSync(f.staging.root) + path.sep));
  assert.equal(fs.realpathSync(directory), directory);
  return path.join(directory, name);
}

test("controller cleanup hold reuses actual final proof without reading source media or invoking a worker", async t => {
  const f = await fixture(t), held = holdOpeningControllerCleanup(f.cleanup);
  held.metadata(); held.check(); f.assertProject();
  assert.equal(f.calls.length, 1); assert.equal(f.cleanup.receipt.claimRetained, false);
  assert.equal(f.cleanup.mediaSelected, false); assert(Object.isFrozen(held));
});

test("original terminal archive identity cannot be rebaselined by a later actual cleanup read", async t => {
  const f = await fixture(t), held = holdOpeningControllerCleanup(f.cleanup);
  replaceReadIntegrationArchive(f);
  assert.throws(held.check, /original cleanup proof changed/); f.assertProject(); assert.equal(f.calls.length, 1);
});

test("original terminal raw Buffer remains held across subsequent callbacks", async t => {
  const f = await fixture(t), held = holdOpeningControllerCleanup(f.cleanup);
  assert(Buffer.isBuffer(f.cleanup.held.bytes)); f.cleanup.held.bytes[0] ^= 1;
  assert.throws(held.metadata, /original cleanup proof changed/); f.assertProject();
});

test("actual selection-shaped CAS does not replay the original current-journal hold or renew render time", async t => {
  const f = await fixture(t), held = holdOpeningControllerCleanup(f.cleanup);
  const before = observeHumanCutJob(f.cleanup.job.ctx.dir), job = before.job;
  // Opaque TEST selection admission is not a real media selection; only the existing cleanup reader's allowed journal delta is exercised.
  const selectionHash = writeGuidedObject(job.ctx.dir, { kind: "TEST selection edge only", mediaQualified: false });
  commitGuidedJob({ beforeHash: before.sha256, guard: f.assertProject, job: { ...job,
    guidedHandoffV2: { ...job.guidedHandoffV2!, openingMediaSelectionHash: selectionHash },
    nextEventId: job.nextEventId + 1, message: "TEST permitted journal edge, no media approved",
    events: [...job.events, { id: job.nextEventId, at: job.updatedAt,
      payload: { event: "TEST_selection_edge", openingApproved: false } }].slice(-256) } });
  assert.notEqual(observeHumanCutJob(job.ctx.dir).sha256, before.sha256);
  held.metadata(); held.check(); f.assertProject(); assert.equal(f.calls.length, 1);
});

test("original cleanup ledger identity survives the final callback-free sweep", async t => {
  const f = await fixture(t), held = holdOpeningControllerCleanup(f.cleanup);
  const file = faultFile(f, "owned-process-ledger.cleanup.jsonl"), stat = fs.lstatSync(file);
  assert.equal(fs.realpathSync(file), file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  const temporary = path.join(path.dirname(file), "TEST-controller-ledger-new-only.jsonl");
  fs.writeFileSync(temporary, fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
  assert.throws(held.metadata, /original cleanup proof changed/); f.assertProject();
});

for (const kind of ["regular", "dangling"] as const) test(`late ${kind} cleanup failure marker remains fenced`, async t => {
  const f = await fixture(t), held = holdOpeningControllerCleanup(f.cleanup), file = faultFile(f, "failure.json");
  assert.throws(() => fs.lstatSync(file), { code: "ENOENT" });
  if (kind === "regular") fs.writeFileSync(file, "TEST failure only", { flag: "wx", mode: 0o600 });
  else fs.symlinkSync("TEST-never-created-target", file);
  assert.throws(held.metadata, /failure marker/); f.assertProject(); assert.equal(f.calls.length, 1);
});
