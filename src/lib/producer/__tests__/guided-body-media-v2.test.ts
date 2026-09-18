/** Closed transport syntax only. No native work, original admission or approval is claimed. */
import assert from "node:assert/strict";
import test from "node:test";
import { BODY_MEDIA_REFERENCES, parseGuidedBodyMediaInput as legacy, parseCurrentBodyMediaInput as parse } from "../contracts/guided-body-media-v1";
import { MANUAL_SHORT_BODY_PROFILE } from "../contracts/guided-media-profile";
import { CAPTION_BODY_PROFILE, CAPTION_SHORT_BODY_PROFILE, SCREENED_CAPTION_BODY_PROFILE,
  SCREENED_CAPTION_SHORT_BODY_PROFILE } from "../contracts/guided-caption-profile";
import { PRESENTER_BODY_PROFILE, PRESENTER_SHORT_BODY_PROFILE, PRESENTER_CAPTION_BODY_PROFILE,
  PRESENTER_CAPTION_SHORT_BODY_PROFILE } from "../contracts/guided-presenter-profile";
import { bodyMediaTestV1, bodyMediaTestV2, bodyMediaOmissions, bodyMediaReferenceChanges } from "./_guided-body-media-v2-fixture";

test("body media current parser preserves exact legacy object and closed legacy parser", () => {
  const original = bodyMediaTestV1(); assert.equal(legacy(original), original); assert.equal(parse(original), original);
  assert.throws(() => legacy(bodyMediaTestV2()));
  assert.throws(() => legacy({ ...original, sourceColorReplay: bodyMediaTestV2().sourceColorReplay }));
});
test("body media V2 has detached replay and the same seven closed original references", () => {
  const original = bodyMediaTestV2(), value = parse(original); assert.deepEqual(value, original);
  assert.equal(value.schemaVersion, 2); if (value.schemaVersion !== 2) throw new Error("TEST expected V2");
  assert.deepEqual(Object.keys(value.references), [...BODY_MEDIA_REFERENCES]);
  value.references.openingInput.sha256 = "b".repeat(64); value.sourceColorReplay.input.sha256 = "c".repeat(64);
  value.runtime.dockerSocketInode = "3"; value.selectedGraphicOrders.push(2);
  assert.deepEqual(original, bodyMediaTestV2());
  assert.equal(value.sourceColorReplay.executable, false); assert.equal(value.sourceColorReplay.bodyApproved, false);
});
test("body media V2 keeps every supported current profile without widening historical profile admission", () => {
  for (const profile of [MANUAL_SHORT_BODY_PROFILE, CAPTION_BODY_PROFILE, CAPTION_SHORT_BODY_PROFILE,
    SCREENED_CAPTION_BODY_PROFILE, SCREENED_CAPTION_SHORT_BODY_PROFILE, PRESENTER_BODY_PROFILE,
    PRESENTER_SHORT_BODY_PROFILE, PRESENTER_CAPTION_BODY_PROFILE, PRESENTER_CAPTION_SHORT_BODY_PROFILE]) {
    assert.equal(parse({ ...bodyMediaTestV1(), profile }).profile, profile);
    assert.equal(parse({ ...bodyMediaTestV2(), profile }).profile, profile);
    assert.throws(() => legacy({ ...bodyMediaTestV1(), profile }));
  }
});
test("body media requires exact version and complete V2 fields without legacy replay leakage", () => {
  const value = bodyMediaTestV2();
  for (const row of [...bodyMediaOmissions(value), { ...value, unknown: false }]) assert.throws(() => parse(row));
  for (const schemaVersion of [0, 1, 3, true, "2", null, NaN]) assert.throws(() => parse({ ...value, schemaVersion }));
  for (const sourceColorReplay of [undefined, null, false, {}, { ...value.sourceColorReplay, schemaVersion: 1 }]) {
    assert.throws(() => parse({ ...value, sourceColorReplay }));
  }
});
test("body media original references remain exact seven two-field records in both versions", () => {
  for (const original of [bodyMediaTestV1(), bodyMediaTestV2()]) {
    for (const references of [...bodyMediaOmissions(original.references), { ...original.references, sourceColorReplay: {} }]) {
      assert.throws(() => parse({ ...original, references }));
    }
    bodyMediaReferenceChanges(original).forEach(row => assert.throws(() => parse(row)));
  }
});
test("body media V2 rejects malformed common values and runtime widening", () => {
  const original = bodyMediaTestV2();
  for (const patch of [{ kind: "other" }, { scope: "approved" }, { profile: "unknown" }, { requestId: false }, { executionId: "bad" },
    { selectedGraphicOrders: [false] }, { selectedGraphicOrders: [0, 0] }, { selectedGraphicOrders: [1] },
    { selectedGraphicOrders: Array.from({ length: 129 }, (_, index) => index) }, { runtime: { ...original.runtime, executable: true } }]) {
    assert.throws(() => parse({ ...original, ...patch }));
  }
});
test("body media V2 applies full nested replay parser including bounds, paths and false flags", () => {
  const original = bodyMediaTestV2(), replay = original.sourceColorReplay;
  for (const sourceColorReplay of [...bodyMediaOmissions(replay), { ...replay, executable: true }, { ...replay, bodyApproved: true },
    { ...replay, input: { ...replay.input, sizeBytes: 8 * 1024 * 1024 + 1 } },
    { ...replay, reservationArchive: { ...replay.reservationArchive, path: replay.input.path } },
    { ...replay, opening: { ...replay.opening, executionId: original.requestId } }]) {
    assert.throws(() => parse({ ...original, sourceColorReplay }));
  }
});
