/** Pure two-CAS metadata only; no files, clocks, resources, process or cleanup authority is created. */
import assert from "node:assert/strict";
import test from "node:test";
import { parsePreparedSourceColorCleanupFact, parseFinalSourceColorCleanupFact, parseSourceColorRetirementAck,
  type PreparedSourceColorCleanupFact, type FinalSourceColorCleanupFact, type SourceColorRetirementAck } from "../contracts/guided-source-color-cleanup-facts";

const HASH = "a".repeat(64), OTHER_HASH = "b".repeat(64);
const EXECUTION = "00000000-0000-4000-8000-000000000001", ATTEMPT = "00000000-0000-4000-8000-000000000002";
const DIRECTORY = `/TEST/producer/guided-v2-operations/00000000-0000-4000-8000-000000000003/executions/${EXECUTION}/cleanup-attempts/${ATTEMPT}`;

/** Syntactically valid TEST values, not authenticated records or an observed filesystem. */
function facts() {
  const identity = { claimHash: HASH, executionId: EXECUTION, cleanupAttemptId: ATTEMPT,
    mediaSelected: false as const, openingApproved: false as const, deliveryApproved: false as const };
  const clock = { ...identity, clockHash: HASH, generationStartedAt: "2026-09-08T00:00:00.000Z", createdAt: "2026-09-08T00:00:10.000Z" };
  const raw = { reservation: { path: "/TEST/.sniper-color-resource/active.json", sha256: HASH, sizeBytes: 257 },
    archive: { path: `${DIRECTORY}/reservation.json`, sha256: HASH, sizeBytes: 257 } };
  const prepared: PreparedSourceColorCleanupFact = { ...clock, ...raw, schemaVersion: 2,
    kind: "guided-opening-source-color-cleanup-prepared", scope: "exact-owned-resource-cleanup-awaiting-reservation-retirement-not-approval",
    phase: "awaiting-retirement", claimRetained: true, beforeJournalHash: HASH, processOutcomeSha256: HASH,
    cleanupStartSha256: HASH, cleanupOutputSha256: HASH, cleanupResultHash: HASH, cleanupInvocationSha256: HASH, sourceColorHash: HASH };
  const final: FinalSourceColorCleanupFact = { ...clock, schemaVersion: 2, kind: "guided-opening-source-color-cleanup-commit",
    scope: "exact-owned-resource-cleanup-and-reservation-retirement-not-approval", phase: "retired", claimRetained: false,
    preparedFactHash: HASH, pendingJournalHash: OTHER_HASH,
    retirementAck: { path: `${DIRECTORY}/retirement-ack.json`, sha256: OTHER_HASH, sizeBytes: 100 } };
  const ack: SourceColorRetirementAck = { ...identity, ...raw, schemaVersion: 1, kind: "guided-opening-source-color-retirement",
    scope: "exact-reservation-retirement-not-process-cleanup-or-approval", preparedFactHash: HASH, pendingJournalHash: OTHER_HASH,
    observedAt: "2026-09-08T00:00:09.000Z", disposition: "unlinked-original" };
  return { prepared, final, ack };
}
function contracts() {
  const f = facts();
  return [{ value: f.prepared, parse: parsePreparedSourceColorCleanupFact }, { value: f.final, parse: parseFinalSourceColorCleanupFact },
    { value: f.ack, parse: parseSourceColorRetirementAck }];
}
/** Generate scalar substitutions without nesting the assertions three levels deep. */
function patches(keys: string[], values: unknown[]): Record<string, unknown>[] {
  return keys.flatMap(key => values.map(value => ({ [key]: value })));
}

test("all three exact phases parse as detached metadata while retaining every explicit flag", () => {
  for (const { value, parse } of contracts()) {
    const before = structuredClone(value), parsed = parse(value);
    assert.deepEqual(parsed, before); assert.notEqual(parsed, value); assert.deepEqual(value, before);
    parsed.claimHash = OTHER_HASH; assert.equal(value.claimHash, HASH);
  }
  const f = facts(); assert.equal(parsePreparedSourceColorCleanupFact(f.prepared).claimRetained, true);
  assert.equal(parseFinalSourceColorCleanupFact(f.final).claimRetained, false);
});

