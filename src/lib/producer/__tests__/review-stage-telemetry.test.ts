import { frameLabel } from "../../../app/api/producer/auto-edit/rendered-review-attachments";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ProjectTimingDetails from "@/components/producer/project-timing-details";
import { runProducerReview, type ProducerReviewRequest } from "@/app/api/producer/auto-edit/brain-review-runner";
import { buildRenderedReviewPrompt } from "@/app/api/producer/auto-edit/rendered-review-prompt";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import { captureAutoEditDoctrine } from "@/lib/server/auto-edit-doctrine";
import { freshJob } from "@/lib/server/auto-edit-job-builders";
import { stageTimingsPath } from "@/lib/server/stage-timing";
import { withStageTimingContext } from "@/lib/server/stage-timing-context";
import { summarizeJobTimings } from "@/lib/server/stage-timing-summary";

interface Row { stage: string; event: string; spanId: string; parentSpanId?: string; status?: string;
  elapsedMs?: number; metadata: Record<string, unknown> }
const message = JSON.stringify({ schemaVersion: 1, stage: "rendered", verdict: "revise",
  summary: "TEST ONLY: stub critic, no pixels reviewed", findings: [], materialIssues: [{
    code: "TEST_REPAIR", severity: "major", lane: "graphics", message: "Test only defect",
    evidence: ["synthetic-frame"], requiredAction: "Test only change",
  }] });
const lineage = { runId: "test-run", attemptId: "test-run", attemptNo: 1 };

async function fixture(run: (ctx: AutoEditCtx) => Promise<void>): Promise<void> {
  const dir = mkdtempSync(path.join(os.tmpdir(), "sniper-review-telemetry-"));
  const base: AutoEditCtx = { dir, scope: "produced", planPath: path.join(dir, "edit_plan.json"),
    manifestPath: path.join(dir, "asset_manifest.json"), transcriptsDir: dir, deliveryPolicy: "mp4-only" };
  writeFileSync(base.planPath, JSON.stringify({ planVersion: 1, cutTrack: [] }));
  try {
    const ctx = { ...base, doctrine: captureAutoEditDoctrine(base, "test-only", process.cwd()) };
    await withStageTimingContext(lineage, () => run(ctx));
  } finally { rmSync(dir, { recursive: true, force: true }); }
}

