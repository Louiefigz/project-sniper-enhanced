import assert from "node:assert/strict";
import path from "node:path";
import { test } from "node:test";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { SCRIPTS_DIR } from "@/app/api/_lib/spawn-python";
import { parsePlanningGateVerdict, spawnPlanningGate } from "@/app/api/producer/auto-edit/planning-gates";
import { reviewGuidedTreatmentProposal } from "../guided-proposal-review";
import { createGuidedProposalFixture, passingReadinessResult, readinessRequest } from "./_guided-proposal-fixture";
import { guidedProposalOutput } from "./_readiness-gate-stub";

interface Finding { gate: string; message: string }

/** Runs the REAL Python gate bundle (no Docker, no stubbed runner). It is the negative proof
 * that an unlintable treatment draft now stops at readiness instead of burning a 25-minute
 * opening attempt at plan_lint. Critics are stubbed only to prove they are never reached. */
test("REAL deterministic gate bundle blocks the default synthetic program at readiness", async () => {
  const began = Date.now();
  const fixture = await createGuidedProposalFixture({ output: guidedProposalOutput }), dir = fixture.ctx.dir;
  try {
    const submission = readinessRequest(dir);
    let critics = 0;
    const gateStart = Date.now();
    const result = await reviewGuidedTreatmentProposal({ dir, submission },
      { critic: async (input) => { critics += 1; return passingReadinessResult(input); } });
    const readinessMs = Date.now() - gateStart;
    assert.equal(critics, 0, "a blocked deterministic bundle must not pay an independent critic");
    assert.equal(result.deterministicGates.ok, false);
    assert.equal(result.readiness.verdict, "blocked");
    assert.equal(result.draftRevision, null);
    assert.equal(result.job.guidedHandoffV2?.treatmentDraftRevisionHash, undefined);
    const root = path.join(dir, "guided-v2-operations", submission.idempotencyKey,
      "executions", String(result.readinessReceipt.executionId));
    const bundle = readCutPreviewObject(path.join(root, "gate-bundle.json")).value;
    const verdict = bundle.verdict as { ok: boolean; errors: Finding[] };
    const findings = verdict.errors.map((item) => `${item.gate}: ${item.message}`);
    process.stderr.write(`REAL GATE BUNDLE (readiness ${readinessMs}ms, total ${Date.now() - began}ms)\n`
      + `${findings.slice(0, 10).join("\n")}\n`);
    assert.equal(verdict.ok, false);
    assert.ok(findings.length > 0, "a blocked bundle must carry diagnostics");
    assert.equal(bundle.overranBudget, false);

    // runPlanningGateBundle stops the downstream gates when the operator_intent/transcript_cut
    // preflight fails, so plan_lint's own verdict is captured directly on the SAME retained
    // candidate plan. That is the evidence that this draft could never have survived a render.
    const lint = parsePlanningGateVerdict("plan_lint", await spawnPlanningGate({ gate: "plan_lint",
      script: path.join(SCRIPTS_DIR, "producer", "plan_lint.py"),
      args: [path.join(root, "gate-plan.json"), fixture.ctx.manifestPath, fixture.ctx.transcriptsDir] }));
    process.stderr.write(`REAL plan_lint ON THE SAME RETAINED CANDIDATE\n${lint.errors.join("\n")}\n`);
    assert.equal(lint.ok, false);
    assert.ok(lint.errors.some((message) => message.includes("below mode floor")),
      `plan_lint should reject the 3s program: ${lint.errors.join(" | ")}`);
  } finally { fixture.cleanup(); }
});