test("every required field and every unknown top-level field is closed", () => {
  for (const { value, parse } of contracts()) {
    for (const key of Object.keys(value)) {
      const changed: Record<string, unknown> = { ...value }; delete changed[key]; assert.throws(() => parse(changed), key);
    }
    assert.throws(() => parse({ ...value, extra: false })); assert.throws(() => parse({ ...value, qcPassed: true }));
  }
});

test("versions are strict and neither phase can masquerade as the other", () => {
  for (const { value, parse } of contracts()) {
    for (const schemaVersion of [true, false, 0, "1", "2", 3, null]) assert.throws(() => parse({ ...value, schemaVersion }));
    assert.throws(() => parse({ ...value, kind: "guided-opening-cleanup-commit" }));
    assert.throws(() => parse({ ...value, scope: "approved" }));
  }
  const f = facts(); assert.throws(() => parsePreparedSourceColorCleanupFact(f.final));
  assert.throws(() => parseFinalSourceColorCleanupFact(f.prepared)); assert.throws(() => parseSourceColorRetirementAck(f.prepared));
});

test("pending cleanup cannot clear a claim and final cleanup cannot retain one", () => {
  const f = facts();
  for (const claimRetained of [false, 1, "true", null]) assert.throws(() => parsePreparedSourceColorCleanupFact({ ...f.prepared, claimRetained }));
  for (const claimRetained of [true, 0, "false", null]) assert.throws(() => parseFinalSourceColorCleanupFact({ ...f.final, claimRetained }));
  assert.throws(() => parsePreparedSourceColorCleanupFact({ ...f.prepared, phase: "retired" }));
  assert.throws(() => parseFinalSourceColorCleanupFact({ ...f.final, phase: "awaiting-retirement" }));
});

test("all selection and approval flags require literal false", () => {
  for (const { value, parse } of contracts()) {
    for (const patch of patches(["mediaSelected", "openingApproved", "deliveryApproved"], [true, 0, "false", null])) {
      assert.throws(() => parse({ ...value, ...patch }));
    }
  }
});

test("every journal, claim, clock, output and invocation hash is a strict lowercase SHA", () => {
  for (const { value, parse } of contracts()) {
    const keys = Object.keys(value).filter(key => key.endsWith("Hash") || key.endsWith("Sha256"));
    for (const patch of patches(keys, [null, 0, true, "A".repeat(64), "a".repeat(63)])) assert.throws(() => parse({ ...value, ...patch }));
  }
});

test("execution and cleanup attempt IDs require exact UUIDv4 strings", () => {
  const invalid = [true, "../escape", "00000000-0000-1000-8000-000000000001", "00000000-0000-4000-c000-000000000001"];
  for (const { value, parse } of contracts()) {
    for (const patch of patches(["executionId", "cleanupAttemptId"], invalid)) assert.throws(() => parse({ ...value, ...patch }));
  }
});

test("timestamps require canonical UTC milliseconds and clock facts cannot predate generation", () => {
  const invalid = [null, true, "2026-09-08T00:00:00Z", "2026-09-08T00:00:00.000+00:00", "2026-02-30T00:00:00.000Z"];
  for (const { value, parse } of contracts()) {
    const fields = Object.keys(value).filter(key => key.endsWith("At"));
    for (const patch of patches(fields, invalid)) assert.throws(() => parse({ ...value, ...patch }));
  }
  const f = facts();
  assert.throws(() => parsePreparedSourceColorCleanupFact({ ...f.prepared, createdAt: "2026-09-07T23:59:59.999Z" }));
  assert.throws(() => parseFinalSourceColorCleanupFact({ ...f.final, createdAt: "2026-09-07T23:59:59.999Z" }));
});

