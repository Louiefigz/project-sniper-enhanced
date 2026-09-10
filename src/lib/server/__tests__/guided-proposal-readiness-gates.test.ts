import assert from "node:assert/strict";
import path from "node:path";
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { test } from "node:test";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { cutApprovalPath } from "@/app/api/producer/auto-edit/cut-approval";
import { PROPOSAL_DETERMINISTIC_GATE_CHECK, PROPOSAL_PENDING_CHECKS } from "@/lib/producer/contracts/proposal-readiness-v1";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { reviewGuidedTreatmentProposal } from "../guided-proposal-review";
import { readGuidedProposalReadiness } from "../guided-proposal-review-store";
import { readGuidedTreatmentProposal } from "../guided-proposal-store";
import { writeGuidedObject } from "../guided-cut-v2-store";
import { createGuidedProposalFixture, passingReadinessResult, readinessRequest } from "./_guided-proposal-fixture";
import { guidedProposalOutput, stubGateBundle } from "./_readiness-gate-stub";

interface GateLedger { ok: boolean; hash: string; planHash: string; executedChecks: string[]; pendingChecks: string[] }

function executionDir(dir: string, idempotencyKey: string, executionId: unknown): string {
  return path.join(dir, "guided-v2-operations", idempotencyKey, "executions", String(executionId));
}

function retained(root: string, name: string): Record<string, unknown> {
  return readCutPreviewObject(path.join(root, name)).value;
}

test("failed deterministic gates block readiness before a single independent critic is paid", async () => {
  const fixture = await createGuidedProposalFixture({ output: guidedProposalOutput }), dir = fixture.ctx.dir;
  try {
    const proposal = readGuidedTreatmentProposal(dir), submission = readinessRequest(dir);
    const gates = stubGateBundle({ failures: {
      plan_lint: ["TEST output 3.0s below mode floor 300s", "TEST missing reason — graphics must be purposeful"],
      hook_contract: ["TEST hook: no graphic/overlay opens by 4s"],
    } });
    let critics = 0;
    const result = await reviewGuidedTreatmentProposal({ dir, submission }, { gates: gates.run,
      critic: async (input) => { critics += 1; return passingReadinessResult(input); } });
    assert.equal(critics, 0); assert.equal(gates.calls.length, 1);
    assert.equal(result.deterministicGates.ok, false); assert.equal(result.readiness.verdict, "blocked");
    assert.equal(result.draftRevision, null); assert.equal(result.job.guidedHandoffV2?.treatmentDraftRevisionHash, undefined);
    assert.ok(result.job.guidedHandoffV2?.proposalReadinessHash);
    assert.match(result.job.message ?? "", /plan_lint: TEST output 3\.0s below mode floor 300s/);
    assert.match(result.job.message ?? "", /hook_contract: TEST hook/);
    const root = executionDir(dir, submission.idempotencyKey, result.readinessReceipt.executionId);
    for (const name of ["gate-plan.json", "gate-manifest.json", "gate-bundle.json", "packet.json",
      "implementation.json", "review-bundle.json"]) assert.ok(existsSync(path.join(root, name)), name);
    for (const name of ["critic-1", "critic-2"]) assert.equal(existsSync(path.join(root, name)), false, name);
    const bundle = retained(root, "gate-bundle.json");
    assert.equal(bundle.ok, false); assert.equal(bundle.overranBudget, false);
    assert.equal(bundle.kind, "guided-proposal-deterministic-gate-bundle");
    assert.deepEqual(retained(root, "gate-plan.json"), proposal.result.candidate);
    assert.deepEqual(retained(root, "gate-manifest.json"), readCutPreviewObject(fixture.ctx.manifestPath).value);
    assert.equal((retained(root, "review-bundle.json").criticResultHashes as unknown[]).length, 0);
    assert.equal(retained(root, "result.json").state, "blocked-deterministic-gates");
    const ledger = result.readinessReceipt.deterministicGates as GateLedger;
    assert.deepEqual(ledger.executedChecks, []); assert.deepEqual(ledger.pendingChecks, [...PROPOSAL_PENDING_CHECKS]);
    assert.equal(ledger.hash, canonicalJsonSha256(bundle));
    assert.equal(readGuidedProposalReadiness(dir).deterministicGates.hash, ledger.hash);
    const saved = readFileSync(path.join(root, "gate-bundle.json"));
    writeFileSync(path.join(root, "gate-bundle.json"), "{}");
    assert.throws(() => readGuidedProposalReadiness(dir), /Private readiness object changed/);
    writeFileSync(path.join(root, "gate-bundle.json"), saved);
    assert.equal(readGuidedProposalReadiness(dir).readiness.verdict, "blocked");
  } finally { fixture.cleanup(); }
});

