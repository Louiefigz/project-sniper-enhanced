import assert from "node:assert/strict";
import path from "node:path";
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { test } from "node:test";
import { admitGuidedBodyClaim } from "../guided-body-claim";
import { readGuidedBodyClaim, bodyClaimJournal } from "../guided-body-lineage";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { bodyClaimFixture } from "./_guided-body-claim-fixture";
import { guardProjectMutation } from "@/app/api/_lib/project-mutation";
import { parseGuidedBodyExecutionClaim } from "@/lib/producer/contracts/guided-body-claim-v1";
import { canonicalJsonSha256 as hash } from "../auto-edit-hash";
import { canonicalJson } from "../auto-edit-hash";
import { writeGuidedObject } from "../guided-cut-v2-store";
import { readHistoricalOpeningCleanup } from "../guided-opening-cleanup-store";
import { captureBodyAttemptStart } from "../guided-body-deadline";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";

test("actual durable body claim is non-executable, preserves approval, and exact replay does no hold or new execution", async () => {
  const f = bodyClaimFixture();
  try {
    const plan = readFileSync(f.base.ctx.planPath), result = await admitGuidedBodyClaim({ dir: f.dir, submission: f.submission }, f.services);
    assert.equal(result.state, "admission-fenced"); assert.equal(result.executable, false); assert.equal(result.replayed, false);
    assert.equal(result.workerState, "not-installed"); assert.equal(result.deliveryApproved, false);
    const held = readGuidedBodyClaim(f.dir, f.reads), references = held.input.input.references as Record<string, Record<string, unknown>>;
    assert.deepEqual(Object.keys(references.base).sort(), ["path", "sha256"]);
    assert.equal(((f.proof.result.record.value.fullProgram as Record<string, unknown>).base as Record<string, unknown>).videoDecodeSucceeded, true);
    assert.equal(observeHumanCutJob(f.dir).job.guidedHandoffV2?.openingApprovalHash, f.submission.openingApprovalHash);
    assert.deepEqual(readFileSync(f.base.ctx.planPath), plan); assert.equal(f.services.counts.holds, 1);
    const directory = path.join(f.dir, "guided-v2-operations", f.submission.idempotencyKey, "executions");
    assert.deepEqual(readdirSync(directory), [result.executionId]);
    const journal = readFileSync(f.base.jobPath), repeat = await admitGuidedBodyClaim({ dir: f.dir, submission: f.submission }, f.services);
    assert.equal(repeat.replayed, true); assert.equal(repeat.executionId, result.executionId); assert.equal(f.services.counts.holds, 1);
    assert.deepEqual(readFileSync(f.base.jobPath), journal); assert.deepEqual(readdirSync(directory), [result.executionId]);
  } finally { f.cleanup(); }
});

test("pending body claim fences ordinary and typed checkpoint mutations after admission lease release", async () => {
  const f = bodyClaimFixture();
  try {
    await admitGuidedBodyClaim({ dir: f.dir, submission: f.submission }, f.services);
    const current = observeHumanCutJob(f.dir), before = readFileSync(f.base.jobPath);
    for (const action of ["continue-approved-opening", "prepare-guided-opening", "approve-guided-opening", "reconcile-guided-opening"] as const) {
      const blocked = guardProjectMutation({ projectRoot: f.root, producerDir: f.dir, operation: action,
        checkpointVerification: { workflowVersion: 2, action, expectedStatus: "treatment_admitted", expectedToken: current.job.token, expectedJournalHash: current.sha256 } });
      assert.equal(blocked.response?.status, 409); assert.equal(blocked.lease, undefined);
    }
    assert.equal(guardProjectMutation({ projectRoot: f.root, producerDir: f.dir, operation: "save" }).response?.status, 409);
    await assert.rejects(admitGuidedBodyClaim({ dir: f.dir, submission: { ...f.submission, idempotencyKey: randomUUID() } }, f.services), /Another body request/);
    assert.deepEqual(readFileSync(f.base.jobPath), before);
  } finally { f.cleanup(); }
});

test("arbitrary descendant, changed approved snapshot and re-sealed held input cannot pass body lineage", async () => {
  const f = bodyClaimFixture();
  try {
    await admitGuidedBodyClaim({ dir: f.dir, submission: f.submission }, f.services);
    const current = observeHumanCutJob(f.dir), held = readGuidedBodyClaim(f.dir, f.reads);
    writeFileSync(f.base.jobPath, JSON.stringify({ ...current.job, message: "unrelated descendant" }));
    assert.throws(() => readGuidedBodyClaim(f.dir, f.reads), /single approved-to-claim/);
    writeFileSync(f.base.jobPath, current.bytes);
    const snapshot = readFileSync(held.snapshotPath); writeFileSync(held.snapshotPath, `${snapshot.toString()}\n`);
    assert.throws(() => readGuidedBodyClaim(f.dir, f.reads), /snapshot is changed/);
    writeFileSync(held.snapshotPath, snapshot);
    const inputPath = path.join(held.execution, "held-input.json"), input = JSON.parse(readFileSync(inputPath, "utf8"));
    input.opening.inputSha256 = "b".repeat(64); writeFileSync(inputPath, JSON.stringify(input));
    assert.throws(() => readGuidedBodyClaim(f.dir, f.reads), /differs from its held object/);
  } finally { f.cleanup(); }
});

