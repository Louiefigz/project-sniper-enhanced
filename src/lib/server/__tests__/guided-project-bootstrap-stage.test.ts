/** All provider, source and preview boundaries are TEST stubs; no media/editorial qualification. */
import assert from "node:assert/strict";
import { test, type TestContext } from "node:test";
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { runAuthorStage } from "@/app/api/producer/auto-edit/authoring-stage";
import { runCutReviewLoop, type CutReviewLoopDependencies } from "@/app/api/producer/auto-edit/cut-review-loop";
import { DEFAULT_PIPELINE_DEPENDENCIES } from "@/app/api/producer/auto-edit/pipeline-dependencies";
import { autoEditAuthoritySnapshot, stableAuthorityHash } from "../auto-edit-authority-snapshot";
import { bootstrapStageGuards } from "../guided-project-bootstrap-stage";
import { bootstrapFixture, bootstrapCutRequest, HASH } from "./_guided-project-bootstrap-fixture";
import type { CutApprovalReceipt } from "@/app/api/producer/auto-edit/cut-approval";
import type { ProducerReview } from "@/app/api/producer/auto-edit/review-contract";
import type { AuthoringRuntime } from "@/app/api/producer/auto-edit/authoring-stage";

async function stageFixture(t: TestContext) {
  const f = bootstrapFixture(t), started = await f.start(), events: string[] = [];
  const run: AuthoringRuntime = { job: started.job, io: { send: () => {},
    advance: (change) => (run.job = { ...run.job, ...change }), invalidate: (change) => (run.job = { ...run.job, ...change }) } };
  t.mock.method(bootstrapStageGuards, "current", () => {});
  t.mock.method(bootstrapStageGuards, "quiescent", async () => { events.push("drain"); });
  t.mock.method(bootstrapStageGuards, "compatibility", async () => { events.push("compatibility"); return {} as never; });
  t.mock.method(bootstrapStageGuards, "boundary", async () => { events.push("preview");
    return { status: "awaiting_cut_approval", request: bootstrapCutRequest(run.job), preview: { executionKey: HASH, receiptHash: HASH } }; });
  const deps = { ...DEFAULT_PIPELINE_DEPENDENCIES,
    author: async () => { assert.fail("writer must never run"); },
    validateSavedCut: async () => { assert.fail("saved-plan gate must never run"); },
    approveSavedCut: async () => { assert.fail("saved-plan approval must never run"); },
    validateCut: async () => { events.push("previsual"); return {} as never; },
    approveCut: async () => { events.push("approve-previsual"); return {} as never; },
    reviewCut: async () => { events.push("two-critics"); return {} as never; } };
  return { ...f, ...started, run, events, deps };
}

test("existing candidate dispatch is previsual→two reviews→compatibility→qualified PAUSE, never writer or visuals", async (t) => {
  const f = await stageFixture(t), before = readFileSync(f.run.job.ctx.planPath);
  const result = await runAuthorStage(f.run, f.deps);
  assert.equal(result.status, "awaiting_cut_approval");
  assert.deepEqual(f.events, ["previsual", "drain", "two-critics", "drain", "approve-previsual", "compatibility", "drain", "preview", "drain"]);
  assert.deepEqual(readFileSync(f.run.job.ctx.planPath), before);
  assert.equal(f.run.job.cutAcceptance, undefined); assert.equal(f.run.job.checkpoint, "queued");
});

test("deterministic gate failure precedes every critic and preview; review issue and preview failure stop unchanged", async (t) => {
  const f = await stageFixture(t), before = readFileSync(f.run.job.ctx.planPath);
  for (const stop of ["validateCut", "reviewCut"] as const) {
    const held = f.deps[stop]; f.events.length = 0;
    f.deps[stop] = async () => { throw new Error(`TEST ${stop} blocked`); };
    await assert.rejects(runAuthorStage(f.run, f.deps), /blocked/); f.deps[stop] = held;
    assert.ok(!f.events.includes("preview"));
    if (stop === "validateCut") assert.ok(!f.events.includes("two-critics"));
  }
  t.mock.method(bootstrapStageGuards, "boundary", async () => { throw new Error("TEST preview failed"); });
  await assert.rejects(runAuthorStage(f.run, f.deps), /preview failed/);
  assert.deepEqual(readFileSync(f.run.job.ctx.planPath), before); assert.equal(f.run.job.cutApprovalRequest, undefined);
});

function reviewInputs(f: Awaited<ReturnType<typeof stageFixture>>) {
  const transcript = path.join(f.root, "TEST-words.json");
  writeFileSync(transcript, JSON.stringify({ transcript: [{ start: 0, end: 12, text: "TEST complete sentence.",
    words: [{ word: "TEST", start: 0, end: 4 }, { word: "complete", start: 4, end: 8 }, { word: "sentence.", start: 8, end: 12 }] }] }));
  writeFileSync(f.manifest, JSON.stringify({ sources: [{ id: "TEST-source", duration: 12, transcriptPath: path.basename(transcript) }] }));
  const authority = autoEditAuthoritySnapshot(f.run.job.ctx);
  const gate: CutApprovalReceipt = { schemaVersion: 1, stage: "previsual", planHash: authority.planHash!,
    manifestHash: authority.manifestHash!, transcriptDigest: authority.transcriptDigest,
    cutTrackDigest: stableAuthorityHash(f.plan.cutTrack), cutDecisionsDigest: stableAuthorityHash(f.plan.cutDecisions), cuts: 1, seams: [], removals: [] };
  return { gate, authority };
}

test("actual review loop keeps two independent packets and refuses candidate revision on either critic issue", async (t) => {
  const f = await stageFixture(t), { gate } = reviewInputs(f), before = readFileSync(f.run.job.ctx.planPath);
  const packets: string[] = []; let revise = 0, issues = false;
  const review = (): ProducerReview => ({ schemaVersion: 1, stage: "cut", verdict: issues ? "revise" : "pass",
    summary: "TEST only", findings: [], materialIssues: issues ? [{ code: "TEST_UNRESOLVED", severity: "major", lane: "cuts",
      message: "TEST unresolved", evidence: ["TEST source"], requiredAction: "TEST source review required" }] : [] });
  const dependencies = { gate: async () => gate,
    review: async (input: Parameters<CutReviewLoopDependencies["review"]>[0]) => {
      if (input.stage !== "cut") throw new Error("TEST unexpected review stage");
      packets.push(input.packet!.path); return { provider: "codex" as const, ms: 1, review: review() }; },
    revise: async () => { revise++; throw new Error("TEST forbidden revision"); } };
  const receipt = await runCutReviewLoop(f.run, dependencies);
  assert.equal(receipt.reviews.length, 2); assert.equal(new Set(packets).size, 2); assert.equal(revise, 0);
  issues = true; packets.length = 0;
  await assert.rejects(runCutReviewLoop(f.run, dependencies), /not modified/);
  assert.equal(packets.length, 2); assert.equal(revise, 0); assert.deepEqual(readFileSync(f.run.job.ctx.planPath), before);
});