test("passing deterministic gates admit both critics and report the gate as executed, not pending", async () => {
  const fixture = await createGuidedProposalFixture({ output: guidedProposalOutput }), dir = fixture.ctx.dir;
  try {
    const proposal = readGuidedTreatmentProposal(dir), submission = readinessRequest(dir), gates = stubGateBundle();
    let critics = 0;
    const result = await reviewGuidedTreatmentProposal({ dir, submission }, { gates: gates.run,
      critic: async (input) => { critics += 1; return passingReadinessResult(input); } });
    assert.equal(critics, 2); assert.equal(result.deterministicGates.ok, true);
    assert.equal(result.readiness.verdict, "clean"); assert.equal(result.draftRevision!.workflowState, "TREATMENT_DRAFT");
    const root = executionDir(dir, submission.idempotencyKey, result.readinessReceipt.executionId);
    assert.equal(gates.calls.length, 1);
    const input = gates.calls[0];
    assert.equal(input.planPath, path.join(root, "gate-plan.json"));
    assert.equal(input.manifestPath, fixture.ctx.manifestPath);
    assert.equal(input.transcriptsDir, fixture.ctx.transcriptsDir);
    assert.equal(input.cutApprovalPath, cutApprovalPath(fixture.ctx));
    assert.ok(existsSync(input.cutApprovalPath)); assert.ok(existsSync(input.templateUsagePath));
    assert.match(input.templateUsagePath, /guided-proposal-readiness-/);
    assert.equal(input.operatorIntent?.mode, "longform"); assert.equal(input.operatorIntent?.scope, "produced");
    assert.deepEqual(retained(root, "gate-plan.json"), proposal.result.candidate);
    const ledger = result.readinessReceipt.deterministicGates as GateLedger;
    assert.deepEqual(ledger.executedChecks, [PROPOSAL_DETERMINISTIC_GATE_CHECK]);
    assert.equal(ledger.pendingChecks.includes(PROPOSAL_DETERMINISTIC_GATE_CHECK), false);
    assert.equal(ledger.pendingChecks.length, PROPOSAL_PENDING_CHECKS.length - 1);
    assert.equal(ledger.hash, canonicalJsonSha256(retained(root, "gate-bundle.json")));
    const draft = readCutPreviewObject(path.join(dir, ".sniper-authority-v1/objects/requests",
      `${result.draftRevision!.requestLedgerHash}.json`)).value;
    assert.equal(draft.schemaVersion, 3);
    assert.deepEqual(draft.executedChecks, [PROPOSAL_DETERMINISTIC_GATE_CHECK]);
    assert.equal((draft.pendingChecks as string[]).includes(PROPOSAL_DETERMINISTIC_GATE_CHECK), false);
    const planFile = path.join(root, "gate-plan.json"), saved = readFileSync(planFile);
    writeFileSync(planFile, "{}");
    assert.throws(() => readGuidedProposalReadiness(dir), /Private readiness object changed/);
    writeFileSync(planFile, saved);
    assert.equal(readGuidedProposalReadiness(dir).deterministicGates.ok, true);
    // A stored receipt written before readiness ran the gates fails closed; it can neither prove
    // nor inherit that evidence, so it is rejected instead of qualifying an unlinted draft.
    const { budgetAdmissionHash, budgetPrecommitHash, deterministicGates, ...old } = result.readinessReceipt;
    void budgetAdmissionHash; void budgetPrecommitHash; void deterministicGates;
    const journal = readFileSync(fixture.jobPath);
    for (const schemaVersion of [1, 2]) {
      const legacy = writeGuidedObject(dir, { ...old, schemaVersion });
      writeFileSync(fixture.jobPath, JSON.stringify({ ...result.job,
        guidedHandoffV2: { ...result.pointer, proposalReadinessHash: legacy } }));
      assert.throws(() => readGuidedProposalReadiness(dir), /predates the deterministic full-plan gates/);
    }
    writeFileSync(fixture.jobPath, journal);
    const gateFile = path.join(root, "gate-bundle.json"), gateBytes = readFileSync(gateFile);
    const currentBundle = retained(root, "gate-bundle.json");
    for (const changed of [{ ...currentBundle, schemaVersion: 1 }, { ...currentBundle, cleanup: "unverified-absence" }]) {
      const hash = writeGuidedObject(dir, changed);
      writeFileSync(gateFile, JSON.stringify(changed));
      const altered = writeGuidedObject(dir, { ...result.readinessReceipt,
        deterministicGates: { ...ledger, hash } });
      writeFileSync(fixture.jobPath, JSON.stringify({ ...result.job,
        guidedHandoffV2: { ...result.pointer, proposalReadinessHash: altered } }));
      assert.throws(() => readGuidedProposalReadiness(dir), /predates owned-process stop proof|all owned gate groups/);
    }
    writeFileSync(gateFile, gateBytes); writeFileSync(fixture.jobPath, journal);
    assert.equal(readGuidedProposalReadiness(dir).deterministicGates.ok, true);
  } finally { fixture.cleanup(); }
});

test("a gate bundle that exhausts the readiness budget is retained as failed, never a partial pass", async () => {
  const fixture = await createGuidedProposalFixture({ output: guidedProposalOutput }), dir = fixture.ctx.dir;
  try {
    const submission = readinessRequest(dir), before = readFileSync(fixture.jobPath);
    let offset = 0;
    const budgetClocks = { wall: () => Date.now() + offset, monotonic: () => performance.now() + offset };
    const gates = stubGateBundle({ before: () => { offset += 21 * 60_000; } });
    await assert.rejects(reviewGuidedTreatmentProposal({ dir, submission }, { gates: gates.run, budgetClocks,
      critic: async () => { throw new Error("an exhausted budget must not pay a critic"); } }), /deadline-exceeded/);
    assert.deepEqual(readFileSync(fixture.jobPath), before);
    assert.equal(readGuidedTreatmentProposal(dir).pointer.proposalReadinessHash, undefined);
    const executions = path.join(dir, "guided-v2-operations", submission.idempotencyKey, "executions");
    const root = path.join(executions, readdirSync(executions)[0]);
    const bundle = retained(root, "gate-bundle.json");
    assert.equal(bundle.overranBudget, true); assert.equal(bundle.remainingMs, 0);
    assert.equal(bundle.ok, false); // the subprocess bundle itself passed; the budget did not
    assert.equal((bundle.verdict as { ok: boolean }).ok, true);
    assert.equal(retained(root, "result.json").state, "failed-or-incomplete");
  } finally { fixture.cleanup(); }
});
