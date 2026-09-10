import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { parseRawTreatmentRevisionSubmissionV1 } from "@/lib/producer/contracts/raw-treatment-revision-v1";
import { parseRawTreatmentSubmissionV1 } from "@/lib/producer/contracts/raw-treatment-v1";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { reviseRawTreatment, reconcileRawTreatmentRevision, treatmentRevisionReads } from "../guided-treatment-revision";
import { readTreatmentBriefHistory } from "../guided-treatment-revision-history";
import { readTreatmentCommandStatus, treatmentStatusReaders } from "../../../../scripts/producer/guided-treatment-status";
import { readRawTreatmentAdmission } from "../guided-raw-treatment-store";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { readGuidedObject, writeGuidedObject } from "../guided-cut-v2-store";
import { assertTreatmentRevisionIdle, treatmentRevisionReservation } from "../guided-treatment-revision-store";
import { treatmentRevisionFixture, revisionRequest } from "./_guided-treatment-revision-fixture";

test("revision transport is closed, exact and never accepts an intent/cut/approval patch", async (t) => {
  const f = await treatmentRevisionFixture(t), request = revisionRequest(f.dir, "  TEST α😀: keep exact whitespace.\n");
  assert.deepEqual(parseRawTreatmentRevisionSubmissionV1(request), request);
  assert.throws(() => parseRawTreatmentSubmissionV1(request));
  for (const patch of [{ supersession: undefined }, { supersession: "merge" }, { rawIntent: " " }, { rawIntent: "x".repeat(20001) },
    { intent: {} }, { target: {} }, { accepted: true }, { parentAdmissionHash: "../bad" }, { supersedesRequestHash: null }, { schemaVersion: "1" }]) {
    assert.throws(() => parseRawTreatmentRevisionSubmissionV1({ ...request, ...patch }));
  }
});

test("metadata-only revision preserves original bytes/context/clock and supports current and ancestor replay", async (t) => {
  const f = await treatmentRevisionFixture(t), before = readRawTreatmentAdmission(f.dir);
  const plan = readFileSync(f.ctx.planPath), manifest = readFileSync(f.ctx.manifestPath), ctx = canonicalJsonSha256(before.job.ctx);
  const clockFile = path.join(f.dir, "guided-v2-operations", `generation-${before.pointer.cutDecisionHash}.json`), clockBytes = readFileSync(clockFile);
  const first = revisionRequest(f.dir), one = await reviseRawTreatment({ dir: f.dir, submission: first });
  const current = readRawTreatmentAdmission(f.dir);
  assert.equal(current.submission.rawIntent, first.rawIntent); assert.equal(current.clock.submission.rawIntent, f.first.rawIntent);
  assert.equal(current.lineage.length, 2); assert.equal(current.job.token, before.job.token);
  assert.equal(canonicalJsonSha256(current.job.ctx), ctx); assert.deepEqual(readFileSync(clockFile), clockBytes);
  assert.deepEqual(readFileSync(f.ctx.planPath), plan); assert.deepEqual(readFileSync(f.ctx.manifestPath), manifest);
  assert.equal(one.sourceFreshness, "not-requalified-by-revision"); assert.equal(one.generationStartedAt, before.generationStartedAt);
  const operations = path.join(f.dir, "guided-v2-operations", first.idempotencyKey, "executions");
  assert.equal((await reviseRawTreatment({ dir: f.dir, submission: first })).replayed, true); assert.equal(readdirSync(operations).length, 1);
  const second = revisionRequest(f.dir, "TEST second full replacement."); await reviseRawTreatment({ dir: f.dir, submission: second });
  const historical = await reviseRawTreatment({ dir: f.dir, submission: first });
  assert.equal(historical.superseded, true); assert.equal(historical.treatmentAdmissionHash, one.treatmentAdmissionHash);
  assert.equal(readRawTreatmentAdmission(f.dir).submission.rawIntent, second.rawIntent);
  await assert.rejects(reviseRawTreatment({ dir: f.dir, submission: { ...first, rawIntent: first.rawIntent + " " } }), /idempotency/);
  assert.equal(existsSync(path.join(f.dir, "final.mp4")), false);
});

