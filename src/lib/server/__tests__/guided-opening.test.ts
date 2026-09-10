import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { parsePrepareGuidedOpening, parseOpeningPreparationReceipt } from "@/lib/producer/contracts/guided-opening-v1";
import { createGuidedProposalFixture, passingReadinessResult, readinessRequest } from "./_guided-proposal-fixture";
import { passingGateBundle } from "./_readiness-gate-stub";
import { reviewGuidedTreatmentProposal } from "../guided-proposal-review";
import { readGuidedProposalReadiness } from "../guided-proposal-review-store";
import { readGuidedTreatmentProposal } from "../guided-proposal-store";
import { readHistoricalGuidedProposal } from "../guided-proposal-history";
import { prepareGuidedOpening } from "../guided-opening";
import { readGuidedOpeningPreparation } from "../guided-opening-store";
import { buildOpeningAuthority } from "../guided-opening-authority";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { readGuidedObject, writeGuidedObject } from "../guided-cut-v2-store";

type Fixture = Awaited<ReturnType<typeof createGuidedProposalFixture>>;
function requestFor(dir: string) {
  const ready = readGuidedProposalReadiness(dir);
  return parsePrepareGuidedOpening({ schemaVersion: 1, operation: "prepare-guided-opening", idempotencyKey: randomUUID(),
    expectedToken: ready.job.token, expectedJournalHash: ready.sha256, proposalReadinessHash: ready.readinessHash,
    treatmentDraftRevisionHash: ready.pointer.treatmentDraftRevisionHash });
}
function noMediaOrPromotion(dir: string) {
  for (const name of ["final.mp4", "base.mp4", "program_audio.v2.json", ".sniper-qc-approved.json", ".sniper-template-usage-approved.json", ".sniper-authority-v1/APPROVED_HEAD", ".render-graph-v1/ACTIVE.json"]) {
    assert.equal(existsSync(path.join(dir, name)), false, name);
  }
}

async function failedAttempts(fixture: Fixture, request: ReturnType<typeof requestFor>, before: Buffer) {
  const dir = fixture.ctx.dir;
  await assert.rejects(prepareGuidedOpening({ dir, submission: { ...request, approved: true } }));
  await assert.rejects(prepareGuidedOpening({ dir, submission: request }, { fault: () => { throw new Error("TEST interrupted observation"); } }), /interrupted observation/);
  await assert.rejects(prepareGuidedOpening({ dir, submission: request }, { fault: (point) => {
    if (point === "after-authority-observation") writeFileSync(fixture.jobPath, JSON.stringify({ ...JSON.parse(before.toString()), message: "TEST competing writer" }));
  } }), /stale/); writeFileSync(fixture.jobPath, before);
  await assert.rejects(prepareGuidedOpening({ dir, submission: request }, { fault: (point) => {
    if (point === "after-receipt") throw new Error("TEST orphan preparation receipt");
  } }), /orphan/);
  await assert.rejects(prepareGuidedOpening({ dir, submission: request }, { fault: (point) => {
    if (point === "after-receipt") writeFileSync(fixture.jobPath, JSON.stringify({ ...JSON.parse(before.toString()), message: "TEST final CAS race" }));
  } }), /compare-and-swap/); writeFileSync(fixture.jobPath, before);
  assert.deepEqual(readFileSync(fixture.jobPath), before); noMediaOrPromotion(dir);
}

