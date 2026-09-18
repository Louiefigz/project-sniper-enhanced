/** Closed data matrix plus genuine TEST metadata capabilities; no body/native/human qualification. */
import assert from "node:assert/strict";
import test from "node:test";
import { randomUUID } from "node:crypto";
import { GUIDED_BODY_INPUT_SCOPE } from "@/lib/producer/contracts/guided-body-v1";
import { BODY_SOURCE_COLOR_REPLAY_SCOPE } from "@/lib/producer/contracts/guided-body-source-color-replay-v2";
import { bodyHeldDocument, parseBodyHeldDocument } from "../guided-body-store";
import { assertBodyHeldSourceColorMetadata } from "../guided-body-authority";
import { sourceColorBodyAuthorityFixture } from "./_guided-source-color-body-authority-fixture";

const HASH = "a".repeat(64), ROOT = "/TEST/producer/executions/00000000-0000-4000-8000-000000000001";
/** Data-only values deliberately carry no actual held authority or file proof. */
function document(version: 1 | 2) {
  const replay = { schemaVersion: 2, kind: "guided-body-source-color-replay-references", scope: BODY_SOURCE_COLOR_REPLAY_SCOPE,
    opening: { selectionHash: HASH, claimHash: HASH, cleanupHash: HASH, executionId: ROOT.split("/").at(-1),
      inputSha256: HASH, executionInputHash: HASH, mediaResultSha256: HASH, receiptHash: HASH }, sourceColorHash: HASH,
    input: { path: `${ROOT}/source-color/input.json`, sha256: HASH, sizeBytes: 1 },
    reservationArchive: { path: `${ROOT}/cleanup-attempts/00000000-0000-4000-8000-000000000002/reservation.json`, sha256: HASH, sizeBytes: 1 },
    executable: false, bodyApproved: false, deliveryApproved: false };
  return { schemaVersion: version, kind: "guided-body-held-input", input: {
    schemaVersion: version, scope: GUIDED_BODY_INPUT_SCOPE, submission: { schemaVersion: 1, operation: "continue-approved-opening",
      idempotencyKey: randomUUID(), expectedToken: "TEST-only", expectedJournalHash: HASH, openingApprovalHash: HASH,
      selectionHash: HASH, proposalReadinessHash: HASH, treatmentDraftRevisionHash: HASH },
    journalHash: HASH, approvalHash: HASH, selectionHash: HASH, readinessHash: HASH, draftRevisionHash: HASH,
    authority: {}, bindings: {}, references: {}, verification: {}, origin: { clockHash: HASH, startedAt: "2026-09-08T00:00:00.000Z" },
    executable: false, bodyReadiness: "not-qualified", bodyGenerated: false, deliveryApproved: false,
    ...(version === 2 ? { sourceColorReplay: replay } : {}) },
  opening: { claimPath: `${ROOT}/execution-claim.json`, claimSha256: HASH, inputPath: `${ROOT}/media-input/input.json`,
    inputSha256: HASH, executionInputHash: HASH, outputRoot: `${ROOT}/media-output`,
    resultPath: `${ROOT}/media-output/media-result.json`, resultSha256: HASH } };
}

test("held body document accepts separate closed V1 and V2 data without granting held capability", () => {
  for (const version of [1, 2] as const) {
    const row = document(version), parsed = parseBodyHeldDocument(row);
    assert.equal(parsed.row.schemaVersion, version); assert.equal(parsed.input.schemaVersion, version);
    assert.equal(Object.hasOwn(parsed.input, "sourceColorReplay"), version === 2);
    assert.equal(parsed.input.executable, false); assert.equal(parsed.input.bodyGenerated, false);
  }
});

test("held body versions never coerce or accept an outer/input mismatch", () => {
  for (const version of [1, 2] as const) {
    const row = document(version);
    for (const bad of [true, false, "1", "2", null, 0, 3, 1.5]) {
      assert.throws(() => parseBodyHeldDocument({ ...row, schemaVersion: bad }));
      assert.throws(() => parseBodyHeldDocument({ ...row, input: { ...row.input, schemaVersion: bad } }));
    }
    assert.throws(() => parseBodyHeldDocument({ ...row, input: { ...row.input, schemaVersion: version === 1 ? 2 : 1 } }));
  }
});

test("V1 cannot smuggle replay and V2 cannot omit it or add unrecognized authority", () => {
  const one = document(1), two = document(2), { sourceColorReplay, ...missing } = two.input;
  assert.throws(() => parseBodyHeldDocument({ ...one, input: { ...one.input, sourceColorReplay } }));
  assert.throws(() => parseBodyHeldDocument({ ...two, input: missing }));
  for (const row of [{ ...two, extra: false }, { ...two, input: { ...two.input, extra: false } },
    { ...two, opening: { ...two.opening, extra: false } }, { ...two, input: { ...two.input, executable: true } }]) {
    assert.throws(() => parseBodyHeldDocument(row));
  }
});

test("both held document versions require every closed outer input and original-opening field", () => {
  for (const version of [1, 2] as const) {
    const row = document(version);
    const targets = [{ value: row, wrap: (value: object) => value },
      { value: row.input, wrap: (input: object) => ({ ...row, input }) },
      { value: row.opening, wrap: (opening: object) => ({ ...row, opening }) }];
    targets.forEach(target => Object.keys(target.value).forEach(key => {
      const value: Record<string, unknown> = { ...target.value }; delete value[key];
      assert.throws(() => parseBodyHeldDocument(target.wrap(value)), `${version}:${key}`);
    }));
  }
});

test("V2 replay cannot name foreign original selection input execution or media-result hashes", () => {
  const row = document(2), replay = row.input.sourceColorReplay!;
  for (const key of ["selectionHash", "inputSha256", "executionInputHash", "mediaResultSha256"]) {
    const sourceColorReplay = { ...replay, opening: { ...replay.opening, [key]: "b".repeat(64) } };
    assert.throws(() => parseBodyHeldDocument({ ...row, input: { ...row.input, sourceColorReplay } }), /differs/);
  }
});

test("actual source2 body authority writes only its genuine same-selection held document", async t => {
  const e = await sourceColorBodyAuthorityFixture(t), held = await e.hold();
  assert.equal(held.schemaVersion, 2); assert.equal(held.executable, false); assert.equal(held.deliveryApproved, false);
  assertBodyHeldSourceColorMetadata(held); held.assertUnchanged();
  const row = bodyHeldDocument(held, e.selected), parsed = parseBodyHeldDocument(row);
  assert.equal(parsed.row.schemaVersion, 2); assert.equal(parsed.input.sourceColorReplay, held.sourceColorReplay);
  assert.equal(held.sourceColorReplay!.opening.mediaResultSha256, e.f.media.completion.receiptSha256);
  assert.equal(held.sourceColorReplay!.opening.inputSha256, e.selected.held.claim.inputSha256);
  assert.deepEqual(held.references.candidatePlan, { path: e.metadata.picture.documents.candidatePlan.path,
    sha256: e.metadata.picture.documents.candidatePlan.sha256 });
  assert.deepEqual(e.metadata.candidate.cutTrack, e.f.staging.context.opening.documents.candidatePlan.value.cutTrack);
  assert.equal(e.f.calls.native, 2); e.f.assertProject();
  assert.throws(() => bodyHeldDocument({ ...held }, e.selected), /actual original held authority/);
  assert.throws(() => bodyHeldDocument(held, { ...e.selected }), /actual original/);
  assert.throws(() => bodyHeldDocument({ ...held, schemaVersion: 1 } as unknown as typeof held, e.selected), /versions differ/);
  assert.equal(e.f.calls.native, 2);
});