test("exact parent CAS rejects stale competitors and reused request IDs", async (t) => {
  const f = await treatmentRevisionFixture(t), first = revisionRequest(f.dir), second = revisionRequest(f.dir);
  const outcomes = await Promise.allSettled([reviseRawTreatment({ dir: f.dir, submission: first }), reviseRawTreatment({ dir: f.dir, submission: second })]);
  assert.equal(outcomes.filter((row) => row.status === "fulfilled").length, 1);
  const current = readRawTreatmentAdmission(f.dir), wanted = revisionRequest(f.dir);
  await assert.rejects(reviseRawTreatment({ dir: f.dir, submission: { ...wanted, requestId: current.submission.requestId } }), /reuses/);
  await assert.rejects(reviseRawTreatment({ dir: f.dir, submission: { ...wanted, expectedJournalHash: first.expectedJournalHash } }), /stale/);
});

for (const point of ["after-reservation", "after-fact", "after-commit"] as const) {
  test(`${point} retains evidence; only explicit same-request reconciliation or committed replay proceeds`, async (t) => {
    const f = await treatmentRevisionFixture(t), request = revisionRequest(f.dir), before = readFileSync(f.jobPath);
    await assert.rejects(reviseRawTreatment({ dir: f.dir, submission: request }, { fault: (at) => { if (at === point) throw new Error("TEST injected crash"); } }), /TEST injected/);
    const reservation = treatmentRevisionReservation(f.dir, request.parentAdmissionHash), reserved = readFileSync(reservation);
    if (point !== "after-commit") {
      assert.deepEqual(readFileSync(f.jobPath), before);
      assert.throws(() => readRawTreatmentAdmission(f.dir), /Pending treatment revision/);
      assert.equal(readTreatmentBriefHistory(f.dir).pendingRevision!.idempotencyKey, request.idempotencyKey);
      await assert.rejects(reviseRawTreatment({ dir: f.dir, submission: request }), /reconcile-revision/);
      await assert.rejects(reviseRawTreatment({ dir: f.dir, submission: { ...request, idempotencyKey: randomUUID() } }), /owns/);
    }
    const result = await reconcileRawTreatmentRevision({ dir: f.dir, submission: request });
    assert.equal(result.replayed, point === "after-commit"); assert.deepEqual(readFileSync(reservation), reserved);
    assert.equal(readRawTreatmentAdmission(f.dir).submission.rawIntent, request.rawIntent);
  });
}

test("all opening/body records and pre-claim launch directory entries block, including unknown failures", async (t) => {
  const f = await treatmentRevisionFixture(t), cut = readRawTreatmentAdmission(f.dir);
  const keys = ["openingPreparationHash", "openingExecutionClaimHash", "openingProcessOutcomeHash", "openingCleanupHash",
    "openingMediaSelectionHash", "openingApprovalHash", "bodyExecutionClaimHash", "bodyActivationHash", "bodyProcessOutcomeHash", "bodyCleanupHash", "bodyCandidateHash"];
  for (const key of keys) assert.throws(() => assertTreatmentRevisionIdle({ ...cut, pointer: { ...cut.pointer, [key]: "a".repeat(64) } }), /opening\/body/);
  const launches = path.join(f.dir, "guided-opening-launches"); mkdirSync(launches); mkdirSync(path.join(launches, "unknown-partial"));
  await assert.rejects(reviseRawTreatment({ dir: f.dir, submission: revisionRequest(f.dir) }), /launch ownership/);
  assert.equal(existsSync(path.join(f.dir, "guided-treatment-revisions")), false);
});

test("original budget expiration and late boundary expiry cannot publish a new brief", async (t) => {
  const f = await treatmentRevisionFixture(t), before = readRawTreatmentAdmission(f.dir), request = revisionRequest(f.dir);
  const wall = Date.parse(before.generationStartedAt) + 31 * 60_000;
  await assert.rejects(reviseRawTreatment({ dir: f.dir, submission: request }, {
    budgetClocks: { wall: () => wall, monotonic: () => 0 } }), /not-admitted/);
  assert.equal(observeHumanCutJob(f.dir).sha256, before.sha256);
  await assert.rejects(reconcileRawTreatmentRevision({ dir: f.dir, submission: request }), /backwards/);
});

