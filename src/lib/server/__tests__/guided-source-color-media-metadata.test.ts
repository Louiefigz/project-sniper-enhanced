/** Callback-free metadata authentication; explicit TEST staging only, no native execution or approval authority. */
import assert from "node:assert/strict";
import test from "node:test";
import { assertStagedSourceColorMetadata } from "../guided-source-color-staging";
import { SourceColorStagingRead, assertSourceColorStagingMetadata } from "../guided-source-color-staging-hold";
import { holdOpeningSourceColorProcess, assertOpeningSourceColorProcessMetadata } from "../guided-source-color-process-binding";
import { sourceColorMediaFixture, replaceMediaFixtureFile } from "./_guided-source-color-media-process-fixture";

test("actual staging and process metadata sweeps invoke zero work/resource callbacks after original work expiry", t => {
  const f = sourceColorMediaFixture(t), binding = holdOpeningSourceColorProcess(f.input.sourceColor);
  const counts = { ...f.calls }; f.clock.expired = true;
  assertStagedSourceColorMetadata(f.staging, f.staged); assertOpeningSourceColorProcessMetadata(binding);
  assert.deepEqual(f.calls, counts); assert.throws(() => binding.assertCurrent(), /expired/);
});

test("metadata authentication refuses spread clones, substitute context, and constructor-only readers", t => {
  const f = sourceColorMediaFixture(t), binding = holdOpeningSourceColorProcess(f.input.sourceColor);
  assert.throws(() => assertOpeningSourceColorProcessMetadata({ ...binding }), /actual original/);
  assert.throws(() => assertStagedSourceColorMetadata(f.staging, { ...f.staged }), /actual completed/);
  assert.throws(() => assertStagedSourceColorMetadata({ ...f.staging }, f.staged), /actual completed/);
  const reader = new SourceColorStagingRead(f.staging);
  assertSourceColorStagingMetadata(f.staging, reader.check);
  assert.throws(() => assertStagedSourceColorMetadata(f.staging, { ...f.staged, assertCurrent: reader.check }), /actual completed/);
});

test("captured original staging reader methods cannot be replaced beneath callback-free checks", t => {
  const f = sourceColorMediaFixture(t), reader = new SourceColorStagingRead(f.staging), current = reader.check;
  reader.check = () => {}; assert.throws(() => assertSourceColorStagingMetadata(f.staging, current), /methods changed/);
});

test("private process metadata keeps exact full original clauses and original callback identities", t => {
  const f = sourceColorMediaFixture(t), binding = holdOpeningSourceColorProcess(f.input.sourceColor);
  f.input.sourceColor.submission = { ...f.input.sourceColor.submission };
  assert.throws(() => assertOpeningSourceColorProcessMetadata(binding), /original staging|complete request/);
});

for (const file of ["claim", "input", "sidecar", "reservation"] as const) test(`metadata-only hold rejects same-byte replacement of original ${file}`, t => {
  const f = sourceColorMediaFixture(t), binding = holdOpeningSourceColorProcess(f.input.sourceColor);
  replaceMediaFixtureFile(f, file);
  assert.throws(() => assertOpeningSourceColorProcessMetadata(binding), /changed/);
});

test("original staging work callback substitution remains detectable without invoking the replacement", t => {
  const f = sourceColorMediaFixture(t), binding = holdOpeningSourceColorProcess(f.input.sourceColor); let called = 0;
  f.staging.guard = () => { called++; };
  assert.throws(() => assertOpeningSourceColorProcessMetadata(binding), /original staging|complete request/);
  assert.equal(called, 0);
});

test("constructor-only staged substitute cannot reach native execution through the internal writer", async t => {
  const f = sourceColorMediaFixture(t), reader = new SourceColorStagingRead(f.staging);
  f.input.sourceColor.staged = { ...f.staged, assertCurrent: reader.check };
  await assert.rejects(f.run(), /actual completed staging/); assert.equal(f.calls.invoke, 0);
});
