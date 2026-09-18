/** Prospective-only batching faults; real bounded reads and optional genuine live prelaunch hooks. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { SourceColorStagingRead, holdSourceColorStagingCancellationMetadata } from "../guided-source-color-staging-hold";
import { enterSourceColorPrelaunchCancel, readSourceColorPrelaunchMetadata } from "../guided-source-color-prelaunch-owner";
import { GUIDED_SOURCE_COLOR_TS_FILES } from "../guided-source-color-staging";
import { stagingBatchFixture, replaceBatchPin, replaceBatchParent, rewriteThenRestoreBatchPin,
  assertBatchUnpublished } from "./_guided-source-color-staging-batch-fixture";

for (const hooks of [false, true]) {
  for (const [boundary, role] of [["early", "first"], ["early", "last"], ["end", "first"], ["end", "last"]] as const) {
    test(`${hooks ? "live hooks" : "no hooks"}: ${boundary} original callback cannot replace ${role} prospective pin`, t => {
      const f = stagingBatchFixture(t, hooks); f.at(boundary, () => replaceBatchPin(f, role));
      assert.throws(f.stage, /pin changed|metadata changed|identity changed/); assertBatchUnpublished(f);
    });
  }
  test(`${hooks ? "live hooks" : "no hooks"}: shared parent replacement refuses before publication`, t => {
    const f = stagingBatchFixture(t, hooks); f.at("later", () => replaceBatchParent(f));
    assert.throws(f.stage, /parent changed|directory changed|pin changed/); assertBatchUnpublished(f);
  });
  test(`${hooks ? "live hooks" : "no hooks"}: earlier hashed pin cannot change during a later read`, t => {
    const f = stagingBatchFixture(t, hooks); f.at("later", () => replaceBatchPin(f, "first"));
    assert.throws(f.stage, /pin changed|metadata changed/); assertBatchUnpublished(f);
  });
  test(`${hooks ? "live hooks" : "no hooks"}: restoring earlier pin bytes cannot rebaseline original metadata`, t => {
    const f = stagingBatchFixture(t, hooks); f.at("later", () => rewriteThenRestoreBatchPin(f));
    assert.throws(f.stage, /pin changed|metadata changed/); assertBatchUnpublished(f);
  });
  for (const boundary of ["middle", "end"] as const) test(`${hooks ? "live hooks" : "no hooks"}: ${boundary} original expiry preserves its exact error`, t => {
    const f = stagingBatchFixture(t, hooks), original = new Error("TEST original batch budget expired");
    f.at(boundary, () => { throw original; });
    assert.throws(f.stage, error => error === original); assertBatchUnpublished(f);
  });
  for (const operation of ["publish", "batch", "cancellation", "read", "directory", "code"] as const) test(`${hooks ? "live hooks" : "no hooks"}: caught ${operation} reentry poisons the batch`, t => {
    const f = stagingBatchFixture(t, hooks);
    f.at("later", () => {
      const read = f.state.reader!;
      if (operation === "publish") assert.throws(() => read.publish(path.join(f.context.root, "TEST-forbidden-publication.json"), {}));
      if (operation === "batch") assert.throws(() => read.holdCodeBatch([f.first]));
      if (operation === "cancellation") assert.throws(() => holdSourceColorStagingCancellationMetadata(f.context, read.check));
      if (operation === "read") assert.throws(() => read.read(f.first, "a".repeat(64), 1024));
      if (operation === "directory") assert.throws(() => read.holdDirectory(path.dirname(f.first)));
      if (operation === "code") assert.throws(() => read.holdCode(f.first));
    });
    assert.throws(f.stage, /batch/); assertBatchUnpublished(f);
    assert.throws(() => f.state.reader!.holdCodeBatch([f.first]), /batch/);
  });
}

for (const boundary of ["middle", "end"] as const) test(`actual cancellation entry at ${boundary} stops the live batch`, t => {
  const f = stagingBatchFixture(t, true);
  f.at(boundary, () => enterSourceColorPrelaunchCancel(f.owner!));
  assert.throws(f.stage, /no longer permits staging/); assertBatchUnpublished(f);
  assert.equal(readSourceColorPrelaunchMetadata(f.owner!).phase, "cancel-entered");
  assert.throws(() => holdSourceColorStagingCancellationMetadata(f.context, f.state.reader!.check), /batch/);
});

test("all pin/parent captures precede first callback and final metadata checks retain completed pins", t => {
  const f = stagingBatchFixture(t, false), stat = fs.lstatSync, pins = new Set(GUIDED_SOURCE_COLOR_TS_FILES.map(p => path.join(f.context.root, p)));
  const captured = new Set<string>(), parents = new Set<string>();
  for (const file of pins) {
    let directory = path.dirname(file);
    while (!parents.has(directory)) { parents.add(directory); directory = path.dirname(directory); }
  }
  t.mock.method(fs, "lstatSync", (file: fs.PathLike, options?: never) => {
    if (f.state.inside && typeof file === "string") captured.add(file);
    return stat(file, options);
  });
  f.at("early", () => { for (const file of [...pins, ...parents]) assert(captured.has(file), `Uncaptured original ${file}`); });
  const result = f.stage(); assert(f.state.fired);
  replaceBatchPin(f, "first"); assert.throws(result.assertCurrent, /metadata changed/);
});

test("batch API rejects empty, duplicate and oversized inventories before guard callbacks", t => {
  const f = stagingBatchFixture(t, false), read = new SourceColorStagingRead(f.context); let calls = 0;
  f.context.onGuard(() => { calls++; });
  for (const names of [[], [f.first, f.first], Array(4001).fill(f.first)]) assert.throws(() => read.holdCodeBatch(names), /bounded/);
  assert.equal(calls, 0);
});

for (const hooks of [false, true]) test(`${hooks ? "live hooks" : "no hooks"}: actual prepublication batch pin metadata is linear`, t => {
  const f = stagingBatchFixture(t, hooks), stat = fs.lstatSync;
  const pins = new Set(GUIDED_SOURCE_COLOR_TS_FILES.map(p => path.join(f.context.root, p))); let calls = 0;
  t.mock.method(fs, "lstatSync", (file: fs.PathLike, options?: never) => {
    if (f.state.inside && typeof file === "string" && pins.has(file)) calls++;
    return stat(file, options);
  });
  f.at("early", () => undefined); f.stage();
  assert.equal(calls, (hooks ? 12 : 8) * pins.size);
  assert.equal(f.state.calls, 8 * pins.size + 2);
  t.diagnostic(`TEST ${pins.size} prospective pins: ${calls} actual pin stats; ${f.state.calls} original work callback calls; no native work`);
});
