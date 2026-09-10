/** Pure metadata syntax only: none of these TEST hashes are source or execution evidence. */
import assert from "node:assert/strict";
import test from "node:test";
import { BODY_SOURCE_COLOR_REPLAY_SCOPE, parseBodySourceColorReplayReferences as parse } from "../contracts/guided-body-source-color-replay-v2";

const HASH = "a".repeat(64), EXECUTION = "00000000-0000-4000-8000-000000000001";
const ATTEMPT = "00000000-0000-4000-8000-000000000002", ROOT = `/TEST/producer/executions/${EXECUTION}`;
function value() {
  return { schemaVersion: 2, kind: "guided-body-source-color-replay-references", scope: BODY_SOURCE_COLOR_REPLAY_SCOPE,
    opening: { selectionHash: HASH, claimHash: HASH, cleanupHash: HASH, executionId: EXECUTION,
      inputSha256: HASH, executionInputHash: HASH, mediaResultSha256: HASH, receiptHash: HASH }, sourceColorHash: HASH,
    input: { path: `${ROOT}/source-color/input.json`, sha256: HASH, sizeBytes: 1 },
    reservationArchive: { path: `${ROOT}/cleanup-attempts/${ATTEMPT}/reservation.json`, sha256: HASH, sizeBytes: 8 * 1024 * 1024 },
    executable: false, bodyApproved: false, deliveryApproved: false };
}
function omissions(row: object): object[] {
  return Object.keys(row).map(key => { const next: Record<string, unknown> = { ...row }; delete next[key]; return next; });
}

test("body source replay parser returns detached closed non-authorizing references", () => {
  const original = value(), parsed = parse(original); assert.deepEqual(parsed, original); assert.notEqual(parsed.input, original.input);
  parsed.input.sha256 = "b".repeat(64); assert.equal(original.input.sha256, HASH);
  assert.equal(parsed.executable, false); assert.equal(parsed.bodyApproved, false); assert.equal(parsed.deliveryApproved, false);
});
test("body source replay rejects all missing or extra top-level and nested fields", () => {
  const original = value(); for (const row of [...omissions(original), { ...original, extra: false }]) assert.throws(() => parse(row));
  for (const key of ["opening", "input", "reservationArchive"] as const) {
    for (const row of [...omissions(original[key]), { ...original[key], extra: false }]) assert.throws(() => parse({ ...original, [key]: row }));
  }
});
test("body source replay refuses legacy, partial, mixed-role and approval spellings", () => {
  for (const schemaVersion of [1, 3, "2", true, null]) assert.throws(() => parse({ ...value(), schemaVersion }));
  for (const key of ["kind", "scope", "input", "reservationArchive", "executable", "bodyApproved", "deliveryApproved"]) {
    for (const replacement of [true, 0, "false", null]) assert.throws(() => parse({ ...value(), [key]: replacement }));
  }
});
test("body source replay rejects malformed hashes and noninteger or excessive raw sizes", () => {
  for (const sha256 of [true, null, "A".repeat(64), "a".repeat(63)]) {
    assert.throws(() => parse({ ...value(), input: { ...value().input, sha256 } }));
    assert.throws(() => parse({ ...value(), sourceColorHash: sha256 }));
  }
  for (const key of Object.keys(value().opening).filter(key => key !== "executionId")) {
    assert.throws(() => parse({ ...value(), opening: { ...value().opening, [key]: true } }));
  }
  for (const sizeBytes of [0, -1, 1.5, true, "1", NaN, Infinity, 8 * 1024 * 1024 + 1]) {
    for (const key of ["input", "reservationArchive"] as const) assert.throws(() => parse({ ...value(), [key]: { ...value()[key], sizeBytes } }));
  }
});
test("body source replay requires canonical same-execution paths and exact UUID4 archive role", () => {
  const original = value();
  const paths = ["relative/input.json", original.input.path.replace("/source-color/", "/source-color/../source-color/"),
    original.input.path.replace("/source-color/", "//source-color/"), original.reservationArchive.path];
  for (const path of paths) assert.throws(() => parse({ ...original, input: { ...original.input, path } }));
  for (const path of [original.reservationArchive.path.replace("/TEST/", "/OTHER/"), `${ROOT}/active.json`,
    original.reservationArchive.path.replace(ATTEMPT, EXECUTION.replace("-4000-", "-1000-")),
    original.reservationArchive.path.replace("reservation.json", "retirement-ack.json")]) {
    assert.throws(() => parse({ ...original, reservationArchive: { ...original.reservationArchive, path } }));
  }
  assert.throws(() => parse({ ...original, opening: { ...original.opening, executionId: ATTEMPT } }));
});
