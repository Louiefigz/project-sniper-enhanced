import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { parseGuidedWorkflowV2, parseGuidedCutSubmissionV2 } from "@/lib/producer/contracts/guided-workflow-v2";
import { parseRawTreatmentSubmissionV1, parseTreatmentCompileSubmissionV1 } from "@/lib/producer/contracts/raw-treatment-v1";
import { createHumanCutFixture } from "./_human-cut-fixture";
import { acceptGuidedCutV2, readGuidedCutV2 } from "../guided-cut-v2";
import { admitRawTreatment } from "../guided-raw-treatment";
import { readRawTreatmentAdmission } from "../guided-raw-treatment-store";
import { compileGuidedTreatmentProposal } from "../guided-proposal";
import { readGuidedTreatmentProposal } from "../guided-proposal-store";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { writeGuidedObject, readGuidedObject } from "../guided-cut-v2-store";
import type { ProposalBrainInput } from "../guided-proposal-compiler";
import { guidedProposalOutput } from "./_readiness-gate-stub";
import { CURRENT_TREATMENT_PROPOSAL_VERSION } from "@/lib/producer/contracts/treatment-proposal-v5";

const workflow = parseGuidedWorkflowV2({ schemaVersion: 2, mode: "guided", afterCut: "treatment-then-intro", approvalPolicy: "explicit-human" });
type Fixture = Awaited<ReturnType<typeof createHumanCutFixture>>;
const raw = "Preserve the accepted cut exactly.";

async function acceptedFixture() {
  const fixture = await createHumanCutFixture({ workflowV2: workflow }), observed = observeHumanCutJob(fixture.ctx.dir);
  const { attestation: _old, ...base } = fixture.submission; void _old;
  const decision = parseGuidedCutSubmissionV2({ ...base, schemaVersion: 2, operation: "accept-cut-await-treatment",
    expectedJournalHash: observed.sha256, attestation: { watched: true, listened: true, acceptsExactCut: true, understandsTreatmentPending: true } });
  try { await acceptGuidedCutV2({ dir: fixture.ctx.dir, submission: decision }); return fixture; }
  catch (error) { fixture.cleanup(); throw error; }
}
function intake(fixture: Fixture, rawIntent = raw) {
  const cut = readGuidedCutV2(fixture.ctx.dir);
  return parseRawTreatmentSubmissionV1({ schemaVersion: 1, operation: "propose-post-cut-treatment", requestId: randomUUID(), idempotencyKey: randomUUID(),
    expectedToken: cut.job.token, expectedJournalHash: cut.sha256, cutDecisionHash: cut.pointer.cutDecisionHash,
    parentRevisionHash: cut.pointer.pictureLockedRevisionHash, rawIntent });
}
function compileRequest(fixture: Fixture) {
  const cut = readRawTreatmentAdmission(fixture.ctx.dir);
  return parseTreatmentCompileSubmissionV1({ schemaVersion: 1, operation: "compile-post-cut-proposal", idempotencyKey: randomUUID(),
    expectedToken: cut.job.token, expectedJournalHash: cut.sha256, treatmentAdmissionHash: cut.pointer.treatmentAdmissionHash });
}
function brain(output?: unknown) {
  return async (input: ProposalBrainInput) => {
    assert.ok(input.timeoutMs > 0 && input.timeoutMs < 600_000, "preparation consumes the existing provider ceiling");
    return { output: output ?? guidedProposalOutput(input, raw), provider: "codex" as const,
      model: "TEST-ONLY-synthetic-provider", effort: "xhigh" as const, elapsedMs: 1, promptHash: canonicalJsonSha256(input.prompt) }; };
}
function noPromotion(fixture: Fixture) {
  for (const name of ["final.mp4", "base.mp4", ".sniper-qc-approved.json", ".sniper-template-usage-approved.json", ".sniper-authority-v1/APPROVED_HEAD", ".render-graph-v1/ACTIVE.json"]) {
    assert.equal(existsSync(path.join(fixture.ctx.dir, name)), false, name);
  }
}

