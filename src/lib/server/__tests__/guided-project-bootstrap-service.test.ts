import assert from "node:assert/strict";
import { test } from "node:test";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { bootstrapGuidedProject, bootstrapServices } from "../guided-project-bootstrap";
import { assertBootstrapBytes, bootstrapProjectPath, BOOTSTRAP_INTAKE } from "../guided-project-bootstrap-store";
import { assertBootstrapSavedPlan } from "../guided-project-bootstrap-guard";
import { assertBootstrapIntent, parseBootstrapRequest, assertExistingCutContext } from "../guided-project-bootstrap-contract";
import { autoEditRequestKey } from "../auto-edit-hash";
import { autoEditJobPath, parseAutoEditJobRecord } from "../auto-edit-job-persistence";
import { startAutoEditJob } from "../auto-edit-job-store";
import { bootstrapFixture } from "./_guided-project-bootstrap-fixture";

test("new project saves only version increment, preserves exact original files and actual intent, never accepts", async (t) => {
  const f = bootstrapFixture(t), input = readFileSync(f.candidate), manifest = readFileSync(f.manifest);
  const { job, result, dir } = await f.start();
  assert.equal(result.state, "launched-not-yet-qualified"); assert.equal(result.cutAccepted, false);
  assert.equal(result.approvalGranted, false); assert.equal(f.launches(), 1);
  const saved = readCutPreviewObject(job.ctx.planPath);
  assertBootstrapSavedPlan(f.plan, saved.value); assert.equal(saved.value.planVersion, 8);
  assert.equal(job.ctx.existingCutCandidate?.savedPlanSha256, saved.sha256);
  assert.equal(job.checkpoint, "queued"); assert.equal(job.cutAcceptance, undefined);
  assert.deepEqual(readFileSync(f.candidate), input); assert.deepEqual(readFileSync(f.manifest), manifest);
  const project = readCutPreviewObject(path.join(path.dirname(dir), "project.json")).value;
  assert.deepEqual(project.intent, f.request.intent); assert.deepEqual(project.intentDecisions, []);
});

test("identical concurrent UUID is read-only replay; conflicting UUID and partial root never launch", async (t) => {
  const f = bootstrapFixture(t);
  const results = await Promise.all([bootstrapGuidedProject(f.request), bootstrapGuidedProject(f.request)]);
  assert.equal(f.launches(), 1); assert.equal(results.filter((row) => row.replayed).length, 1);
  await assert.rejects(bootstrapGuidedProject({ ...f.request, intent: { ...f.request.intent, brief: "TEST different" } }), /conflicts/);
  const partial = { ...f.request, idempotencyKey: "fedcba98-7654-4321-8123-012345678901" };
  const root = bootstrapProjectPath(partial.idempotencyKey); mkdirSync(root);
  await assert.rejects(bootstrapGuidedProject(partial), /ENOENT/);
  assert.equal(existsSync(path.join(root, BOOTSTRAP_INTAKE)), false); assert.equal(f.launches(), 1);
});

test("stale input and mutation during save stop before start/spawn without changing originals", async (t) => {
  const f = bootstrapFixture(t), originalSave = bootstrapServices.save;
  await assert.rejects(bootstrapGuidedProject({ ...f.request, candidate: { ...f.request.candidate, sha256: "f".repeat(64) } }), /stale/);
  assert.equal(existsSync(bootstrapProjectPath(f.request.idempotencyKey)), false);
  t.mock.method(bootstrapServices, "save", async (input: Parameters<typeof originalSave>[0]) => {
    const result = await originalSave(input); writeFileSync(f.manifest, "{}"); return result;
  });
  await assert.rejects(bootstrapGuidedProject(f.request), /stale/); assert.equal(f.launches(), 0);
  const replay = await bootstrapGuidedProject(f.request);
  assert.equal(replay.state, "failed-or-unknown-no-relaunch"); assert.equal(f.launches(), 0);
});

test("failed or ambiguous launch retains evidence and never retries even if current input later changes", async (t) => {
  const f = bootstrapFixture(t); let attempted = 0;
  t.mock.method(bootstrapServices, "launch", async () => { attempted++; throw new Error("TEST launch identity unknown"); });
  await assert.rejects(bootstrapGuidedProject(f.request), /identity unknown/);
  writeFileSync(f.candidate, "{}");
  const replay = await bootstrapGuidedProject(f.request);
  assert.equal(replay.state, "failed-or-unknown-no-relaunch"); assert.equal("cleanupUnknown" in replay && replay.cleanupUnknown, true);
  assert.equal(attempted, 1);
  assert.ok(existsSync(path.join(bootstrapProjectPath(f.request.idempotencyKey), ".sniper-project-mutation.lock")));
});

