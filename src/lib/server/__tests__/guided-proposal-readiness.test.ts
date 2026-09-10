import assert from "node:assert/strict";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { test } from "node:test";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { parseProposalReadinessReview, assertProposalReviewCoverage } from "@/lib/producer/contracts/proposal-readiness-v1";
import { reviewGuidedTreatmentProposal } from "../guided-proposal-review";
import { readGuidedProposalReadiness } from "../guided-proposal-review-store";
import { readGuidedTreatmentProposal } from "../guided-proposal-store";
import { buildProposalReadinessPacket } from "../guided-proposal-review-packet";
import { assertProposalCriticResult, runProposalReadinessCritic, type ProposalReadinessBrainInput } from "../guided-proposal-review-brain";
import { createGuidedProposalFixture, passingReadinessResult, readinessRequest } from "./_guided-proposal-fixture";
import { passingGateBundle } from "./_readiness-gate-stub";

function untouched(dir: string) {
  for (const name of ["final.mp4", "base.mp4", ".sniper-qc-approved.json", ".sniper-template-usage-approved.json",
    ".sniper-authority-v1/APPROVED_HEAD", ".render-graph-v1/ACTIVE.json"]) assert.equal(existsSync(path.join(dir, name)), false, name);
}

test("two independent critics create actual isolated draft objects, not an accepted head, media or legacy plan approval", async () => {
  const fixture = await createGuidedProposalFixture(), dir = fixture.ctx.dir;
  try {
    const original = readGuidedTreatmentProposal(dir), submission = readinessRequest(dir), plan = readFileSync(fixture.ctx.planPath);
    const active = readFileSync(path.join(dir, ".sniper-authority-v1/ACTIVE_HEAD"));
    let started = 0, release!: () => void;
    const bothStarted = new Promise<void>((resolve) => { release = resolve; }), cwds: string[] = [];
    const result = await reviewGuidedTreatmentProposal({ dir, submission }, { gates: passingGateBundle(), critic: async (input) => {
      cwds.push(input.cwd); started += 1; if (started === 2) release(); await bothStarted;
      assert.deepEqual(input.packet, buildProposalReadinessPacket(original));
      return passingReadinessResult(input);
    } });
    assert.equal(started, 2); assert.equal(new Set(cwds).size, 2); assert.equal(result.readiness.verdict, "clean");
    assert.equal(result.draftRevision!.workflowState, "TREATMENT_DRAFT"); assert.equal(result.available, false);
    assert.equal(result.draftRevision!.parentRevisionHash, original.pointer.pictureLockedRevisionHash);
    assert.equal(result.generationStartedAt, original.generationStartedAt); assert.deepEqual(readFileSync(fixture.ctx.planPath), plan);
    assert.deepEqual(readFileSync(path.join(dir, ".sniper-authority-v1/ACTIVE_HEAD")), active);
    assert.equal(existsSync(path.join(dir, ".sniper-authority-v1/advances", `${original.pointer.pictureLockedRevisionHash}.json`)), false); untouched(dir);
    const graph = readCutPreviewObject(path.join(dir, ".sniper-authority-v1/objects/graphs", `${result.draftRevision!.renderGraphHash}.json`)).value;
    assert.ok((graph.nodes as Array<{ outputArtifactHash: string | null }>).slice(1).every((row) => row.outputArtifactHash === null));
    assert.equal((await reviewGuidedTreatmentProposal({ dir, submission }, { gates: passingGateBundle(), critic: async () => { throw new Error("replay must not pay critic"); } })).replayed, true);
    await assert.rejects(reviewGuidedTreatmentProposal({ dir, submission: { ...submission, idempotencyKey: randomUUID() } }), /Another readiness/);
    for (const [kind, hash] of [["graphs", result.draftRevision!.renderGraphHash], ["requests", result.draftRevision!.requestLedgerHash],
      ["projections", result.draftRevision!.projectionReceiptHash], ["plans", result.draftRevision!.planObjectHash]]) {
      const file = path.join(dir, ".sniper-authority-v1/objects", kind!, `${hash}.json`), saved = readFileSync(file);
      writeFileSync(file, "{}"); assert.throws(() => readGuidedProposalReadiness(dir), /closure changed|object changed/); writeFileSync(file, saved);
    }
  } finally { fixture.cleanup(); }
});

