/** V3-only settled-timeout extension. Retained TEST protocol bytes, no worker, decoder, process probe or admission. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import test from "node:test";
import { readStoppedOpeningProcess, ownershipUnresolved } from "../guided-opening-process";
import { writeGuidedObject } from "../guided-cut-v2-store";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { openingProcessFixture } from "./_guided-opening-process-fixture";

for (const version of [1, 2]) test(`historical V${version} refuses timeout without actual forced-stop flag`, t => {
  const f = openingProcessFixture({ timedOut: true, forcedStop: false }, version); t.after(f.cleanup); f.write();
  assert.throws(() => readStoppedOpeningProcess(f.held), /absent, ambiguous or changed/);
});

for (const version of [1, 2]) test(`historical V${version} normal and forced outcomes retain their exact semantics`, t => {
  const normal = openingProcessFixture({}, version), forced = openingProcessFixture({ timedOut: true, forcedStop: true }, version);
  t.after(normal.cleanup); t.after(forced.cleanup); normal.write(); forced.write();
  assert.equal(ownershipUnresolved(readStoppedOpeningProcess(normal.held)), false);
  assert.equal(ownershipUnresolved(readStoppedOpeningProcess(forced.held)), true);
});

test("V3 actual completed wrapper permits a truthful settled timeout as failure, never completion", t => {
  const f = openingProcessFixture({ timedOut: true, forcedStop: false }, 3); t.after(f.cleanup); f.write();
  const stopped = readStoppedOpeningProcess(f.held);
  assert.equal(stopped.receipt.status, "failed"); assert.equal(stopped.receipt.timedOut, true);
  assert.equal(stopped.receipt.forcedStop, false); assert.equal(stopped.nestedOwnership, "resolved-by-normal-return");
  const complete = openingProcessFixture({ timedOut: true, status: "complete", error: "" }, 3);
  t.after(complete.cleanup); complete.write(); assert.throws(() => readStoppedOpeningProcess(complete.held));
});

test("V3 settled timeout cannot hide an unrecorded nested spawn even with a complete hash-held wrapper", t => {
  const f = openingProcessFixture({ timedOut: true }, 3); t.after(f.cleanup);
  const file = path.join(f.root, "owned-process-ledger.media.jsonl");
  assert.equal(fs.realpathSync(file), file); assert(fs.lstatSync(file).isFile()); assert.equal(fs.lstatSync(file).nlink, 1);
  const rows = fs.readFileSync(file, "utf8").trimEnd().split("\n");
  rows.splice(1, 0, JSON.stringify({ event: "intent", pid: null, argv0: "/TEST/unspawned-child", at: 100.5 }));
  const bytes = rows.join("\n") + "\n"; fs.writeFileSync(file, bytes);
  f.outcome.ledgerSha256 = createHash("sha256").update(bytes).digest("hex");
  f.activation.outcomeSha256 = canonicalJsonSha256(f.outcome);
  f.held.job.guidedHandoffV2!.openingProcessOutcomeHash = writeGuidedObject(f.held.job.ctx.dir, f.activation); f.write();
  assert.throws(() => readStoppedOpeningProcess(f.held), /complete original nested settlement/);
});

test("V3 settled timeout still requires exact separately held ledger bytes", t => {
  const f = openingProcessFixture({ timedOut: true, ledgerSha256: "f".repeat(64) }, 3); t.after(f.cleanup); f.write();
  assert.throws(() => readStoppedOpeningProcess(f.held), /ledger bytes changed/);
});

test("V3 cannot borrow legacy activation schema even with matching outcome bytes", t => {
  const f = openingProcessFixture({ timedOut: true }, 3); t.after(f.cleanup); f.activation.schemaVersion = 1;
  f.held.job.guidedHandoffV2!.openingProcessOutcomeHash = writeGuidedObject(f.held.job.ctx.dir, f.activation); f.write();
  assert.throws(() => readStoppedOpeningProcess(f.held), /absent, ambiguous or changed/);
});
