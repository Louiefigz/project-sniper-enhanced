/** Actual V3 records/CAS/reader with TEMP leases. Native worker and admission leaves are explicitly TEST-only. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { CutPreviewProcessError } from "@/app/api/producer/auto-edit/cut-preview-process";
import { readStoppedOpeningProcess, ownershipUnresolved } from "../guided-opening-process";
import { readOpeningProcessActivation } from "../guided-opening-process-activation";
import { sourceColorMediaFixture } from "./_guided-source-color-media-process-fixture";

test("actual internal V3 writer binds one TEST native return to V2 activation and actual stopped readback", async t => {
  const f = sourceColorMediaFixture(t), result = await f.run();
  assert.equal(f.calls.invoke, 1); assert.equal(result.receipt.schemaVersion, 3); assert.equal(result.receipt.status, "complete");
  assert(result.stopped); assert.equal(ownershipUnresolved(result.stopped), false);
  assert.deepEqual(readStoppedOpeningProcess(result.held), result.stopped);
  assert.equal(readOpeningProcessActivation(f.staging.producerDir, result.held).fact.schemaVersion, 2);
  assert.deepEqual(f.requests[0].extraArgs, ["--source-color-input", f.staged.input.path, "--source-color-input-sha256",
    f.staged.input.sha256, "--source-color-producer-dir", f.staging.producerDir,
    "--source-color-resource-dir", f.staging.resource.resource]);
  assert.notEqual(result.held.sha256, f.input.held.sha256); assert.equal(result.held.claimHash, f.input.held.claimHash);
  assert(fs.existsSync(f.staged.reservation.path)); assert.equal(result.mediaSelected, false);
  assert.equal(result.openingApproved, false); assert.equal(result.deliveryApproved, false);
});

test("settled normal return never invokes the expired original work callback during durable publication", async t => {
  const f = sourceColorMediaFixture(t); let workAtSettlement = 0;
  f.callbacks.settled = () => { workAtSettlement = f.calls.work; f.clock.expired = true; };
  const result = await f.run(); assert.equal(result.receipt.status, "complete"); assert.equal(f.calls.work, workAtSettlement);
  assert(result.stopped); assert.equal(result.stopped.nestedOwnership, "resolved-by-normal-return");
});

test("truthful settled runner timeout is failed V3, not a fabricated forced stop or success", async t => {
  const f = sourceColorMediaFixture(t);
  f.callbacks.error = new CutPreviewProcessError("TEST deadline after actual outer settlement", {
    groupStopped: true, forcedStop: false, timedOut: true, stdout: "", stderr: "TEST no native work" });
  f.callbacks.settled = () => { f.clock.expired = true; };
  const result = await f.run(); assert.equal(result.receipt.status, "failed"); assert.equal(result.receipt.timedOut, true);
  assert.equal(result.receipt.forcedStop, false); assert(result.stopped);
  assert.equal(result.stopped.nestedOwnership, "resolved-by-normal-return");
});

test("forced outer stop remains unresolved, with original reservation retained", async t => {
  const f = sourceColorMediaFixture(t); f.callbacks.ledger = "missing";
  f.callbacks.error = new CutPreviewProcessError("TEST forced stop", {
    groupStopped: true, forcedStop: true, timedOut: true, stdout: "", stderr: "" });
  const result = await f.run(); assert.equal(result.receipt.status, "failed"); assert(result.stopped);
  assert.equal(ownershipUnresolved(result.stopped), true); assert(fs.existsSync(f.staged.reservation.path));
});

test("unknown actual outer stop remains failed without manufacturing a completed wrapper ledger", async t => {
  const f = sourceColorMediaFixture(t); f.callbacks.ledger = "missing";
  f.callbacks.error = new CutPreviewProcessError("TEST unknown outer group", {
    groupStopped: false, forcedStop: true, timedOut: true, stdout: "", stderr: "TEST observation uncertainty" });
  const result = await f.run(); assert.equal(result.receipt.groupStopped, false); assert.equal(result.receipt.status, "failed");
  assert.equal(result.stopped, null); assert.equal(result.receipt.ledgerSha256, null); assert.equal(f.calls.invoke, 1);
});

for (const ledger of ["missing", "unfinished"] as const) test(`normal return with ${ledger} wrapper ledger never proves settlement`, async t => {
  const f = sourceColorMediaFixture(t); f.callbacks.ledger = ledger;
  const result = await f.run(); assert.equal(result.receipt.status, "failed"); assert.equal(result.stopped, null);
  assert.equal(f.calls.invoke, 1); assert(fs.existsSync(path.join(f.root, "media-process-result.json")));
});

test("possible prior invocation is not replayed or inferred absent from a new call", async t => {
  const f = sourceColorMediaFixture(t); await f.run(); await assert.rejects(f.run(), /pre-outcome|current journal|already|changed/);
  assert.equal(f.calls.invoke, 1);
});

test("prelaunch original work expiry creates no process intent", async t => {
  const f = sourceColorMediaFixture(t); f.clock.expired = true; await assert.rejects(f.run(), /expired/);
  assert.equal(f.calls.invoke, 0); assert.equal(fs.existsSync(path.join(f.root, "media-process-intent.json")), false);
});
