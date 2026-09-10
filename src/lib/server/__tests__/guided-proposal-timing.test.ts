import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { createGuidedProposalFixture, passingReadinessResult, readinessRequest } from "./_guided-proposal-fixture";
import { passingGateBundle } from "./_readiness-gate-stub";
import { readGuidedTreatmentProposal } from "../guided-proposal-store";
import { reviewGuidedTreatmentProposal } from "../guided-proposal-review";
import { stageTimingsPath } from "../stage-timing";

test("actual source verification belongs to each immutable proposal/readiness execution, not merely its job token", async () => {
  const fixture = await createGuidedProposalFixture(), dir = fixture.ctx.dir;
  try {
    const proposal = readGuidedTreatmentProposal(dir);
    const readiness = await reviewGuidedTreatmentProposal({ dir, submission: readinessRequest(dir) }, {
      gates: passingGateBundle(), critic: async (input) => passingReadinessResult(input),
    });
    const rows = readFileSync(stageTimingsPath(dir), "utf8").trim().split("\n")
      .map((line) => JSON.parse(line) as Record<string, unknown>);
    for (const [stage, execution] of [["guided_full_program_proposal", `proposal:${proposal.receipt.executionId}`],
      ["guided_proposal_readiness", `proposal-readiness:${readiness.readinessReceipt.executionId}`]]) {
      const root = rows.find((row) => row.stage === stage && row.event === "start"); assert.ok(root);
      assert.equal(root.attemptId, execution); assert.notEqual(root.attemptId, proposal.job.token);
      const verifications = rows.filter((row) => row.stage === "cut_preview_source_reobservation"
        && row.event === "start" && row.parentSpanId === root.spanId);
      assert.equal(verifications.length, 2);
      assert.ok(verifications.every((row) => row.attemptId === root.attemptId && row.runId === root.runId));
    }
  } finally { fixture.cleanup(); }
});