test("archive and original active reference must preserve identical raw SHA and size", () => {
  const f = facts();
  for (const [value, parse] of [[f.prepared, parsePreparedSourceColorCleanupFact], [f.ack, parseSourceColorRetirementAck]] as const) {
    assert.throws(() => parse({ ...value, archive: { ...value.archive, sha256: OTHER_HASH } }));
    assert.throws(() => parse({ ...value, archive: { ...value.archive, sizeBytes: 258 } }));
    assert.throws(() => parse({ ...value, reservation: { ...value.reservation, path: "/TEST/active.json" } }));
  }
});

test("raw reference shapes reject missing, extra, unsafe path and non-SHA fields", () => {
  const f = facts();
  for (const [value, parse, field, original] of [[f.prepared, parsePreparedSourceColorCleanupFact, "archive", f.prepared.archive],
    [f.ack, parseSourceColorRetirementAck, "reservation", f.ack.reservation],
    [f.final, parseFinalSourceColorCleanupFact, "retirementAck", f.final.retirementAck]] as const) {
    for (const ref of [null, [], {}, { ...original, extra: 0 }, { ...original, sha256: false },
      { ...original, path: "/TEST/../escape" }, { ...original, path: "relative.json" }]) {
      assert.throws(() => parse({ ...value, [field]: ref }));
    }
  }
});

test("reservation and archive sizes allow the exact 8 MiB boundary only", () => {
  const f = facts();
  for (const [value, parse] of [[f.prepared, parsePreparedSourceColorCleanupFact], [f.ack, parseSourceColorRetirementAck]] as const) {
    const at = (sizeBytes: unknown) => ({ ...value, archive: { ...value.archive, sizeBytes }, reservation: { ...value.reservation, sizeBytes } });
    assert.doesNotThrow(() => parse(at(8 * 1024 * 1024))); assert.doesNotThrow(() => parse(at(1)));
    for (const size of [0, -1, true, "257", 1.5, Infinity, NaN, 8 * 1024 * 1024 + 1]) assert.throws(() => parse(at(size)));
  }
});

test("acknowledgement raw reference has its separate exact 128 KiB ceiling", () => {
  const f = facts(), at = (sizeBytes: unknown) => ({ ...f.final, retirementAck: { ...f.final.retirementAck, sizeBytes } });
  assert.doesNotThrow(() => parseFinalSourceColorCleanupFact(at(128 * 1024)));
  for (const size of [0, true, "100", 128 * 1024 + 1, 8 * 1024 * 1024]) assert.throws(() => parseFinalSourceColorCleanupFact(at(size)));
});

test("archive and acknowledgement paths bind the exact declared execution, attempt and filename", () => {
  const f = facts();
  for (const [value, parse, field, original] of [[f.prepared, parsePreparedSourceColorCleanupFact, "archive", f.prepared.archive],
    [f.final, parseFinalSourceColorCleanupFact, "retirementAck", f.final.retirementAck]] as const) {
    for (const path of [original.path.replace(EXECUTION, ATTEMPT), original.path.replace(`/cleanup-attempts/${ATTEMPT}`, `/cleanup-attempts/${EXECUTION}`),
      original.path.replace(/[^/]+$/u, "other.json")]) assert.throws(() => parse({ ...value, [field]: { ...original, path } }));
  }
});

test("retirement acknowledgement retains honest disposition without inferring earlier unlink", () => {
  const f = facts();
  const disposition = "already-absent-after-committed-intent";
  assert.equal(parseSourceColorRetirementAck({ ...f.ack, disposition }).disposition, disposition);
  for (const value of [true, ["unlinked-original"], "absent", "unlinked", null]) {
    assert.throws(() => parseSourceColorRetirementAck({ ...f.ack, disposition: value }));
  }
});

test("pure parser accepts structural metadata without claiming a real namespace or cross-fact joins", () => {
  const f = facts();
  const value = { ...f.prepared, archive: { ...f.prepared.archive, path: f.prepared.archive.path.replace("/TEST", "/OTHER-TEST") } };
  assert.doesNotThrow(() => parsePreparedSourceColorCleanupFact(value));
  // Actual reader must compare this parent hash to its independently authenticated prepared fact.
  assert.equal(parseFinalSourceColorCleanupFact({ ...f.final, preparedFactHash: "c".repeat(64) }).preparedFactHash, "c".repeat(64));
});