test("critic failure, journal race and orphan receipt retain evidence; one negative independent verdict blocks draft promotion", async () => {
  const fixture = await createGuidedProposalFixture(), dir = fixture.ctx.dir;
  try {
    const submission = readinessRequest(dir), before = readFileSync(fixture.jobPath);
    await assert.rejects(reviewGuidedTreatmentProposal({ dir, submission }, { gates: passingGateBundle(), critic: async (input) => {
      if (input.criticIndex === 0) throw new Error("TEST critic timeout"); return passingReadinessResult(input);
    } }), /critic timeout/);
    assert.deepEqual(readFileSync(fixture.jobPath), before);
    const executions = path.join(dir, "guided-v2-operations", submission.idempotencyKey, "executions");
    const failed = path.join(executions, readdirSync(executions)[0]);
    assert.ok(existsSync(path.join(failed, "critic-1/failure.json"))); assert.ok(existsSync(path.join(failed, "critic-2/result.json")));
    await assert.rejects(reviewGuidedTreatmentProposal({ dir, submission }, { gates: passingGateBundle(), critic: async (input) => {
      const job = JSON.parse(before.toString()); job.message = "TEST concurrent mutation"; writeFileSync(fixture.jobPath, JSON.stringify(job));
      return passingReadinessResult(input);
    } }), /journal changed/); writeFileSync(fixture.jobPath, before);
    const source = JSON.parse(readFileSync(fixture.ctx.manifestPath, "utf8")).sources[1].path as string, sourceBytes = readFileSync(source);
    await assert.rejects(reviewGuidedTreatmentProposal({ dir, submission }, { gates: passingGateBundle(), critic: async (input) => {
      if (input.criticIndex === 0) writeFileSync(source, Buffer.concat([sourceBytes, Buffer.from("TEST unused silent source drift")]));
      return passingReadinessResult(input);
    } }), /cut preview|source|changed/); writeFileSync(source, sourceBytes);
    assert.deepEqual(readFileSync(fixture.jobPath), before);
    await assert.rejects(reviewGuidedTreatmentProposal({ dir, submission }, { gates: passingGateBundle(), verifySources: async ({ lease }) => { lease.release(); },
      critic: async () => { throw new Error("a lost lease must stop before a paid critic"); } }), /lease|ENOENT/);
    await assert.rejects(reviewGuidedTreatmentProposal({ dir, submission }, { gates: passingGateBundle(), timeoutMs: 1,
      verifySources: async () => { throw new Error("expired readiness must not verify sources"); },
      critic: async () => { throw new Error("expired readiness must not pay a critic"); } }), /deadline exceeded/);
    await assert.rejects(reviewGuidedTreatmentProposal({ dir, submission }, { gates: passingGateBundle(), critic: async (input) => passingReadinessResult(input),
      fault: (point) => { if (point === "after-receipt") throw new Error("TEST orphan readiness"); } }), /orphan readiness/);
    assert.deepEqual(readFileSync(fixture.jobPath), before);
    const blocked = await reviewGuidedTreatmentProposal({ dir, submission }, { gates: passingGateBundle(), critic: async (input) => {
      const result = passingReadinessResult(input);
      if (input.criticIndex === 1) result.review = parseProposalReadinessReview({ ...result.review, verdict: "revise",
        materialIssues: [{ code: "UNSUPPORTED_PROMISE", severity: "major", lane: "story", message: "TEST missing payoff", evidence: ["TEST occurrence0"], requiredAction: "Repair the proposal; do not recut." }] });
      return result;
    } });
    assert.equal(blocked.readiness.verdict, "blocked"); assert.equal(blocked.draftRevision, null);
    assert.equal(blocked.job.guidedHandoffV2?.treatmentDraftRevisionHash, undefined); assert.equal(readdirSync(executions).length, 7); untouched(dir);
  } finally { fixture.cleanup(); }
});

