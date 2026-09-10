/** Real metadata guards, TEST source metadata only; no admitted media or editor output. */
import assert from "node:assert/strict";
import path from "node:path";
import { test } from "node:test";
import { readFileSync, writeFileSync, renameSync, symlinkSync, unlinkSync, truncateSync } from "node:fs";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { autoEditJobPath, parseAutoEditJobRecord } from "../auto-edit-job-persistence";
import { autoEditAuthoritySnapshot, autoEditTranscriptDigest } from "../auto-edit-authority-snapshot";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { captureAutoEditPipeline } from "../auto-edit-pipeline-authority";
import { bootstrapSeedPath } from "../guided-project-bootstrap-store";
import { assertAuthoredBootstrapDraft, assertAuthoredBootstrapSeed, assertBootstrapCurrent,
  assertBootstrapCode, bootstrapRuntimeGuards } from "../guided-project-bootstrap-guard";
import { authorFixture, assertOriginalBytes } from "./_guided-project-author-fixture";
import { HASH } from "./_guided-project-bootstrap-fixture";

function proposedPlan(file: string): Record<string, unknown> {
  const seed = readCutPreviewObject(file).value;
  return { ...seed, target: { ...(seed.target as object), durationTargetS: 1 },
    cutTrack: [{ sourceId: "TEST-source", start: 0, end: 1, speed: 1 }],
    cutDecisions: { schemaVersion: 1, removals: [] } };
}

test("real seed/draft guard preserves fixed intent but permits new proposed cuts and increasing versions", async t => {
  const f = authorFixture(t), { job } = await f.start(); let codeChecks = 0;
  t.mock.method(bootstrapRuntimeGuards, "code", () => { codeChecks++; });
  assert.doesNotThrow(() => assertAuthoredBootstrapSeed(job));
  assert.throws(() => assertAuthoredBootstrapDraft(job), /empty seed/);
  const proposed = proposedPlan(job.ctx.planPath); writeFileSync(job.ctx.planPath, JSON.stringify(proposed));
  assert.doesNotThrow(() => assertAuthoredBootstrapDraft(job));
  assert.throws(() => assertAuthoredBootstrapSeed(job), /exact unapproved seed/);
  writeFileSync(job.ctx.planPath, JSON.stringify({ ...proposed, planVersion: 3 }));
  assert.doesNotThrow(() => assertAuthoredBootstrapDraft(job));
  assert.equal(codeChecks, 5); assertOriginalBytes(f.originals);
});

test("new draft cannot alter canvas/rate/music/lanes, reset version, add visual tracks or retime speech", async t => {
  const f = authorFixture(t), { job } = await f.start();
  const code = t.mock.method(bootstrapRuntimeGuards, "code", () => {});
  const proposed = proposedPlan(job.ctx.planPath), target = proposed.target as Record<string, unknown>;
  const variants = [
    ...[{ width: 1080 }, { fps: 24 }, { music: true }, { lanes: { captions: "off" } }, { mode: "short" }]
      .map(change => ({ ...proposed, target: { ...target, ...change } })),
    { ...proposed, planVersion: 1 }, { ...proposed, graphicsTrack: [] }, { ...proposed, cutTrack: [] },
    { ...proposed, target: { ...target, durationTargetS: 0 } },
    ...[{ speed: 1.1 }, { audioLeadMs: 100 }].map(change => ({ ...proposed,
      cutTrack: [{ sourceId: "TEST-source", start: 0, end: 1, ...change }] })),
  ];
  for (const variant of variants) {
    writeFileSync(job.ctx.planPath, JSON.stringify(variant));
    assert.throws(() => assertAuthoredBootstrapDraft(job), /protected|version|unsupported|cut|duration/i);
  }
  assert.equal(code.mock.callCount(), 0); assertOriginalBytes(f.originals);
});

test("seed, transcript and project brief drift reject before runtime authorization, never silently rebind", async t => {
  const f = authorFixture(t), { job, dir } = await f.start();
  const code = t.mock.method(bootstrapRuntimeGuards, "code", () => {});
  writeFileSync(job.ctx.planPath, JSON.stringify(proposedPlan(job.ctx.planPath)));
  const project = path.join(path.dirname(dir), "project.json"), seed = bootstrapSeedPath(dir);
  for (const file of [seed, f.manifest, f.transcript, project]) {
    const original = readFileSync(file), value = JSON.parse(original.toString("utf8"));
    const changed = file === project ? { ...value, intent: { ...value.intent, brief: "TEST drift" } } : { ...value, TEST_drift: true };
    writeFileSync(file, JSON.stringify(changed));
    assert.throws(() => assertBootstrapCurrent(job), /changed/);
    writeFileSync(file, original);
  }
  assert.equal(code.mock.callCount(), 0);
  assert.doesNotThrow(() => assertBootstrapCurrent(job)); assertOriginalBytes(f.originals);
});