test("self-consistent altered parent/invalidation receipts and damaged original bytes fail closed", async (t) => {
  const f = await treatmentRevisionFixture(t), request = revisionRequest(f.dir);
  await reviseRawTreatment({ dir: f.dir, submission: request });
  const held = readRawTreatmentAdmission(f.dir), original = readFileSync(f.jobPath);
  const forged = { ...held.admission, supersedesRequestHash: "b".repeat(64) };
  const changed = structuredClone(held.job); changed.guidedHandoffV2!.treatmentAdmissionHash = writeGuidedObject(f.dir, forged);
  writeFileSync(f.jobPath, JSON.stringify(changed)); assert.throws(() => readRawTreatmentAdmission(f.dir), /reservation/);
  writeFileSync(f.jobPath, original);
  const first = held.lineage[1].hash, file = path.join(f.dir, ".sniper-authority-v1/objects/receipts", `${first}.json`);
  writeFileSync(file, JSON.stringify({ ...readGuidedObject(f.dir, first), requestObjectHash: "b".repeat(64) }));
  assert.throws(() => readRawTreatmentAdmission(f.dir), /object changed/);
});

test("only dependent unapproved pointers are invalidated and their immutable objects survive", async (t) => {
  const f = await treatmentRevisionFixture(t), held = readRawTreatmentAdmission(f.dir), job = structuredClone(held.job);
  const hash = writeGuidedObject(f.dir, { scope: "TEST-only-stubbed-unapproved-work" });
  Object.assign(job.guidedHandoffV2!, { treatmentProposalHash: hash, proposalReadinessHash: hash, treatmentDraftRevisionHash: hash });
  writeFileSync(f.jobPath, JSON.stringify(job));
  t.mock.method(treatmentRevisionReads, "readiness", () => ({ scope: "TEST-only-current-readiness" }));
  const request = revisionRequest(f.dir); await reviseRawTreatment({ dir: f.dir, submission: request });
  const current = readRawTreatmentAdmission(f.dir);
  assert.deepEqual(current.admission.invalidated, { treatmentProposalHash: hash, proposalReadinessHash: hash, treatmentDraftRevisionHash: hash });
  assert.equal(current.pointer.treatmentProposalHash, undefined); assert.equal(current.pointer.proposalReadinessHash, undefined);
  assert.equal(current.pointer.treatmentDraftRevisionHash, undefined);
  assert.deepEqual(readGuidedObject(f.dir, hash), { scope: "TEST-only-stubbed-unapproved-work" });
  assert.equal(current.pointer.cutDecisionHash, held.pointer.cutDecisionHash);
});

test("brief history exposes active and superseded full text under the original clock", async (t) => {
  const f = await treatmentRevisionFixture(t), request = revisionRequest(f.dir);
  await reviseRawTreatment({ dir: f.dir, submission: request });
  const result = readTreatmentBriefHistory(f.dir);
  assert.deepEqual(result.history.map((row) => row.rawIntent), [request.rawIntent, f.first.rawIntent]);
  assert.deepEqual(result.history.map((row) => row.active), [true, false]);
  assert.equal(result.firstRequestHash, canonicalJsonSha256(f.first)); assert.equal(result.approved, false);
  assert.equal(result.revisionBindings!.parentAdmissionHash, result.currentBrief.treatmentAdmissionHash);
});

test("lost original pins, same-key different transport and late budget failure stay fail closed", async (t) => {
  const f = await treatmentRevisionFixture(t), before = readRawTreatmentAdmission(f.dir), request = revisionRequest(f.dir);
  let wall = Date.now(), mono = 0;
  await assert.rejects(reviseRawTreatment({ dir: f.dir, submission: request }, {
    budgetClocks: { wall: () => wall, monotonic: () => mono },
    fault: (point) => { if (point === "after-fact") { wall += 600001; mono += 600001; } },
  }), /deadline-exceeded/);
  assert.equal(observeHumanCutJob(f.dir).sha256, before.sha256);
  await assert.rejects(reconcileRawTreatmentRevision({ dir: f.dir, submission: { ...request, rawIntent: "TEST altered pending text" } }), /owns/);
  t.mock.method(treatmentRevisionReads, "pinnedFile", () => { throw new Error("TEST pinned implementation changed"); });
  await assert.rejects(reconcileRawTreatmentRevision({ dir: f.dir, submission: request }), /pinned implementation/);
});