test("readiness contract cannot hide clauses, duplicate coverage, name imaginary words, or masquerade as plan QC", () => {
  const proposal = { clauses: [{}], beats: [{ startAnchor: 0, endAnchorExclusive: 1 }] } as Parameters<typeof assertProposalReviewCoverage>[1];
  const evidence = { anchors: [0, 30], occurrences: [[0, 0, 0, 0, 30, "TEST", 0]] } as Parameters<typeof assertProposalReviewCoverage>[2];
  const review = parseProposalReadinessReview({ schemaVersion: 1, stage: "proposal-readiness", verdict: "pass", summary: "TEST ONLY",
    materialIssues: [], findings: [], checks: [{ kind: "clause", index: 0, verdict: "pass", occurrenceIds: [], reason: "TEST" },
      { kind: "beat", index: 0, verdict: "pass", occurrenceIds: [0], reason: "TEST" }] });
  assertProposalReviewCoverage(review, proposal, evidence);
  for (const checks of [review.checks.slice(1), [review.checks[0], review.checks[0]],
    [review.checks[0], { ...review.checks[1], occurrenceIds: [1] }]]) {
    assert.throws(() => assertProposalReviewCoverage({ ...review, checks }, proposal, evidence), /omitted\/duplicated/);
  }
  assert.throws(() => assertProposalReviewCoverage(review, proposal, { ...evidence, anchors: [30, 60] }), /within its own frame range/);
  assert.throws(() => assertProposalReviewCoverage({ ...review, checks: [review.checks[0], { ...review.checks[1], occurrenceIds: [] }] }, proposal, evidence), /within its own frame range/);
  assert.throws(() => parseProposalReadinessReview({ ...review, stage: "plan" }), /scope/);
  assert.throws(() => parseProposalReadinessReview({ ...review, checks: [{ ...review.checks[0], verdict: "issue" }] }), /failed check/);
  assert.throws(() => parseProposalReadinessReview({ ...review, finalApproved: true }), /unsupported fields/);
});

test("readiness critic metadata is closed and uses unchanged independent effort with no session/peer/tools", async () => {
  const input = { packet: { proposal: { clauses: [{}], beats: [{ startAnchor: 0, endAnchorExclusive: 1 }] },
    evidence: { anchors: [0, 30], occurrences: [[0, 0, 0, 0, 30, "TEST", 0]] } },
    criticIndex: 0, ctx: {}, cwd: "/private/tmp", schema: {}, timeoutMs: 1000 } as unknown as ProposalReadinessBrainInput;
  const result = passingReadinessResult(input), binding = { packet: input.packet, criticIndex: 0 };
  assertProposalCriticResult(result, binding);
  for (const patch of [{ criticIndex: 1 }, { packetHash: "a".repeat(64) }, { promptHash: "b".repeat(64) },
    { effort: "low" }, { elapsedMs: NaN }, { extra: true }]) assert.throws(() => assertProposalCriticResult({ ...result, ...patch }, binding), /metadata/);
  const prior = process.env.SNIPER_BRAIN_PROVIDER;
  try {
    process.env.SNIPER_BRAIN_PROVIDER = "codex";
    await runProposalReadinessCritic(input, { codex: async (options) => {
      assert.equal(options.reasoning, "medium"); assert.equal(options.tools, "none"); assert.equal(options.sandbox, "read-only");
      assert.equal(options.schema, "producer-proposal-readiness"); assert.equal(options.maxOutputBytes, 1048576);
      return { message: JSON.stringify(result.review), stderr: "", ms: 1 };
    } });
    process.env.SNIPER_BRAIN_PROVIDER = "legacy";
    await runProposalReadinessCritic(input, { legacy: async (options) => {
      assert.equal(options.args[options.args.indexOf("--tools") + 1], ""); assert.equal(options.args.includes("--resume"), false);
      assert.equal(options.args[options.args.indexOf("--effort") + 1], "xhigh"); assert.equal(options.maxOutputBytes, 1048576);
      return { message: JSON.stringify(result.review), stderr: "", ms: 1 };
    } });
  } finally { if (prior === undefined) delete process.env.SNIPER_BRAIN_PROVIDER; else process.env.SNIPER_BRAIN_PROVIDER = prior; }
});