test("policy is included in identity, closed at persistence and dispatch, and cannot resume or use saved/writer completion", async (t) => {
  const f = bootstrapFixture(t), { job } = await f.start();
  assert.notEqual(job.requestKey, autoEditRequestKey({ ...job.ctx, existingCutCandidate: undefined }));
  for (const extra of [{ reviewSavedPlan: true }, { resume: job }, { bootstrapPlanHash: "a".repeat(64) }]) {
    assert.throws(() => startAutoEditJob({ ctx: job.ctx, token: "TEST-other", snapshots: 0, ...extra }), /new-only|cannot/);
  }
  for (const policy of [null, { ...job.ctx.existingCutCandidate, extra: true }, { ...job.ctx.existingCutCandidate, policy: "writer" }]) {
    const ctx = { ...job.ctx, existingCutCandidate: policy } as never;
    assert.throws(() => assertExistingCutContext(ctx));
    assert.throws(() => parseAutoEditJobRecord({ ...job, ctx, requestKey: autoEditRequestKey(ctx) }));
  }
  for (const patch of [{ workflowV2: undefined }, { workflowPolicy: undefined }, { deliveryPolicy: "palmier-hybrid" }]) {
    assert.throws(() => assertExistingCutContext({ ...job.ctx, ...patch } as never));
  }
  assert.throws(() => parseAutoEditJobRecord({ ...job, attempts: 2 }));
});

test("exact candidate guard never fills missing intent or changes produced treatment to pass previsual gates", (t) => {
  const f = bootstrapFixture(t);
  for (const patch of [{ mode: "shortform" }, { scope: undefined }, { treatment: "clean-cut" },
    { pace: "fast" }, { style: "minimal" }, { lanes: { graphics: "off" } }]) {
    assert.throws(() => assertBootstrapIntent({ ...f.plan, target: { ...f.plan.target, ...patch } }, f.request.intent));
  }
  for (const patch of [{ approved: true }, { workerPid: 1 }, { overrides: {} }, { intent: { ...f.request.intent, unknown: true } }]) {
    assert.throws(() => parseBootstrapRequest({ ...f.request, ...patch }));
  }
  assert.throws(() => assertBootstrapSavedPlan(f.plan, { ...f.plan, planVersion: 9 }));
  assert.throws(() => assertBootstrapSavedPlan(f.plan, { ...f.plan, planVersion: 8, cutTrack: [] }));
});

test("original and saved byte guards catch post-save mutation rather than silently resealing", async (t) => {
  const f = bootstrapFixture(t), { job } = await f.start();
  assert.doesNotThrow(() => assertBootstrapBytes(job));
  for (const file of [f.candidate, f.manifest, job.ctx.planPath]) {
    const before = readFileSync(file); writeFileSync(file, Buffer.concat([before, Buffer.from("\n")]));
    assert.throws(() => assertBootstrapBytes(job), /changed/); writeFileSync(file, before);
  }
});

test("bootstrap music metadata is strict, effective-false, and never grants a contradictory opt-in", (t) => {
  const f = bootstrapFixture(t);
  const cases = [undefined, false, true].flatMap((intentMusic) =>
    [undefined, false, true, null, 0, 1, "true", [], {}].map((targetMusic) => ({ intentMusic, targetMusic })));
  for (const { intentMusic, targetMusic } of cases) {
    const intent = { ...f.request.intent, ...(intentMusic === undefined ? {} : { music: intentMusic }) };
    const plan = { ...f.plan, target: { ...f.plan.target, ...(targetMusic === undefined ? {} : { music: targetMusic }) } };
    const valid = (targetMusic === undefined || typeof targetMusic === "boolean") && (targetMusic === true) === (intentMusic === true);
    const check = () => assertBootstrapIntent(plan, intent);
    if (valid) assert.doesNotThrow(check); else assert.throws(check, /music intent/);
  }
  assert.throws(() => assertBootstrapIntent(f.plan, { ...f.request.intent, music: "false" } as never), /music intent/);
  assert.throws(() => assertBootstrapIntent({ ...f.plan, target: { ...f.plan.target, music: undefined } }, f.request.intent), /music intent/);
});

test("requested music with absent target mirror stops before new project/save/spawn and preserves inputs", async (t) => {
  const f = bootstrapFixture(t), candidate = readFileSync(f.candidate), manifest = readFileSync(f.manifest);
  const request = { ...f.request, intent: { ...f.request.intent, music: true } };
  await assert.rejects(bootstrapGuidedProject(request), /music intent/);
  assert.equal(f.launches(), 0);
  assert.equal(existsSync(bootstrapProjectPath(request.idempotencyKey)), false);
  assert.deepEqual(readFileSync(f.candidate), candidate);
  assert.deepEqual(readFileSync(f.manifest), manifest);
});

test("fresh explicit music mirror persists with actual intent while the accepted-candidate input remains cut-only", async (t) => {
  const f = bootstrapFixture(t);
  const plan = { ...f.plan, target: { ...f.plan.target, music: true } };
  writeFileSync(f.candidate, JSON.stringify(plan));
  const original = readFileSync(f.candidate), observed = readCutPreviewObject(f.candidate);
  const request = { ...f.request, intent: { ...f.request.intent, music: true },
    candidate: { ...f.request.candidate, sha256: observed.sha256 } };
  const result = await bootstrapGuidedProject(request);
  const journal = readCutPreviewObject(autoEditJobPath(result.producerDir));
  const job = parseAutoEditJobRecord(journal.value), saved = readCutPreviewObject(job.ctx.planPath);
  assert.equal(job.ctx.intent?.music, true);
  assert.equal((saved.value.target as Record<string, unknown>).music, true);
  assert.equal(Object.hasOwn(saved.value, "music"), false);
  assertBootstrapSavedPlan(plan, saved.value);
  assert.deepEqual(readFileSync(f.candidate), original);
  assert.equal(result.cutAccepted, false); assert.equal(result.approvalGranted, false);
});