test("bounded transcript identity equals the legacy digest but rejects replaced oversized/linked/missing/invalid bytes", async t => {
  const f = authorFixture(t), { job } = await f.start(), original = readFileSync(f.transcript);
  assert.equal(autoEditTranscriptDigest(job.ctx), autoEditAuthoritySnapshot(job.ctx).transcriptDigest);
  for (const invalid of ["[]", "null", "{", Buffer.from([0xc3, 0x28])]) {
    writeFileSync(f.transcript, invalid); assert.throws(() => autoEditTranscriptDigest(job.ctx));
  }
  writeFileSync(f.transcript, original); truncateSync(f.transcript, 16 * 1024 * 1024 + 1);
  assert.throws(() => autoEditTranscriptDigest(job.ctx), /bounded regular/); writeFileSync(f.transcript, original);
  const moved = `${f.transcript}.TEST-held`; renameSync(f.transcript, moved);
  assert.throws(() => autoEditTranscriptDigest(job.ctx), /ENOENT/);
  symlinkSync(moved, f.transcript); assert.throws(() => autoEditTranscriptDigest(job.ctx));
  unlinkSync(f.transcript); renameSync(moved, f.transcript); assertOriginalBytes(f.originals);
});

test("journal policy exclusivity, one-attempt and current context fences apply to authored jobs", async t => {
  const f = authorFixture(t), { job } = await f.start();
  for (const change of [{ attempts: 2 }, { reviewSavedPlan: true }, { status: "complete", checkpoint: "complete" },
    { checkpoint: "rendered" }, { finalHash: HASH }, { ctx: { ...job.ctx, authoredCut: null } },
    { ctx: { ...job.ctx, existingCutCandidate: { schemaVersion: 1, policy: "previsual-review-only", requestHash: HASH,
      inputPlanSha256: HASH, savedPlanSha256: HASH } } }]) {
    assert.throws(() => parseAutoEditJobRecord({ ...job, ...change }), /malformed/);
  }
  const changed = { ...job, ctx: { ...job.ctx, brainSessionId: "TEST-other-context" } };
  writeFileSync(autoEditJobPath(job.ctx.dir), JSON.stringify(changed));
  assert.throws(() => assertBootstrapCurrent(job), /runtime context/);
});

test("late code-check interval cannot replace validated draft, transcript or current journal before binding", async t => {
  const f = authorFixture(t), { job } = await f.start(), proposed = proposedPlan(job.ctx.planPath);
  writeFileSync(job.ctx.planPath, JSON.stringify(proposed));
  const mutations = [
    { file: job.ctx.planPath, value: { ...proposed, cutTrack: [{ sourceId: "TEST-source", start: 0, end: 1, speed: 2 }] } },
    { file: f.transcript, value: { TEST: "changed after transcript validation" } },
    { file: autoEditJobPath(job.ctx.dir), value: { ...job, status: "interrupted" } },
  ];
  for (const mutation of mutations) {
    const bytes = readFileSync(mutation.file);
    const mocked = t.mock.method(bootstrapRuntimeGuards, "code", () => { writeFileSync(mutation.file, JSON.stringify(mutation.value)); });
    assert.throws(() => assertAuthoredBootstrapDraft(job), /changed during authorization/);
    mocked.mock.restore(); writeFileSync(mutation.file, bytes);
  }
  assertOriginalBytes(f.originals);
});

test("actual repository code snapshot contains authored stage/writer/deadline and missing required closure rejects", async t => {
  const f = authorFixture(t), { job } = await f.start();
  job.ctx.pipeline = captureAutoEditPipeline(job.ctx, "TEST-authored-code-closure");
  job.ctx.doctrine = { runId: "TEST", doctrineHash: HASH, snapshotPath: path.join(f.root, "TEST-not-restored"), files: {} };
  assert.doesNotThrow(() => assertBootstrapCode(job));
  const omitted = "src/lib/server/guided-project-author-cut-stage.ts";
  const pipeline = job.ctx.pipeline;
  assert.ok(pipeline.files.some(row => row.path === omitted));
  const files = pipeline.files.filter(row => row.path !== omitted), digest = canonicalJsonSha256(files);
  const lock = readCutPreviewObject(pipeline.lockPath).value;
  writeFileSync(pipeline.lockPath, JSON.stringify({ ...lock, files, digest }));
  job.ctx.pipeline = { ...pipeline, files, digest };
  assert.throws(() => assertBootstrapCode(job), /runtime closure is incomplete/); assertOriginalBytes(f.originals);
});