test("raw request and actual pinned advisors compile one private unapproved proposal without mutating the accepted root", async () => {
  const fixture = await acceptedFixture();
  try {
    const before = readFileSync(fixture.ctx.planPath), ctx = canonicalJsonSha256(fixture.ctx), request = intake(fixture);
    assert.equal(existsSync(path.join(fixture.ctx.dir, "guided-v2-operations", `generation-${request.cutDecisionHash}.json`)), false);
    await assert.rejects(admitRawTreatment({ dir: fixture.ctx.dir, submission: { ...request, attestation: true } }));
    const admitted = await admitRawTreatment({ dir: fixture.ctx.dir, submission: request });
    const compile = compileRequest(fixture), result = await compileGuidedTreatmentProposal({ dir: fixture.ctx.dir, submission: compile }, { brain: brain() });
    assert.equal(result.available, false); assert.equal(result.receipt.executable, false); assert.equal(result.receipt.independentReview, "not-run");
    assert.equal(result.generationStartedAt, admitted.generationStartedAt); assert.equal(result.result.blockers.length, 0);
    assert.equal(result.receipt.schemaVersion, 2);
    assert.equal(readGuidedObject(fixture.ctx.dir, String(result.receipt.budgetAdmissionHash)).clockHash,
      readRawTreatmentAdmission(fixture.ctx.dir).clock.hash);
    assert.equal(result.result.candidate!.baselineLook, undefined);
    assert.equal(result.result.range!.approval.endFrameExclusive, fixture.receipt.media.videoFrames);
    assert.deepEqual(result.evidence.catalog.map((row) => row.kind).sort(), ["chart-story", "ui-focus-zoom"]);
    assert.ok(result.evidence.catalog.every((row) => row.canvas.join(",") === "1920,1080"));
    assert.ok(result.evidence.graphicsAdvice["graphics_planner.py"]);
    assert.equal((await compileGuidedTreatmentProposal({ dir: fixture.ctx.dir, submission: compile }, { brain: async () => { throw new Error("replay must not call model"); } })).replayed, true);
    await assert.rejects(compileGuidedTreatmentProposal({ dir: fixture.ctx.dir, submission: { ...compile, idempotencyKey: randomUUID() } }), /different proposal/);
    assert.deepEqual(readFileSync(fixture.ctx.planPath), before); assert.equal(canonicalJsonSha256(fixture.ctx), ctx); noPromotion(fixture);
    const proofPath = path.join(fixture.ctx.dir, ".sniper-authority-v1/objects/receipts", `${result.receipt.candidateResultHash}.json`);
    const bytes = readFileSync(proofPath); writeFileSync(proofPath, "{}");
    assert.throws(() => readGuidedTreatmentProposal(fixture.ctx.dir), /object changed/); writeFileSync(proofPath, bytes);
    const journal = readFileSync(fixture.jobPath), poisoned = JSON.parse(journal.toString());
    const forged = { ...readGuidedObject(fixture.ctx.dir, result.proposalHash), executionId: "../../escape" };
    poisoned.guidedHandoffV2.treatmentProposalHash = writeGuidedObject(fixture.ctx.dir, forged);
    writeFileSync(fixture.jobPath, JSON.stringify(poisoned)); assert.throws(() => readGuidedTreatmentProposal(fixture.ctx.dir), /executionId/);
    writeFileSync(fixture.jobPath, journal);
  } finally { fixture.cleanup(); }
});

test("expired original generation allowance stops a retry before source verification or provider work", async () => {
  const fixture = await acceptedFixture();
  try {
    await admitRawTreatment({ dir: fixture.ctx.dir, submission: intake(fixture) });
    const admitted = readRawTreatmentAdmission(fixture.ctx.dir), compile = compileRequest(fixture);
    const before = readFileSync(fixture.jobPath), wall = Date.parse(admitted.generationStartedAt) + 31 * 60_000;
    await assert.rejects(compileGuidedTreatmentProposal({ dir: fixture.ctx.dir, submission: compile }, {
      budgetClocks: { wall: () => wall, monotonic: () => 0 },
      verifySources: async () => { throw new Error("must not verify after budget refusal"); },
      brain: async () => { throw new Error("must not pay provider after budget refusal"); },
    }), /budget not-admitted/);
    const executions = path.join(fixture.ctx.dir, "guided-v2-operations", compile.idempotencyKey, "executions");
    const attempt = path.join(executions, readdirSync(executions)[0]);
    const retained = JSON.parse(readFileSync(path.join(attempt, "budget-admission.json"), "utf8"));
    const outcome = JSON.parse(readFileSync(path.join(attempt, "result.json"), "utf8"));
    assert.equal(retained.generationStartedAt, admitted.generationStartedAt);
    assert.equal(retained.admitted, false); assert.equal(outcome.budget.state, "not-admitted");
    assert.deepEqual(readFileSync(fixture.jobPath), before); noPromotion(fixture);
  } finally { fixture.cleanup(); }
});