test("actual stored V4 cut/proposal/readiness reaches honest unsupported preparation with durable failure, CAS and replay", async () => {
  const fixture = await createGuidedProposalFixture({ proposalVersion: 4 }), dir = fixture.ctx.dir;
  try {
    await reviewGuidedTreatmentProposal({ dir, submission: readinessRequest(dir) }, { gates: passingGateBundle(), critic: async (input) => passingReadinessResult(input) });
    const request = requestFor(dir), before = readFileSync(fixture.jobPath), plan = readFileSync(fixture.ctx.planPath);
    const active = readFileSync(path.join(dir, ".sniper-authority-v1/ACTIVE_HEAD"));
    writeFileSync(fixture.ctx.planPath, JSON.stringify({ ...JSON.parse(plan.toString()), cutTrack: [] }));
    await assert.rejects(prepareGuidedOpening({ dir, submission: request })); writeFileSync(fixture.ctx.planPath, plan);
    const ready = readGuidedProposalReadiness(dir), authority = buildOpeningAuthority(ready);
    assert.equal(ready.result.proposal.schemaVersion, 4); // This historical V4 test must not follow the current authoring default.
    assert.equal(authority.bindings!.graphics.length, 0); assert.deepEqual(authority.blockerCodes, ["opening-renderer-unavailable"]);
    assert.equal(authority.input.occurrenceEvidenceHash, authority.bindings!.occurrenceEvidenceHash);
    await failedAttempts(fixture, request, before);
    let sourceCalls = 0;
    const source = JSON.parse(readFileSync(fixture.ctx.manifestPath, "utf8")).sources.at(-1).path;
    const sourceBytes = readFileSync(source), changed = Buffer.from(sourceBytes); changed[changed.length - 1] ^= 1;
    writeFileSync(source, changed);
    const result = await prepareGuidedOpening({ dir, submission: request }, { verifySources: async () => { sourceCalls++; throw new Error("Known unavailable must not spend source work"); } });
    writeFileSync(source, sourceBytes); // Unsupported did not make a freshness or media claim about these changed bytes.
    assert.equal(result.state, "unsupported-before-render"); assert.equal(result.media, null); assert.equal(result.available, false);
    assert.equal(result.currentExecutionAuthority, false); assert.equal(result.receipt.generationStartedAt, ready.generationStartedAt);
    assert.equal(sourceCalls, 0); assert.equal(result.receipt.sourceObservation, "not-run-known-unsupported");
    assert.equal(result.proposal.job.status, "treatment_admitted"); assert.equal(result.proposal.job.workerPid, undefined);
    assert.equal((await prepareGuidedOpening({ dir, submission: request }, { verifySources: async () => { throw new Error("must not reverify replay"); } })).replayed, true);
    await assert.rejects(prepareGuidedOpening({ dir, submission: { ...request, idempotencyKey: randomUUID() } }), /stale/);
    assert.deepEqual(readFileSync(fixture.ctx.planPath), plan); assert.deepEqual(readFileSync(path.join(dir, ".sniper-authority-v1/ACTIVE_HEAD")), active);
    const roots = path.join(dir, "guided-v2-operations", request.idempotencyKey, "executions"), attempts = readdirSync(roots);
    assert.equal(attempts.length, 5);
    const outcomes = attempts.map((id) => JSON.parse(readFileSync(path.join(roots, id, "result.json"), "utf8")));
    assert.equal(outcomes.filter((row) => row.state === "failed-or-incomplete").length, 4);
    assert.ok(outcomes.every((row) => row.generationStartedAt === ready.generationStartedAt && row.rendererStarted === false));
    assert.ok(outcomes.every((row) => Number.isFinite(row.elapsedMs) && row.elapsedMs >= 0));
    testStoredOpeningCorruption(fixture, result); testHistoricalReadability(dir, fixture.root);
    noMediaOrPromotion(dir);
  } finally { fixture.cleanup(); }
});

function testStoredOpeningCorruption(fixture: Fixture, result: Awaited<ReturnType<typeof prepareGuidedOpening>>) {
  const dir = fixture.ctx.dir, journal = readFileSync(fixture.jobPath);
  for (const patch of [{ media: { path: "/tmp/fake.mp4" } }, { state: "complete" }, { approved: true }, { executable: true }]) {
    assert.throws(() => parseOpeningPreparationReceipt({ ...result.receipt, ...patch }), /cannot claim/);
  }
  const hash = result.receipt.frameBindingsHash!, file = path.join(dir, ".sniper-authority-v1/objects/receipts", `${hash}.json`);
  const bytes = readFileSync(file); writeFileSync(file, "{}");
  assert.throws(() => readGuidedOpeningPreparation(dir), /object changed/); writeFileSync(file, bytes);
  const forged = writeGuidedObject(dir, { ...result.receipt, executionId: "../../outside" });
  const job = JSON.parse(journal.toString()); job.guidedHandoffV2.openingPreparationHash = forged;
  writeFileSync(fixture.jobPath, JSON.stringify(job)); assert.throws(() => readGuidedOpeningPreparation(dir), /executionId/);
  writeFileSync(fixture.jobPath, journal); assert.equal(readGuidedObject(dir, result.preparationHash).approved, false);
}

function testHistoricalReadability(dir: string, unrelatedWorkingDirectory: string) {
  const current = process.cwd(), before = observeHumanCutJob(dir).sha256;
  try {
    process.chdir(unrelatedWorkingDirectory); // Unavailable current runtime, without editing repository source.
    assert.throws(() => readGuidedTreatmentProposal(dir));
    const historical = readHistoricalGuidedProposal(dir);
    assert.equal(historical.proposalVersion, 4); assert.equal(historical.currentExecutionAuthority, false);
    assert.equal(historical.available, false); assert.equal(historical.sourceCurrentness, "not-observed");
    assert.equal(historical.readinessCurrentness, "not-revalidated"); assert.match(historical.rawIntent, /Preserve/);
    assert.equal(observeHumanCutJob(dir).sha256, before);
  } finally { process.chdir(current); }
}