test("journal-only rollback and malformed reservation cannot reactivate an earlier brief", async (t) => {
  const f = await treatmentRevisionFixture(t), before = readFileSync(f.jobPath), request = revisionRequest(f.dir);
  await reviseRawTreatment({ dir: f.dir, submission: request });
  const current = readFileSync(f.jobPath); writeFileSync(f.jobPath, before);
  assert.throws(() => readRawTreatmentAdmission(f.dir), /Pending treatment revision/);
  writeFileSync(f.jobPath, current);
  const reservation = treatmentRevisionReservation(f.dir, request.parentAdmissionHash);
  const row = JSON.parse(readFileSync(reservation, "utf8")); writeFileSync(reservation, JSON.stringify({ ...row, idempotencyKey: "../bad" }));
  assert.throws(() => readRawTreatmentAdmission(f.dir), /idempotency/);
});

test("32 admissions remain readable; a thirty-third cannot create a reservation or reset the clock", { timeout: 60_000 }, async (t) => {
  const f = await treatmentRevisionFixture(t), firstClock = readRawTreatmentAdmission(f.dir).clock.hash;
  for (let index = 1; index < 32; index++) await reviseRawTreatment({ dir: f.dir, submission: revisionRequest(f.dir, `TEST full brief revision ${index}`) });
  const held = readRawTreatmentAdmission(f.dir), request = revisionRequest(f.dir);
  assert.equal(held.lineage.length, 32); assert.equal(held.clock.hash, firstClock);
  await assert.rejects(reviseRawTreatment({ dir: f.dir, submission: request }), /capacity/);
  assert.equal(existsSync(treatmentRevisionReservation(f.dir, request.parentAdmissionHash)), false);
});

test("revision before first compile rejects missing or changed transitive executor closure without changing its parent", async (t) => {
  const f = await treatmentRevisionFixture(t), original = readFileSync(f.jobPath), request = revisionRequest(f.dir);
  assert.equal(readRawTreatmentAdmission(f.dir).pointer.treatmentProposalHash, undefined);
  for (const message of ["TEST transitive TS source differs", "TEST pinned TS source is missing"]) {
    t.mock.method(treatmentRevisionReads, "implementation", () => { throw new Error(message); });
    await assert.rejects(reviseRawTreatment({ dir: f.dir, submission: request }), new RegExp(message));
    assert.deepEqual(readFileSync(f.jobPath), original);
    assert.equal(existsSync(treatmentRevisionReservation(f.dir, request.parentAdmissionHash)), false);
  }
});

test("complete transitive closure is rechecked immediately before CAS after retained revision fact", async (t) => {
  const f = await treatmentRevisionFixture(t), original = readFileSync(f.jobPath), request = revisionRequest(f.dir);
  let observations = 0;
  t.mock.method(treatmentRevisionReads, "implementation", () => {
    if (++observations > 1) throw new Error("TEST transitive TS changed before CAS");
    return { scope: "TEST-only-initial-complete-closure" };
  });
  await assert.rejects(reviseRawTreatment({ dir: f.dir, submission: request }), /changed before CAS/);
  assert.equal(observations, 2); assert.deepEqual(readFileSync(f.jobPath), original);
  assert.throws(() => readRawTreatmentAdmission(f.dir), /Pending treatment revision/);
});

test("status rejects a late reservation even when the journal and earlier brief observation stay unchanged", async (t) => {
  const f = await treatmentRevisionFixture(t), held = readRawTreatmentAdmission(f.dir), request = revisionRequest(f.dir);
  t.mock.method(treatmentStatusReaders, "admission", () => {
    mkdirSync(path.join(f.dir, "guided-treatment-revisions"));
    writeFileSync(treatmentRevisionReservation(f.dir, request.parentAdmissionHash), JSON.stringify({ schemaVersion: 1,
      kind: "guided-treatment-revision-reservation", parentAdmissionHash: request.parentAdmissionHash,
      requestObjectHash: canonicalJsonSha256(request), idempotencyKey: request.idempotencyKey }));
    return held;
  });
  assert.throws(() => readTreatmentCommandStatus(f.dir), /reservation changed during status/);
  assert.equal(observeHumanCutJob(f.dir).sha256, held.sha256);
});
