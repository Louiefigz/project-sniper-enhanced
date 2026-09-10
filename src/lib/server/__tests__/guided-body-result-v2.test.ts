/** No native body run or read: real source admission/phase bytes, explicit native/AV provenance leaf. */
import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import { bodyResultReads, assertBodyReadbackIdentity, assertHeldBodyResultMetadata } from "../guided-body-result";
import { bodyResultV2Fixture, replaceBodyResultFile } from "./_guided-body-result-v2-fixture";

test("actual source2 admission/activation/result binds raw completion and exact original replay readback", async t => {
  const f = await bodyResultV2Fixture(t);
  await f.run(async f => {
    const selected = f.read(); assert.equal(selected.completion.schemaVersion, 2);
    assert.equal(selected.sourceBytesObserved, false); assert.equal(selected.mediaBytesObserved, false);
    assert(Buffer.isBuffer(selected.record.bytes)); assertHeldBodyResultMetadata(selected);
    const readback = assertBodyReadbackIdentity(JSON.stringify(f.readback), selected);
    assert.deepEqual(readback, f.readback); assert.equal(readback.bodyApproved, false);
    assert.throws(() => assertHeldBodyResultMetadata({ ...selected }), /private metadata/);
    const legacy = { ...f.readback, schemaVersion: 1 }; delete (legacy as Record<string, unknown>).sourceColorReplay;
    delete (legacy as Record<string, unknown>).sourceColorReadback;
    assert.throws(() => assertBodyReadbackIdentity(JSON.stringify(legacy), selected));
    const changed = structuredClone(f.readback); changed.sourceColorReadback.observationRecordHash = "b".repeat(64);
    assert.throws(() => assertBodyReadbackIdentity(JSON.stringify(changed), selected), /replay evidence/);
    assertHeldBodyResultMetadata(selected);
  });
});
test("source2 result refuses a copied or downgraded admission before the stopped callback", async t => {
  const fixture = await bodyResultV2Fixture(t);
  await fixture.run(async f => {
    const original = f.phase.held.admission;
    const mock = t.mock.method(bodyResultReads, "stopped", () => { throw new Error("TEST stopped must not run"); });
    f.phase.held.admission = { ...original };
    assert.throws(f.read, /actual original/);
    f.phase.held.admission = original;
    original.input.row.schemaVersion = 1; original.input.input.schemaVersion = 1;
    assert.throws(f.read, /changed/); assert.equal(mock.mock.callCount(), 0);
  });
});
test("source2 result rejects the first stopped callback replacing its already captured result inode", async t => {
  const fixture = await bodyResultV2Fixture(t);
  await fixture.run(async f => {
    t.mock.method(bodyResultReads, "stopped", () => { replaceBodyResultFile(f); return f.stopped; });
    assert.throws(f.read, /original metadata/); assert(fs.existsSync(f.result.path));
  });
});
test("source2 retained result refuses late raw Buffer, nested projection and inode substitutions", async t => {
  const fixture = await bodyResultV2Fixture(t);
  await fixture.run(async f => {
    const selected = f.read(), byte = selected.record.bytes[0];
    selected.record.bytes[0] ^= 1; assert.throws(() => assertHeldBodyResultMetadata(selected), /changed/); selected.record.bytes[0] = byte;
    assertHeldBodyResultMetadata(selected);
    if (selected.completion.schemaVersion !== 2) throw new Error("TEST source2 required");
    const prior = selected.completion.sourceColorReadback.gradeApplied;
    (selected.completion.sourceColorReadback as unknown as Record<string, unknown>).gradeApplied = true;
    assert.throws(() => assertHeldBodyResultMetadata(selected), /changed/); selected.completion.sourceColorReadback.gradeApplied = prior;
    assertHeldBodyResultMetadata(selected); replaceBodyResultFile(f);
    assert.throws(() => assertHeldBodyResultMetadata(selected), /changed/);
  });
});