test("a provider completing after the whole-attempt ceiling keeps its result but cannot publish a proposal", async () => {
  const fixture = await acceptedFixture();
  try {
    await admitRawTreatment({ dir: fixture.ctx.dir, submission: intake(fixture) });
    const compile = compileRequest(fixture), before = readFileSync(fixture.jobPath);
    let wall = Date.now(), mono = 0;
    await assert.rejects(compileGuidedTreatmentProposal({ dir: fixture.ctx.dir, submission: compile }, {
      budgetClocks: { wall: () => wall, monotonic: () => mono },
      brain: async (input) => { const result = await brain()(input); wall += 11 * 60_000; mono += 11 * 60_000; return result; },
      verifySources: async () => { wall += 1; mono += 1; },
    }), /budget deadline-exceeded/);
    const executions = path.join(fixture.ctx.dir, "guided-v2-operations", compile.idempotencyKey, "executions");
    const attempt = path.join(executions, readdirSync(executions)[0]);
    assert.ok(existsSync(path.join(attempt, "compiler-result.json")));
    assert.equal(existsSync(path.join(attempt, "budget-precommit.json")), false);
    assert.equal(JSON.parse(readFileSync(path.join(attempt, "result.json"), "utf8")).budget.state, "deadline-exceeded");
    assert.deepEqual(readFileSync(fixture.jobPath), before); noPromotion(fixture);
  } finally { fixture.cleanup(); }
});

test("a late receipt or rollback cannot cross the final synchronous proposal commit guard", async () => {
  for (const fault of ["expired", "rollback"] as const) {
    const fixture = await acceptedFixture();
    try {
      await admitRawTreatment({ dir: fixture.ctx.dir, submission: intake(fixture) });
      const compile = compileRequest(fixture), before = readFileSync(fixture.jobPath);
      let wall = Date.now(), mono = 0;
      let reachedReceipt = false;
      await assert.rejects(compileGuidedTreatmentProposal({ dir: fixture.ctx.dir, submission: compile }, {
        budgetClocks: { wall: () => wall, monotonic: () => mono },
        brain: brain(), verifySources: async () => { wall += 1; mono += 1; },
        fault: (point) => {
          if (point !== "after-receipt") return;
          reachedReceipt = true;
          wall += fault === "expired" ? 11 * 60_000 : -1;
          mono += fault === "expired" ? 11 * 60_000 : 0;
        },
      }), fault === "expired" ? /deadline-exceeded/ : /clock-invalid/);
      assert.equal(reachedReceipt, true, "each independent case must reach the actual final commit boundary");
      assert.deepEqual(readFileSync(fixture.jobPath), before); noPromotion(fixture);
    } finally { fixture.cleanup(); }
  }
});

test("a late provider exception cannot recover known elapsed time on the next explicit retry", async () => {
  const fixture = await acceptedFixture();
  try {
    await admitRawTreatment({ dir: fixture.ctx.dir, submission: intake(fixture) });
    const compile = compileRequest(fixture), before = readFileSync(fixture.jobPath), start = Date.now();
    let wall = start, mono = 0;
    await assert.rejects(compileGuidedTreatmentProposal({ dir: fixture.ctx.dir, submission: compile }, {
      budgetClocks: { wall: () => wall, monotonic: () => mono }, verifySources: async () => {},
      brain: async () => { wall += 9 * 60_000; mono += 9 * 60_000; throw new Error("TEST late provider exception"); },
    }), /late provider exception/);
    const executions = path.join(fixture.ctx.dir, "guided-v2-operations", compile.idempotencyKey, "executions");
    const result = JSON.parse(readFileSync(path.join(executions, readdirSync(executions)[0], "result.json"), "utf8"));
    assert.equal(result.budget.elapsedMs, 9 * 60_000);
    wall = start + 2 * 60_000; mono = 0;
    await assert.rejects(compileGuidedTreatmentProposal({ dir: fixture.ctx.dir, submission: compile }, {
      budgetClocks: { wall: () => wall, monotonic: () => mono },
      verifySources: async () => { throw new Error("must stop before verifying retry"); },
      brain: async () => { throw new Error("must stop before paying retry"); },
    }), /clock-invalid.*across attempts/);
    assert.deepEqual(readFileSync(fixture.jobPath), before); noPromotion(fixture);
  } finally { fixture.cleanup(); }
});

