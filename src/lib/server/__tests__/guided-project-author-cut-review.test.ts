/** Real packet/review-loop artifacts; TEST gate/provider/source guard and preview only. */
import assert from "node:assert/strict";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test, type TestContext } from "node:test";
import { runAuthorStage } from "@/app/api/producer/auto-edit/authoring-stage";
import { cutReviewBootstrapGuards, runCutReviewLoop, type CutReviewLoopDependencies } from "@/app/api/producer/auto-edit/cut-review-loop";
import { cutReviewApprovalPath } from "@/app/api/producer/auto-edit/cut-review-approval";
import type { CutApprovalReceipt } from "@/app/api/producer/auto-edit/cut-approval";
import type { ProducerReview } from "@/app/api/producer/auto-edit/review-contract";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import { autoEditAuthoritySnapshot, stableAuthorityHash } from "../auto-edit-authority-snapshot";
import { authoredStageFixture } from "./_guided-project-author-cut-stage-fixture";

function testGate(ctx: AutoEditCtx): CutApprovalReceipt {
  const authority = autoEditAuthoritySnapshot(ctx), plan = JSON.parse(readFileSync(ctx.planPath, "utf8"));
  return { schemaVersion: 1, stage: "previsual", planHash: authority.planHash!, manifestHash: authority.manifestHash!,
    transcriptDigest: authority.transcriptDigest, cutTrackDigest: stableAuthorityHash(plan.cutTrack),
    cutDecisionsDigest: stableAuthorityHash(plan.cutDecisions), cuts: plan.cutTrack.length, seams: [], removals: [] };
}

function testReview(issues: boolean): ProducerReview {
  return { schemaVersion: 1, stage: "cut", verdict: issues ? "revise" : "pass", summary: "TEST source-grounded rationale only",
    findings: [], materialIssues: issues ? [{ code: "TEST_RATIONALE", severity: "major", lane: "cuts",
      message: "TEST explain the kept complete sentence.", evidence: ["TEST complete teaching."],
      requiredAction: "TEST improve only the evidenced cut rationale." }] : [] };
}

function reviewFixture(t: TestContext, mode: "repair" | "defer" | "exhaust") {
  const f = authoredStageFixture(t), packets: string[] = [], counts = { reviews: 0, revisions: 0, guards: 0 };
  const transcriptPath = path.join(f.run.job.ctx.dir, "TEST-words.json");
  writeFileSync(transcriptPath, JSON.stringify({ transcript: [{ start: 0, end: 12, text: "TEST complete teaching.",
    words: [{ word: "TEST", start: 0, end: 4 }, { word: "complete", start: 4, end: 8 }, { word: "teaching.", start: 8, end: 12 }] }] }));
  writeFileSync(f.run.job.ctx.manifestPath, JSON.stringify({ sources: [{ id: "TEST-source", duration: 12,
    transcriptPath: path.basename(transcriptPath) }] }));
  t.mock.method(cutReviewBootstrapGuards, "current", () => { counts.guards++; });
  const deps: Partial<CutReviewLoopDependencies> = { gate: async (ctx) => testGate(ctx),
    review: async (input) => {
      if (input.stage !== "cut") throw new Error("TEST unexpected critic stage");
      packets.push(input.packet!.path); counts.reviews++;
      return { provider: "codex", ms: 1, review: testReview(mode !== "repair" || counts.revisions === 0) };
    },
    revise: async (ctx, review) => {
      counts.revisions++;
      if (mode !== "defer") changeRationale(ctx, counts.revisions);
      return { provider: "codex", ms: 1, receipt: { schemaVersion: 1, changedPlan: mode !== "defer",
        addressedIssueCodes: mode === "defer" ? [] : review.materialIssues.map((issue) => issue.code),
        deferredIssueCodes: mode === "defer" ? review.materialIssues.map((issue) => issue.code) : [],
        summary: "TEST explicit rationale-only correction or source review deferral." } };
    } };
  f.deps.reviewCut = async (run) => runCutReviewLoop(run, deps);
  return { ...f, packets, counts };
}

/** A changed rationale is a real cut-identity change; no source words or timing are invented. */
function changeRationale(ctx: AutoEditCtx, revision: number): void {
  const plan = JSON.parse(readFileSync(ctx.planPath, "utf8"));
  plan.planVersion++; plan.cutTrack[0].rationale = `TEST complete teaching retained after review ${revision}.`;
  writeFileSync(ctx.planPath, JSON.stringify(plan));
}

test("authored cut runs actual independent critic packets, permits evidenced revision, then two new clean reviews", async (t) => {
  const f = reviewFixture(t, "repair");
  assert.equal((await runAuthorStage(f.run, f.deps)).status, "awaiting_cut_approval");
  assert.equal(f.counts.reviews, 4); assert.equal(f.counts.revisions, 1); assert.ok(f.counts.guards >= 5);
  assert.equal(new Set(f.packets).size, 4);
  const packets = f.packets.map((file) => JSON.parse(readFileSync(file, "utf8")));
  assert.equal(packets[0].inputAuthority.digest, packets[1].inputAuthority.digest);
  assert.equal(packets[2].inputAuthority.digest, packets[3].inputAuthority.digest);
  assert.notEqual(packets[0].inputAuthority.digest, packets[2].inputAuthority.digest);
  const receipt = JSON.parse(readFileSync(cutReviewApprovalPath(f.run.job.ctx), "utf8"));
  assert.deepEqual(receipt.reviews.map((item: { round: number }) => item.round), [3, 4]);
  assert.equal(f.calls.filter((call) => call.startsWith("writer:")).length, 1);
  assert.equal(f.run.job.cutAcceptance, undefined); assert.equal(f.run.job.guidedHandoffV2, undefined);
});

test("authored source-review deferral preserves the existing one-recheck no-progress stop", async (t) => {
  const f = reviewFixture(t, "defer");
  await assert.rejects(runAuthorStage(f.run, f.deps), /conflict repeated for unchanged deterministic cut/);
  assert.equal(f.counts.reviews, 4); assert.equal(f.counts.revisions, 1);
  assert.equal(f.calls.includes("preview"), false); assert.equal(existsSync(cutReviewApprovalPath(f.run.job.ctx)), false);
  assert.deepEqual(JSON.parse(readFileSync(f.run.job.ctx.planPath, "utf8")), f.draft);
});

test("authored repeated changed but unresolved cuts retain the original six-critic ceiling", async (t) => {
  const f = reviewFixture(t, "exhaust");
  await assert.rejects(runAuthorStage(f.run, f.deps), /cut review exhausted 6 rounds/);
  assert.equal(f.counts.reviews, 6); assert.equal(f.counts.revisions, 2);
  assert.equal(f.calls.includes("approve-previsual"), false); assert.equal(f.calls.includes("preview"), false);
  assert.equal(existsSync(cutReviewApprovalPath(f.run.job.ctx)), false);
});
