/** Actual TEMP source2 approval → admission → writer protocol, never native input/media qualification. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { assertBodyClaimSourceColorMetadata } from "../guided-body-lineage";
import { assertBodyInputReferences, observeGuidedBodyMediaInput, writeGuidedBodyMediaInput } from "../guided-body-input";
import { BODY_MEDIA_REFERENCES } from "@/lib/producer/contracts/guided-body-media-v1";
import { replaceBodyWriterPublication } from "./_guided-body-media-input-admission-fixture";
import { bodyControllerSourcesFixture as bodyMediaInputAdmissionFixture } from "./_guided-body-controller-sources-fixture";

test("actual source2 body admission writes and reopens the exact original replay and seven references", async t => {
  const f = await bodyMediaInputAdmissionFixture(t);
  await f.run(async ({ admission, write }) => {
    assertBodyClaimSourceColorMetadata(admission); const result = write();
    assert.equal(result.input.schemaVersion, 2); assert.deepEqual(Object.keys(result.input.references), [...BODY_MEDIA_REFERENCES]);
    if (result.input.schemaVersion !== 2) throw new Error("TEST missing source2");
    assert.deepEqual(result.input.sourceColorReplay, admission.input.input.sourceColorReplay);
    assert.deepEqual(observeGuidedBodyMediaInput(result.record.path, result.record.sha256).input, result.input);
    assertBodyInputReferences(admission, result.input); assertBodyClaimSourceColorMetadata(admission);
    assert.equal(result.input.sourceColorReplay.executable, false); assert.equal(result.input.sourceColorReplay.bodyApproved, false);
  });
});
test("actual known source2 admission rejects copies and a tag downgrade before writer callbacks", async t => {
  const f = await bodyMediaInputAdmissionFixture(t);
  await f.run(async ({ admission }) => {
    let calls = 0; const guard = () => { calls++; }, file = path.join(admission.execution, "body-media-input.json");
    assert.throws(() => writeGuidedBodyMediaInput({ ...admission }, guard), /actual original/);
    admission.input.row.schemaVersion = 1; admission.input.input.schemaVersion = 1;
    assert.throws(() => writeGuidedBodyMediaInput(admission, guard), /changed/);
    assert.equal(calls, 0); assert.equal(fs.existsSync(file), false);
  });
});
test("actual source2 writer rejects original replay mutation at its first caller callback", async t => {
  const f = await bodyMediaInputAdmissionFixture(t);
  await f.run(async ({ admission, write }) => {
    assert.throws(() => write(() => { admission.input.input.sourceColorReplay = {}; }), /changed/);
    assert.equal(fs.existsSync(path.join(admission.execution, "body-media-input.json")), false);
  });
});
test("copied source2 admission with both tags downgraded cannot publish legacy input", async t => {
  const f = await bodyMediaInputAdmissionFixture(t);
  await f.run(async ({ admission, context }) => {
    const copied = { ...admission, input: { ...admission.input, row: { ...admission.input.row, schemaVersion: 1 },
      input: { ...admission.input.input, schemaVersion: 1 } } };
    let calls = 0;
    assert.throws(() => writeGuidedBodyMediaInput(copied, () => { calls++; context.budget.remainingMs(); }), /stored held-input/);
    assert.equal(calls, 0);
    assert.equal(fs.existsSync(path.join(admission.execution, "body-media-input.json")), false);
  });
});
test("actual source2 writer rejects last callback same-byte publication replacement and keeps evidence", async t => {
  const f = await bodyMediaInputAdmissionFixture(t);
  await f.run(async ({ admission, context, write }) => {
    let calls = 0;
    assert.throws(() => write(() => {
      context.budget.remainingMs(); calls++;
      if (calls === 4) replaceBodyWriterPublication(f, admission.execution);
    }), /original publication changed/);
    assert.equal(calls, 4); assert(fs.existsSync(path.join(admission.execution, "body-media-input.json")));
  });
});