test("provider/CAS/lease failures retain the first raw clock and failed execution; exact explicit retry cannot become a fresh brief", async () => {
  const fixture = await acceptedFixture();
  try {
    const request = intake(fixture); await admitRawTreatment({ dir: fixture.ctx.dir, submission: request });
    const first = readRawTreatmentAdmission(fixture.ctx.dir).generationStartedAt, compile = compileRequest(fixture), before = readFileSync(fixture.jobPath);
    await assert.rejects(compileGuidedTreatmentProposal({ dir: fixture.ctx.dir, submission: compile }, { brain: async () => { throw new Error("TEST provider timeout"); } }), /provider timeout/);
    assert.deepEqual(readFileSync(fixture.jobPath), before);
    const executions = path.join(fixture.ctx.dir, "guided-v2-operations", compile.idempotencyKey, "executions");
    assert.equal(JSON.parse(readFileSync(path.join(executions, readdirSync(executions)[0], "result.json"), "utf8")).state, "failed-or-incomplete");
    await assert.rejects(compileGuidedTreatmentProposal({ dir: fixture.ctx.dir, submission: compile }, {
      brain: brain(), verifySources: async ({ lease }) => { lease.release(); },
    }), /lease|ENOENT/);
    assert.deepEqual(readFileSync(fixture.jobPath), before);
    await assert.rejects(compileGuidedTreatmentProposal({ dir: fixture.ctx.dir, submission: compile }, { brain: async (input) => {
      const job = JSON.parse(before.toString()); job.message = "TEST concurrent writer"; writeFileSync(fixture.jobPath, JSON.stringify(job)); return brain()(input);
    } }), /journal changed/);
    writeFileSync(fixture.jobPath, before);
    await assert.rejects(compileGuidedTreatmentProposal({ dir: fixture.ctx.dir, submission: compile }, { brain: brain(),
      fault: (point) => { if (point === "after-receipt") throw new Error("TEST orphan fact"); } }), /orphan fact/);
    assert.deepEqual(readFileSync(fixture.jobPath), before);
    const result = await compileGuidedTreatmentProposal({ dir: fixture.ctx.dir, submission: compile }, { brain: brain() });
    assert.equal(result.generationStartedAt, first); assert.equal(readdirSync(executions).length, 5); noPromotion(fixture);
  } finally { fixture.cleanup(); }
});

test("unsupported natural-language clauses remain a blocking proposal, not falsely fulfilled controls", async () => {
  const fixture = await acceptedFixture();
  try {
    const text = "Add punchy music, captions, and move my conclusion first.", request = intake(fixture, text);
    await admitRawTreatment({ dir: fixture.ctx.dir, submission: request });
    const output = { schemaVersion: CURRENT_TREATMENT_PROPOSAL_VERSION, summary: "TEST ONLY unresolved raw request.",
      graphicsStyle: "catalog-first", graphicsStyleRationale: "TEST ONLY grammar choice; it asserts no creative or renderer quality.",
      clauses: [{ start: 0, end: text.length, quote: text, disposition: "cut-affecting", rationale: "The cut-order change and unimplemented music require resolution; a caption preset cannot satisfy the whole clause.", operationIndices: [] }],
      beats: [], operations: [], beatDecisions: [], hookSeamDecisions: [],
      openingEndAnchor: null, continuityEndAnchor: null, audioPolicy: "preserve-full-program", colorPolicy: "preserve" };
    const result = await compileGuidedTreatmentProposal({ dir: fixture.ctx.dir, submission: compileRequest(fixture) }, { brain: brain(output) });
    assert.equal(result.result.candidate, null); assert.equal(result.result.blockers.length, 1); assert.equal(result.submission.rawIntent, text);
    assert.equal(result.job.status, "treatment_admitted"); assert.equal(result.job.workerPid, undefined); noPromotion(fixture);
  } finally { fixture.cleanup(); }
});
