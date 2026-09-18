import assert from "node:assert/strict";
import path from "node:path";
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { test } from "node:test";
import { readGuidedTreatmentProposal } from "../guided-proposal-store";
import { readGuidedProposalReadiness } from "../guided-proposal-review-store";
import { reviewGuidedTreatmentProposal } from "../guided-proposal-review";
import { writeGuidedObject } from "../guided-cut-v2-store";
import { createGuidedProposalFixture, passingReadinessResult, readinessRequest } from "./_guided-proposal-fixture";
import { passingGateBundle } from "./_readiness-gate-stub";

const MINUTE = 60_000;

test("readiness checks the original phase before sources or paid critics and retains rejected admission", async () => {
  const fixture = await createGuidedProposalFixture(), dir = fixture.ctx.dir;
  try {
    const original = readGuidedTreatmentProposal(dir), submission = readinessRequest(dir), before = readFileSync(fixture.jobPath);
    const wall = Date.parse(original.generationStartedAt) + 21 * MINUTE;
    await assert.rejects(reviewGuidedTreatmentProposal({ dir, submission }, {
      budgetClocks: { wall: () => wall, monotonic: () => 0 },
      verifySources: async () => { throw new Error("must not verify rejected attempt"); },
      critic: async () => { throw new Error("must not pay for rejected attempt"); },
    }), /not-admitted/);
    assert.deepEqual(readFileSync(fixture.jobPath), before);
    const root = path.join(dir, "guided-v2-operations", submission.idempotencyKey, "executions");
    const execution = path.join(root, readdirSync(root)[0]);
    const admission = JSON.parse(readFileSync(path.join(execution, "budget-admission.json"), "utf8"));
    assert.equal(admission.admitted, false); assert.equal(admission.clockHash, original.clock.hash);
    assert.equal(admission.elapsedRequestWallMs, 21 * MINUTE);
    assert.equal(JSON.parse(readFileSync(path.join(execution, "result.json"), "utf8")).budget.state, "not-admitted");
  } finally { fixture.cleanup(); }
});

test("late critic failure advances original high-water; retry and final receipt cannot recover expired allowance", async () => {
  const fixture = await createGuidedProposalFixture(), dir = fixture.ctx.dir;
  try {
    const submission = readinessRequest(dir), before = readFileSync(fixture.jobPath);
    const began = Date.now(); let wall = began, mono = 0;
    const budgetClocks = { wall: () => wall, monotonic: () => mono };
    await assert.rejects(reviewGuidedTreatmentProposal({ dir, submission }, { gates: passingGateBundle(), budgetClocks, critic: async (input) => {
      if (input.criticIndex === 0) { wall += 9 * MINUTE; mono += 9 * MINUTE; throw new Error("TEST late readiness critic failure"); }
      return passingReadinessResult(input);
    } }), /late readiness critic/);
    wall = began + 2 * MINUTE; mono = 0;
    await assert.rejects(reviewGuidedTreatmentProposal({ dir, submission }, { gates: passingGateBundle(), budgetClocks,
      critic: async () => { throw new Error("rollback must not reach another critic"); } }), /across attempts/);
    wall = began + 10 * MINUTE;
    await assert.rejects(reviewGuidedTreatmentProposal({ dir, submission }, { gates: passingGateBundle(), budgetClocks,
      critic: async (input) => passingReadinessResult(input), fault: (point) => {
        if (point === "after-receipt") { wall += 20 * MINUTE; mono += 20 * MINUTE; }
      } }), /deadline-exceeded/);
    assert.deepEqual(readFileSync(fixture.jobPath), before);
    assert.equal(readGuidedTreatmentProposal(dir).pointer.proposalReadinessHash, undefined);
  } finally { fixture.cleanup(); }
});

test("new readiness reopens exact budget proof; a pre-gate v1/v2 receipt is rejected, never a fresh allowance", async () => {
  const fixture = await createGuidedProposalFixture(), dir = fixture.ctx.dir;
  try {
    const submission = readinessRequest(dir);
    const result = await reviewGuidedTreatmentProposal({ dir, submission }, { gates: passingGateBundle(), critic: async (input) => passingReadinessResult(input) });
    assert.equal(result.readinessReceipt.schemaVersion, 3);
    assert.equal(result.generationBudgetQualification, "proposal-phase-only-not-full-request-accounting");
    const row = result.readinessReceipt, execution = path.join(dir, "guided-v2-operations", submission.idempotencyKey,
      "executions", String(row.executionId)), file = path.join(execution, "budget-precommit.json"), saved = readFileSync(file);
    writeFileSync(file, "{}"); assert.throws(() => readGuidedProposalReadiness(dir), /Private readiness object changed/);
    writeFileSync(file, saved);
    // A historical receipt predates the deterministic full-plan gate bundle, so it fails closed
    // instead of qualifying an unlinted draft; there is no legacy budget/gate exemption left.
    const { budgetAdmissionHash, budgetPrecommitHash, deterministicGates, ...old } = row;
    void budgetAdmissionHash; void budgetPrecommitHash; void deterministicGates;
    for (const schemaVersion of [1, 2]) {
      const oldHash = writeGuidedObject(dir, { ...old, schemaVersion });
      writeFileSync(fixture.jobPath, JSON.stringify({ ...result.job,
        guidedHandoffV2: { ...result.pointer, proposalReadinessHash: oldHash } }));
      assert.throws(() => readGuidedProposalReadiness(dir), /predates the deterministic full-plan gates/);
      await assert.rejects(reviewGuidedTreatmentProposal({ dir, submission }, {
        gates: passingGateBundle(), critic: async () => { throw new Error("historical replay must not pay critics"); },
      }), /predates the deterministic full-plan gates/);
    }
  } finally { fixture.cleanup(); }
});