test("failed verification retains an immutable attempt and cannot silently start a fresh replay", async () => {
  const f = bodyClaimFixture();
  try {
    const before = readFileSync(f.base.jobPath), services = { ...f.services, hold: async () => { throw new Error("TEST source verification failed"); } };
    await assert.rejects(admitGuidedBodyClaim({ dir: f.dir, submission: f.submission }, services), /source verification failed/);
    assert.deepEqual(readFileSync(f.base.jobPath), before);
    const directory = path.join(f.dir, "guided-v2-operations", f.submission.idempotencyKey, "executions"), ids = readdirSync(directory);
    assert.equal(ids.length, 1); assert.equal(JSON.parse(readFileSync(path.join(directory, ids[0], "result.json"), "utf8")).status, "failed");
    await assert.rejects(admitGuidedBodyClaim({ dir: f.dir, submission: f.submission }, f.services), /retained incomplete admission/);
    assert.deepEqual(readdirSync(directory), ids);
    await assert.rejects(admitGuidedBodyClaim({ dir: f.dir, submission: { ...f.submission, selectionHash: "b".repeat(64) } }, f.services), /idempotency key conflicts/);
  } finally { f.cleanup(); }
});

test("lost response after actual claim CAS leaves fence and same request can read it without spawning", async () => {
  const f = bodyClaimFixture();
  try {
    const services = { ...f.services, read: () => { throw new Error("TEST lost response after commit"); } };
    await assert.rejects(admitGuidedBodyClaim({ dir: f.dir, submission: f.submission }, services), /lost response/);
    assert.ok(observeHumanCutJob(f.dir).job.guidedHandoffV2?.bodyExecutionClaimHash);
    const replay = await admitGuidedBodyClaim({ dir: f.dir, submission: f.submission }, f.services);
    assert.equal(replay.replayed, true); assert.equal(f.services.counts.holds, 1); assert.equal(replay.executable, false);
  } finally { f.cleanup(); }
});

test("body claim parser rejects executable flags, missing fields and a changed original clock", async () => {
  const f = bodyClaimFixture();
  try {
    await admitGuidedBodyClaim({ dir: f.dir, submission: f.submission }, f.services);
    const claim = readGuidedBodyClaim(f.dir, f.reads).claim;
    assert.deepEqual(parseGuidedBodyExecutionClaim(claim), claim);
    for (const patch of [{ executable: true }, { workerState: "ready" }, { bodyGenerated: true }, { deliveryApproved: true },
      { extra: true }, { beforeJournalHash: "" }, { generationStartedAt: "2099-01-01T00:00:00.000Z" }]) assert.throws(() => parseGuidedBodyExecutionClaim({ ...claim, ...patch }));
    for (const key of Object.keys(claim)) {
      const row = { ...claim } as Record<string, unknown>; delete row[key]; assert.throws(() => parseGuidedBodyExecutionClaim(row));
    }
    assert.notEqual(hash(claim), hash({ ...claim, executionId: randomUUID() }));
  } finally { f.cleanup(); }
});

test("a re-sealed claim edge cannot turn a changed approved journal into human approval", async () => {
  const f = bodyClaimFixture();
  try {
    await admitGuidedBodyClaim({ dir: f.dir, submission: f.submission }, f.services);
    const held = readGuidedBodyClaim(f.dir, f.reads), job = { ...held.before.job, message: "resealed arbitrary approved descendant" };
    const snapshotHash = hash(job), file = path.join(f.dir, "human-cut-job-snapshots", `${snapshotHash}.json`);
    writeFileSync(file, canonicalJson(job));
    const before = { ...readCutPreviewObject(file), job }, claim = { ...held.claim, beforeJournalHash: snapshotHash };
    const claimHash = writeGuidedObject(f.dir, claim); writeFileSync(path.join(held.execution, "claim.json"), canonicalJson(claim));
    writeFileSync(f.base.jobPath, JSON.stringify(bodyClaimJournal(before, claim, claimHash)));
    const original = f.reads.selection(f.dir, f.current.sha256);
    const reads = { ...f.reads, selection: () => ({ ...original, observed: { ...original.observed, ...before } }) };
    assert.throws(() => readGuidedBodyClaim(f.dir, reads), /approval journal transition/);
  } finally { f.cleanup(); }
});

test("wrong and transplanted historical snapshots reject before opening proof is consumed", async () => {
  const f = bodyClaimFixture(), other = bodyClaimFixture();
  try {
    await admitGuidedBodyClaim({ dir: f.dir, submission: f.submission }, f.services);
    assert.throws(() => readHistoricalOpeningCleanup(f.dir, { job: f.current.job } as unknown as string), /historical opening journal/);
    assert.throws(() => readHistoricalOpeningCleanup(f.dir, "b".repeat(64)));
    const file = path.join(f.dir, "human-cut-job-snapshots", `${other.current.sha256}.json`);
    writeFileSync(file, other.current.bytes);
    assert.throws(() => readHistoricalOpeningCleanup(f.dir, other.current.sha256), /another project/);
  } finally { f.cleanup(); other.cleanup(); }
});