function request(ctx: AutoEditCtx): Extract<ProducerReviewRequest, { stage: "rendered" }> {
  const frames = [path.join(ctx.dir, "TEST-ONLY-one.png"), path.join(ctx.dir, "TEST-ONLY-two.png")];
  for (const frame of frames) writeFileSync(frame, Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64"));
  writeFileSync(path.join(ctx.dir, "TEST-ONLY.json"), JSON.stringify({ frames: frames.map((frame) => ({ path: frame })) }));
  return { stage: "rendered", ctx, round: 2, lens: "editorial",
    evidence: { auditReportPath: path.join(ctx.dir, "TEST-ONLY.json"), framePaths: frames } };
}

function attachments(req: Extract<ProducerReviewRequest, { stage: "rendered" }>) {
  return { frames: req.evidence.framePaths.map((frame, index) => ({ path: frame, labels: [`#${index + 1} ${frameLabel(frame)}`] })),
    reference: [] };
}

function rows(ctx: AutoEditCtx): Row[] {
  return readFileSync(stageTimingsPath(ctx.dir), "utf8").trim().split("\n").map((line) => JSON.parse(line));
}

for (const provider of ["codex", "legacy"] as const) {
  test(`${provider}: exact prompt/policy preserved; negative verdict is not execution failure`, () => fixture(async (ctx) => {
    const req = request(ctx), expected = buildRenderedReviewPrompt(ctx, req.evidence, req.round, req.lens!, attachments(req));
    let observed = "";
    const result = await runProducerReview(req, { provider: () => provider,
      codex: async (options) => {
        observed = options.prompt;
        assert.equal(options.reasoning, "medium"); assert.equal(options.sandbox, "read-only");
        return { message, ms: 99_999, stderr: "PRIVATE-STDERR" };
      }, legacy: async (invocation) => {
        observed = (JSON.parse(invocation.stdin!) as { message: { content: Array<{ text?: string }> } }).message.content[0].text!;
        assert.equal(invocation.args[invocation.args.indexOf("--effort") + 1], "xhigh");
        return { message, ms: 99_999, stderr: "PRIVATE-STDERR" };
      } });
    assert.equal(observed, expected); assert.equal(result.review.verdict, "revise");
    const log = rows(ctx), parent = log.find((row) => row.stage === "critic_rendered" && row.event === "start")!;
    assert.deepEqual(log.filter((row) => row.event === "end").map((row) => row.stage), [
      "critic_rendered_prepare", "critic_rendered_provider", "critic_rendered_result_check", "critic_rendered"]);
    assert.ok(log.filter((row) => row.stage !== "critic_rendered").every((row) => row.parentSpanId === parent.spanId));
    assert.ok(log.filter((row) => row.event === "end").every((row) => row.status === "completed"));
    const engine = log.find((row) => row.stage === "critic_rendered_provider" && row.event === "end")!;
    assert.equal(engine.metadata.promptBytes, Buffer.byteLength(expected, "utf8"));
    assert.equal(engine.metadata.evidenceImages, 2); assert.equal(engine.metadata.lens, "editorial");
    assert.notEqual(engine.elapsedMs, 99_999, "journal measures real elapsed time, not returned provider ms");
    assert.ok(!JSON.stringify(log).includes("PRIVATE-STDERR"));
    assert.ok(!JSON.stringify(log).includes("TEST-ONLY-one.png"));
    const job = freshJob({ ctx, token: lineage.runId, snapshots: 0 }, new Date().toISOString());
    const report = summarizeJobTimings(readFileSync(stageTimingsPath(ctx.dir), "utf8"), job);
    const html = renderToStaticMarkup(createElement(ProjectTimingDetails, { report }));
    assert.match(html, /Largest prompt/); assert.match(html, /1\/1 calls measured/);
    assert.match(html, /Hard process ceiling: 25m 0s/); assert.match(html, /does not mean QC passed/);
  }));
}

test("provider error retains failed child and parent, without starting result checks", () => fixture(async (ctx) => {
  await assert.rejects(runProducerReview(request(ctx), { provider: () => "codex",
    codex: async () => { throw new Error("PRIVATE-PROVIDER-ERROR"); } }), /PRIVATE-PROVIDER-ERROR/);
  const log = rows(ctx);
  assert.deepEqual(log.filter((row) => row.status === "failed").map((row) => row.stage),
    ["critic_rendered_provider", "critic_rendered"]);
  assert.ok(!log.some((row) => row.stage === "critic_rendered_result_check"));
  assert.ok(!JSON.stringify(log).includes("PRIVATE-PROVIDER-ERROR"));
}));

test("malformed critic output is a result-check failure, not a passing critic", () => fixture(async (ctx) => {
  await assert.rejects(runProducerReview(request(ctx), { provider: () => "codex",
    codex: async () => ({ message: "malformed", ms: 1, stderr: "" }) }));
  assert.deepEqual(rows(ctx).filter((row) => row.status === "failed").map((row) => row.stage),
    ["critic_rendered_result_check", "critic_rendered"]);
}));

test("missing evidence authority fails in measured preparation, before provider expense", () => fixture(async (ctx) => {
  let called = false;
  const missing: ProducerReviewRequest = { stage: "plan", ctx: { ...ctx, doctrine: undefined }, round: 1,
    packet: { path: path.join(ctx.dir, "missing.json"), hash: "0".repeat(64), contentDigest: "1".repeat(64),
      authorityDigest: "2".repeat(64), gateDigest: "3".repeat(64), round: 1 } };
  await assert.rejects(runProducerReview(missing, { provider: () => "codex",
    codex: async () => { called = true; return { message, ms: 1, stderr: "" }; } }));
  assert.equal(called, false);
  assert.deepEqual(rows(ctx).filter((row) => row.status === "failed").map((row) => row.stage),
    ["critic_plan_prepare", "critic_plan"]);
}));
