import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { createGuidedProposalFixture } from "./_guided-proposal-fixture";
import { guidedProposalOutput } from "./_readiness-gate-stub";
import { revisionRequest } from "./_guided-treatment-revision-fixture";
import { reviseRawTreatment } from "../guided-treatment-revision";
import { readRawTreatmentAdmission } from "../guided-raw-treatment-store";
import { compileGuidedTreatmentProposal } from "../guided-proposal";
import { readGuidedTreatmentProposal } from "../guided-proposal-store";
import { readTreatmentBriefHistory } from "../guided-treatment-revision-history";
import { buildProposalReadinessPacket } from "../guided-proposal-review-packet";

/** Opt-in actual fresh admitted synthetic source/cut preview; TEST critics/compiler, never a creator decision. */
test("fresh cut retains original clock/cut and compiles the new brief with both historical proposals readable", {
  skip: process.env.SNIPER_RUN_TREATMENT_REVISION_INTEGRATION !== "1", timeout: 120_000,
}, async () => {
  const firstText = "Preserve the accepted cut exactly.", rawIntent = "Keep the accepted cut and framing unchanged.";
  const fixture = await createGuidedProposalFixture({ rawIntent: firstText, retainFailure: true });
  let passed = false;
  try {
    const dir = fixture.ctx.dir, prior = readGuidedTreatmentProposal(dir), plan = readFileSync(fixture.ctx.planPath);
    const manifest = readFileSync(fixture.ctx.manifestPath), request = revisionRequest(dir, rawIntent);
    const changed = await reviseRawTreatment({ dir, submission: request }), admitted = readRawTreatmentAdmission(dir);
    assert.equal(changed.generationStartedAt, prior.generationStartedAt); assert.equal(admitted.clock.hash, prior.clock.hash);
    let calls = 0;
    const result = await compileGuidedTreatmentProposal({ dir, submission: { schemaVersion: 1, operation: "compile-post-cut-proposal",
      idempotencyKey: randomUUID(), expectedToken: admitted.job.token, expectedJournalHash: admitted.sha256,
      treatmentAdmissionHash: admitted.pointer.treatmentAdmissionHash } }, { brain: async (input) => {
      calls++; assert.ok(input.prompt.includes(rawIntent));
      return { output: guidedProposalOutput(input, rawIntent), provider: "codex", model: "TEST-ONLY-inert-revision-compiler",
        effort: "xhigh", elapsedMs: 1, promptHash: canonicalJsonSha256(input.prompt) };
    } });
    assert.equal(calls, 1); assert.equal(result.result.blockers.length, 0);
    const packet = buildProposalReadinessPacket(result);
    assert.deepEqual(packet.rawRequest, request); assert.equal(packet.treatmentAdmissionHash, changed.treatmentAdmissionHash);
    assert.equal(packet.clockHash, prior.clock.hash); assert.equal(packet.generationStartedAt, prior.generationStartedAt);
    const history = readTreatmentBriefHistory(dir);
    assert.deepEqual(history.history.map((row) => row.rawIntent), [rawIntent, firstText]);
    assert.equal(history.history[1].proposal!.proposalHash, prior.proposalHash);
    assert.deepEqual(readFileSync(fixture.ctx.planPath), plan); assert.deepEqual(readFileSync(fixture.ctx.manifestPath), manifest);
    assert.equal(canonicalJsonSha256(result.job.ctx), canonicalJsonSha256(prior.job.ctx));
    passed = true;
  } finally { if (passed) fixture.cleanup(); else process.stderr.write(`TEST failed revision integration retained: ${fixture.root}\n`); }
});