test("stale token and post-hold expiry cannot create a body claim or recover consumed time", async () => {
  const f = bodyClaimFixture();
  try {
    await assert.rejects(admitGuidedBodyClaim({ dir: f.dir, submission: { ...f.submission, expectedToken: "wrong" } }, f.services));
    assert.equal(f.services.counts.holds, 0);
    let wall = Date.now(), mono = performance.now();
    const services = { ...f.services, capture: () => captureBodyAttemptStart({ wall: () => wall, monotonic: () => mono }),
      hold: async (input: Parameters<typeof f.services.hold>[0]) => {
        const held = await f.services.hold(input); wall += 56 * 60_000; mono += 56 * 60_000; return held;
      } };
    await assert.rejects(admitGuidedBodyClaim({ dir: f.dir, submission: f.submission }, services), /deadline-exceeded/);
    assert.equal(observeHumanCutJob(f.dir).job.guidedHandoffV2?.bodyExecutionClaimHash, undefined);
    const root = path.join(f.dir, "generation-clock-observations", f.origin.clockHash);
    const latest = readdirSync(root).map((name) => readGuidedObjectClock(root, name)).sort().at(-1)!;
    assert.ok(latest >= new Date(wall).toISOString());
    await assert.rejects(admitGuidedBodyClaim({ dir: f.dir, submission: { ...f.submission, idempotencyKey: randomUUID() } }, f.services), /clock-invalid/);
  } finally { f.cleanup(); }
});

function readGuidedObjectClock(root: string, name: string): string {
  return String(JSON.parse(readFileSync(path.join(root, name), "utf8")).observedAt);
}

test("a re-sealed body-only clock cannot depart from the actually approved opening origin", async () => {
  const f = bodyClaimFixture();
  try {
    await admitGuidedBodyClaim({ dir: f.dir, submission: f.submission }, f.services);
    const held = readGuidedBodyClaim(f.dir, f.reads), value = JSON.parse(readFileSync(path.join(held.execution, "held-input.json"), "utf8"));
    value.input.origin.clockHash = "b".repeat(64);
    const heldInputHash = writeGuidedObject(f.dir, value); writeFileSync(path.join(held.execution, "held-input.json"), canonicalJson(value));
    const claim = { ...held.claim, heldInputHash, clockHash: "b".repeat(64) }, claimHash = writeGuidedObject(f.dir, claim);
    writeFileSync(path.join(held.execution, "claim.json"), canonicalJson(claim));
    writeFileSync(f.base.jobPath, JSON.stringify(bodyClaimJournal(held.before, claim, claimHash)));
    assert.throws(() => readGuidedBodyClaim(f.dir, f.reads), /approved opening clock/);
  } finally { f.cleanup(); }
});

test("expiry immediately after a valid CAS budget observation is caught after the receipt reads", async () => {
  const f = bodyClaimFixture();
  try {
    let offset = 0, samples = 0;
    const services = { ...f.services, capture: () => captureBodyAttemptStart({ wall: () => Date.now(), monotonic: () => {
      const current = performance.now() + offset;
      if (new Error().stack?.includes("commitGuard") && ++samples === 2) offset += 56 * 60_000;
      return current;
    } }) };
    const before = readFileSync(f.base.jobPath);
    await assert.rejects(admitGuidedBodyClaim({ dir: f.dir, submission: f.submission }, services), /deadline-exceeded/);
    assert.ok(samples >= 3); assert.deepEqual(readFileSync(f.base.jobPath), before);
    assert.equal(observeHumanCutJob(f.dir).job.guidedHandoffV2?.bodyExecutionClaimHash, undefined);
  } finally { f.cleanup(); }
});

test("an invalid original clock after operation creation retains a failed result and never retries as fresh", async () => {
  const f = bodyClaimFixture();
  try {
    const earlier = Date.parse(f.origin.startedAt) - 1;
    const services = { ...f.services, capture: () => captureBodyAttemptStart({ wall: () => earlier, monotonic: () => performance.now() }) };
    await assert.rejects(admitGuidedBodyClaim({ dir: f.dir, submission: f.submission }, services), /original request clock is invalid/);
    const root = path.join(f.dir, "guided-v2-operations", f.submission.idempotencyKey, "executions"), ids = readdirSync(root);
    assert.equal(ids.length, 1);
    const result = JSON.parse(readFileSync(path.join(root, ids[0], "result.json"), "utf8"));
    assert.equal(result.status, "failed"); assert.equal(result.clock.state, "unverified"); assert.equal(result.claimCleared, false);
    assert.equal(observeHumanCutJob(f.dir).job.guidedHandoffV2?.bodyExecutionClaimHash, undefined);
    await assert.rejects(admitGuidedBodyClaim({ dir: f.dir, submission: f.submission }, f.services), /retained incomplete admission/);
    assert.deepEqual(readdirSync(root), ids);
  } finally { f.cleanup(); }
});
