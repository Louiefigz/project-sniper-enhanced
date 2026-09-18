/** TEST metadata and fake provider only; all source/media/gate boundaries are explicit stubs. */
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import type { TestContext } from "node:test";
import type { AuthoringResult } from "@/app/api/producer/auto-edit/authoring";
import type { AuthoringRuntime, AuthoringStageDependencies } from "@/app/api/producer/auto-edit/authoring-stage";
import { authoringWriterGuards } from "@/app/api/producer/auto-edit/authoring-writer";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import { DEFAULT_PIPELINE_DEPENDENCIES } from "@/app/api/producer/auto-edit/pipeline-dependencies";
import { canonicalJsonSha256, fileSha256 } from "../auto-edit-hash";
import { planContentHash } from "../auto-edit-authority";
import { freshJob } from "../auto-edit-job-builders";
import { authoredCutStageGuards } from "../guided-project-author-cut-stage";
import { parseAuthorCutRequest } from "../guided-project-bootstrap-contract";
import { authoredCutSeed } from "../guided-project-bootstrap-inputs";

const HASH = "a".repeat(64);
export const SUCCESS: AuthoringResult = { code: 0, timedOut: false, errTail: "", ms: 1,
  provider: "codex", authored: null, sessionEstablished: true };

/** A real file hash/content hash is used; this is not a pinned source authority. */
function testAuthority(ctx: AutoEditCtx) {
  return { schemaVersion: 1 as const, qualityPolicyVersion: 1 as const,
    digest: HASH, planHash: fileSha256(ctx.planPath) ?? null,
    planContentHash: planContentHash(ctx.planPath) ?? null, manifestHash: HASH,
    operatorIntentDigest: HASH, transcriptDigest: HASH, referenceDigest: HASH, pipelineDigest: HASH };
}

function fakePause(run: AuthoringRuntime) {
  const core = { schemaVersion: 1 as const, requestKey: run.job.requestKey,
    planHash: fileSha256(run.job.ctx.planPath)!, authorityDigest: HASH,
    cutAuthorityDigest: HASH, cutApprovalReceiptHash: HASH, cutReviewApprovalReceiptHash: HASH,
    pictureLockHash: HASH, timelineMapHash: HASH, projectionReceiptHash: HASH, createdAt: new Date().toISOString() };
  return { status: "awaiting_cut_approval" as const, request: { ...core, requestHash: canonicalJsonSha256(core) },
    preview: { executionKey: HASH, receiptHash: HASH } };
}

function runtime(t: TestContext) {
  const dir = mkdtempSync("/private/tmp/TEST-author-cut-stage-");
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const seed = { planVersion: 2, target: { mode: "longform", scope: "produced", lanes: {},
    width: 1920, height: 1080, fps: 29.97, durationTargetS: 0, platforms: ["youtube"], treatment: "produced" },
    cutTrack: [], cutDecisions: { schemaVersion: 1, removals: [] } };
  const ctx: AutoEditCtx = { dir, planPath: `${dir}/edit_plan.json`, manifestPath: `${dir}/asset_manifest.json`,
    transcriptsDir: dir, scope: "produced", intent: { mode: "longform", lanes: {}, brief: "TEST source-faithful teaching." },
    workflowPolicy: "cut-first", workflowV2: { schemaVersion: 2, mode: "guided", afterCut: "treatment-then-intro",
      approvalPolicy: "explicit-human" }, deliveryPolicy: "mp4-only" };
  writeFileSync(ctx.planPath, JSON.stringify(seed)); writeFileSync(ctx.manifestPath, JSON.stringify({ sources: [] }));
  const request = parseAuthorCutRequest({ schemaVersion: 1, operation: "author-cut", idempotencyKey: randomUUID(),
    manifest: { path: ctx.manifestPath, sha256: fileSha256(ctx.manifestPath)! }, intent: { ...ctx.intent, scope: ctx.scope },
    output: { width: 1920, height: 1080, fps: 29.97 } });
  assert.deepEqual(seed, { ...authoredCutSeed(request), planVersion: 2 });
  ctx.authoredCut = { schemaVersion: 1, policy: "source-brief-cut", requestHash: HASH,
    initialPlanSha256: fileSha256(ctx.planPath)!, transcriptDigest: HASH, preparationStartedAt: new Date().toISOString() };
  const events: Record<string, unknown>[] = [], calls: string[] = [];
  const run: AuthoringRuntime = { job: freshJob({ ctx, token: randomUUID(), snapshots: 0 }, new Date().toISOString()),
    io: { send: (event) => events.push(event), advance: (change) => (run.job = { ...run.job, ...change }),
      invalidate: (change) => (run.job = { ...run.job, ...change }) } };
  const draft = { ...seed, target: { ...seed.target, durationTargetS: 12 },
    cutTrack: [{ sourceId: "TEST-source", start: 0, end: 12, speed: 1, rationale: "TEST complete teaching." }] };
  return { run, calls, events, seed, draft, writeDraft: () => writeFileSync(ctx.planPath, JSON.stringify(draft)) };
}

/** Fixed production hooks are stubbed explicitly, never daemon/provider implementations. */
function guards(t: TestContext, f: ReturnType<typeof runtime>): void {
  t.mock.method(authoredCutStageGuards, "current", () => { f.calls.push("current"); });
  t.mock.method(authoredCutStageGuards, "quiescent", async () => { f.calls.push("drain"); });
  t.mock.method(authoredCutStageGuards, "seed", () => {
    f.calls.push("seed"); assert.deepEqual(JSON.parse(readFileSync(f.run.job.ctx.planPath, "utf8")), f.seed);
  });
  t.mock.method(authoringWriterGuards, "authoredDraft", () => {
    f.calls.push("draft"); assert.deepEqual(JSON.parse(readFileSync(f.run.job.ctx.planPath, "utf8")), f.draft);
  });
  t.mock.method(authoredCutStageGuards, "compatibility", async () => { f.calls.push("compatibility"); return {} as never; });
  t.mock.method(authoredCutStageGuards, "boundary", async () => { f.calls.push("preview"); return fakePause(f.run); });
}

export function authoredStageFixture(t: TestContext) {
  const f = runtime(t); guards(t, f);
  const forbidden = async () => { assert.fail("TEST forbidden legacy fallback"); };
  const deps: AuthoringStageDependencies = { ...DEFAULT_PIPELINE_DEPENDENCIES,
    exists: existsSync, hashFile: fileSha256, authority: testAuthority,
    author: async (_ctx, _send, stage, mode) => { f.calls.push(`writer:${stage}:${mode}`); f.writeDraft(); return SUCCESS; },
    bindSession: (job) => { f.calls.push("bind-session"); return job; },
    validateCut: async () => { f.calls.push("previsual"); return {} as never; },
    reviewCut: async () => { f.calls.push("two-critics"); return {} as never; },
    approveCut: async () => { f.calls.push("approve-previsual"); return {} as never; },
    validateSavedCut: forbidden, approveSavedCut: forbidden, verifyCut: forbidden,
    verifyReviewCut: () => { assert.fail("TEST forbidden legacy reuse"); }, checkpoint: forbidden };
  return { ...f, deps };
}
