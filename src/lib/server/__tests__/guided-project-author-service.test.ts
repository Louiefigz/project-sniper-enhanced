import assert from "node:assert/strict";
import path from "node:path";
import { test } from "node:test";
import { existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { authorGuidedProjectCut, bootstrapGuidedProject, bootstrapServices } from "../guided-project-bootstrap";
import { assertBootstrapJob, assertBootstrapBytes, readBootstrapIntake, bootstrapSeedPath,
  bootstrapProjectPath, BOOTSTRAP_INTAKE } from "../guided-project-bootstrap-store";
import { readCutPreviewObject, observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { autoEditRequestKey } from "../auto-edit-hash";
import { startAutoEditJob } from "../auto-edit-job-store";
import { authoredPreparationRuntime } from "../guided-project-preparation-deadline";
import { authorFixture, assertOriginalBytes } from "./_guided-project-author-fixture";

test("new authored project retains exact saved seed, original transcript/intent/time, and no acceptance", async t => {
  const f = authorFixture(t), started = new Date(Date.now() - 1000).toISOString();
  const { result, dir, job } = await f.start(started), seed = readCutPreviewObject(bootstrapSeedPath(dir));
  assert.equal(f.launches(), 1); assert.equal(result.cutAccepted, false); assert.equal(result.approvalGranted, false);
  assert.equal(job.ctx.existingCutCandidate, undefined); assert.equal(job.ctx.authoredCut?.initialPlanSha256, seed.sha256);
  assert.deepEqual(seed.bytes, readFileSync(job.ctx.planPath)); assert.equal(seed.value.planVersion, 2);
  assert.deepEqual(Object.keys(seed.value), ["planVersion", "target", "cutTrack", "cutDecisions"]);
  assert.deepEqual(seed.value.cutTrack, []); assert.equal(job.ctx.authoredCut?.preparationStartedAt, started);
  assert.equal(readBootstrapIntake(dir).value.receivedAt, started); assert.equal(job.cutAcceptance, undefined);
  assert.deepEqual(job.ctx.intent?.brief, f.request.intent.brief); assertOriginalBytes(f.originals);
  assert.notEqual(job.requestKey, autoEditRequestKey({ ...job.ctx, authoredCut: undefined }));
  assert.doesNotThrow(() => assertBootstrapJob(job)); assert.doesNotThrow(() => assertBootstrapBytes(job));
});

test("authored guard permits mutable active cut, but rejects changed seed/manifest/intake/operation/origin", async t => {
  const f = authorFixture(t), { job, dir } = await f.start(), seedPath = bootstrapSeedPath(dir);
  writeFileSync(job.ctx.planPath, JSON.stringify({ TEST: "writer candidate is checked by stage, not seed-byte guard" }));
  assert.doesNotThrow(() => assertBootstrapBytes(job));
  for (const file of [seedPath, f.manifest]) {
    const bytes = readFileSync(file); writeFileSync(file, Buffer.concat([bytes, Buffer.from("\n")]));
    assert.throws(() => assertBootstrapBytes(job), /changed/); writeFileSync(file, bytes);
  }
  assert.throws(() => assertBootstrapJob({ ...job, attempts: 2 }), /new-only/);
  assert.throws(() => assertBootstrapJob({ ...job, ctx: { ...job.ctx,
    authoredCut: { ...job.ctx.authoredCut!, preparationStartedAt: new Date(Date.now() - 60000).toISOString() } } }), /exact intake/);
  for (const extra of [{ reviewSavedPlan: true }, { resume: job }, { bootstrapPlanHash: "a".repeat(64) }]) {
    assert.throws(() => startAutoEditJob({ ctx: job.ctx, token: "TEST-other", snapshots: 0, ...extra }), /new-only|cannot/);
  }
});

test("same UUID concurrency/replay never relaunches or resets preparation; cross-operation collision rejects", async t => {
  const f = authorFixture(t), original = new Date(Date.now() - 1000).toISOString();
  const results = await Promise.all([authorGuidedProjectCut(f.request, original), authorGuidedProjectCut(f.request)]);
  assert.equal(f.launches(), 1); assert.equal(results.filter(row => row.replayed).length, 1);
  const dir = results[0].producerDir; assert.equal(readBootstrapIntake(dir).value.receivedAt, original);
  writeFileSync(f.transcript, "{}");
  const replay = await authorGuidedProjectCut(f.request); assert.equal(replay.replayed, true); assert.equal(f.launches(), 1);
  const candidate = { schemaVersion: 1, operation: "bootstrap-existing-cut", idempotencyKey: f.request.idempotencyKey,
    intent: f.request.intent, manifest: f.request.manifest, candidate: { path: f.candidate, sha256: observeCutPreviewFile(f.candidate, 131072).sha256 } };
  await assert.rejects(bootstrapGuidedProject(candidate), /conflicts/);
  await assert.rejects(authorGuidedProjectCut({ ...f.request, intent: { ...f.request.intent, brief: "Different" } }), /conflicts/);
});

test("transcript drift during save or pin is rejected before launch, without reminting original digest", async t => {
  for (const phase of ["save", "pin"] as const) {
    await t.test(phase, async child => {
      const f = authorFixture(child), originalSave = bootstrapServices.save;
      if (phase === "save") child.mock.method(bootstrapServices, "save", async (input: Parameters<typeof originalSave>[0]) => {
        const result = await originalSave(input); writeFileSync(f.transcript, "{}"); return result;
      });
      else child.mock.method(bootstrapServices, "pin", ({ ctx }: Parameters<typeof bootstrapServices.pin>[0]) => {
        writeFileSync(f.transcript, "{}"); return ctx;
      });
      await assert.rejects(authorGuidedProjectCut(f.request), /original transcripts changed/); assert.equal(f.launches(), 0);
      const replay = await authorGuidedProjectCut(f.request);
      assert.equal(replay.state, "failed-or-unknown-no-relaunch"); assert.equal(f.launches(), 0);
    });
  }
});

test("deadline expiry before pin retains partial project and cannot obtain fresh retry credit", async t => {
  const f = authorFixture(t); let pins = 0;
  t.mock.method(bootstrapServices, "pin", () => { pins++; throw new Error("TEST pin must not execute"); });
  await assert.rejects(authorGuidedProjectCut(f.request, new Date(Date.now() - 121 * 60000).toISOString()), /expired|deadline|budget/i);
  assert.equal(pins, 0); assert.equal(f.launches(), 0);
  const replay = await authorGuidedProjectCut(f.request);
  assert.equal(replay.state, "failed-or-unknown-no-relaunch"); assert.equal(pins, 0);
});

test("pin failure after immutable seed publication retains original bytes and refuses every replay launch", async t => {
  const f = authorFixture(t); let pins = 0;
  t.mock.method(bootstrapServices, "pin", () => { pins++; throw new Error("TEST pin failed after seed publication"); });
  await assert.rejects(authorGuidedProjectCut(f.request), /after seed publication/);
  const dir = path.join(bootstrapProjectPath(f.request.idempotencyKey), "producer"), seed = readFileSync(bootstrapSeedPath(dir));
  assert.deepEqual(readFileSync(path.join(dir, "edit_plan.json")), seed); assertOriginalBytes(f.originals);
  const replay = await authorGuidedProjectCut(f.request);
  assert.equal(replay.state, "failed-or-unknown-no-relaunch"); assert.equal(f.launches(), 0); assert.equal(pins, 1);
  assert.deepEqual(readFileSync(bootstrapSeedPath(dir)), seed);
});

test("post-pin seed mutation or elapsed original budget prevents start and worker launch", async t => {
  for (const failure of ["seed", "expired"] as const) {
    await t.test(failure, async child => {
      const f = authorFixture(child); let starts = 0;
      child.mock.method(bootstrapServices, "start", () => { starts++; throw new Error("TEST must not start"); });
      child.mock.method(bootstrapServices, "pin", ({ ctx }: Parameters<typeof bootstrapServices.pin>[0]) => {
        if (failure === "seed") writeFileSync(bootstrapSeedPath(ctx.dir), "{}");
        else child.mock.method(authoredPreparationRuntime, "wall", () => Date.now() + 121 * 60000);
        return ctx;
      });
      await assert.rejects(authorGuidedProjectCut(f.request), /seed changed|expired/i);
      assert.equal(starts, 0); assert.equal(f.launches(), 0); assertOriginalBytes(f.originals);
    });
  }
});

test("invalid/future preparation origin rejects before input observations or singleton creation", async t => {
  const f = authorFixture(t); let reads = 0;
  t.mock.method(bootstrapServices, "inputs", () => { reads++; throw new Error("TEST must not read inputs"); });
  for (const started of ["invalid", new Date(Date.now() + 60000).toISOString()]) {
    await assert.rejects(authorGuidedProjectCut(f.request, started), /ISO|future/);
  }
  assert.equal(reads, 0); assert.equal(existsSync(bootstrapProjectPath(f.request.idempotencyKey)), false);
});

test("failed launch and partial singleton remain retained, unknown and never adopted", async t => {
  const f = authorFixture(t); let attempts = 0;
  t.mock.method(bootstrapServices, "launch", async () => { attempts++; throw new Error("TEST ambiguous launch"); });
  await assert.rejects(authorGuidedProjectCut(f.request), /ambiguous launch/);
  const replay = await authorGuidedProjectCut(f.request);
  assert.equal(replay.state, "failed-or-unknown-no-relaunch"); assert.equal("cleanupUnknown" in replay && replay.cleanupUnknown, true);
  assert.equal(attempts, 1); assert.ok(existsSync(path.join(bootstrapProjectPath(f.request.idempotencyKey), ".sniper-project-mutation.lock")));
  const other = { ...f.request, idempotencyKey: "12345678-1234-4234-8234-123456789012" }, root = bootstrapProjectPath(other.idempotencyKey);
  mkdirSync(root); await assert.rejects(authorGuidedProjectCut(other), /ENOENT/);
  assert.equal(existsSync(path.join(root, BOOTSTRAP_INTAKE)), false); assert.equal(attempts, 1);
});
