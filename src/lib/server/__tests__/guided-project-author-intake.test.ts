import assert from "node:assert/strict";
import path from "node:path";
import { test } from "node:test";
import type { AutoEditCtx } from "@/app/api/producer/auto-edit/stream";
import { writeFileSync, symlinkSync, unlinkSync } from "node:fs";
import { parseBootstrapRequest, parseGuidedProjectRequest, parseAuthoredCutPolicy,
  assertExistingCutContext, hasGuidedBootstrap } from "../guided-project-bootstrap-contract";
import { readBootstrapInputs, authoredCutSeed } from "../guided-project-bootstrap-inputs";
import { autoEditTranscriptDigest } from "../auto-edit-authority-snapshot";
import { authorFixture, shortAuthorRequest, replaceManifestSource } from "./_guided-project-author-fixture";

test("author request is closed, requires exact complete brief, and preserves supplied-candidate parser closure", t => {
  const f = authorFixture(t);
  assert.deepEqual(parseGuidedProjectRequest(f.request), f.request);
  assert.throws(() => parseBootstrapRequest(f.request));
  for (const extra of [{ model: "other" }, { provider: "paid" }, { approved: true }, { deadlineMs: 1 },
    { candidate: { path: f.candidate, sha256: "a".repeat(64) } }, { intent: { ...f.request.intent, brief: undefined } },
    { intent: { ...f.request.intent, brief: " " } }, { intent: { ...f.request.intent, brief: " trim me " } },
    { intent: { ...f.request.intent, brief: "x".repeat(1201) } }, { intent: { ...f.request.intent, lanes: null } }]) {
    assert.throws(() => parseGuidedProjectRequest({ ...f.request, ...extra }));
  }
});

test("explicit canvas/rate parser preserves numbers exactly and rejects unsupported rational targets", t => {
  const f = authorFixture(t);
  for (const fps of [1, 23.976, 29.97, 60]) {
    const request = { ...f.request, output: { ...f.request.output, fps } };
    assert.deepEqual(parseGuidedProjectRequest(request), request);
  }
  for (const fps of [false, null, 0, 60.001, NaN, Infinity, "30", "24000/1001", "1/1", "60/1", "02/1", "30/0", "60/2"]) {
    assert.throws(() => parseGuidedProjectRequest({ ...f.request, output: { ...f.request.output, fps } }));
  }
  assert.equal(shortAuthorRequest(f).output.height, 1920);
  for (const output of [{ width: 3840, height: 2160, fps: 30 }, { width: 1080, height: 1920, fps: 30 },
    { ...f.request.output, width: "1920" }, { ...f.request.output, scale: 1 }]) {
    assert.throws(() => parseGuidedProjectRequest({ ...f.request, output }));
  }
});

test("seed is precisely four unapproved fields and preserves complete intent obligations", t => {
  const f = authorFixture(t), original = structuredClone(f.request);
  for (const music of [false, true]) {
    const request = { ...f.request, intent: { ...f.request.intent, music, excerpt: false, pace: "talking-head" as const } };
    const plan = authoredCutSeed(request), target = plan.target as Record<string, unknown>;
    assert.deepEqual(Object.keys(plan), ["planVersion", "target", "cutTrack", "cutDecisions"]);
    assert.deepEqual(plan.cutTrack, []); assert.deepEqual(plan.cutDecisions, { schemaVersion: 1, removals: [] });
    assert.equal(target.durationTargetS, 0); assert.equal(target.treatment, "produced");
    assert.equal(target.music, music); assert.deepEqual(target.lanes, request.intent.lanes);
    assert.equal(target.excerpt, false); assert.equal(target.pace, "talking-head");
  }
  assert.deepEqual(f.request, original);
  assert.equal(Object.hasOwn(authoredCutSeed(shortAuthorRequest(f)), "reframe"), false);
});

test("authored intake holds real bounded transcript bytes, rejects absent, malformed and linked input", t => {
  const f = authorFixture(t), observed = readBootstrapInputs(f.request);
  assert.equal(observed.transcriptDigest, autoEditTranscriptDigest({ manifestPath: f.manifest, transcriptsDir: f.root }));
  for (const source of [{ id: "TEST" }, { id: "TEST", transcriptPath: "" }, { id: "TEST", transcriptPath: "missing.json" }]) {
    assert.throws(() => readBootstrapInputs(replaceManifestSource(f, source)));
  }
  const request = replaceManifestSource(f, { id: "TEST", transcriptPath: path.basename(f.transcript) });
  for (const raw of ["null", "[]", "{", Buffer.from([255]), Buffer.alloc(16 * 1024 * 1024 + 1, 32)]) {
    writeFileSync(f.transcript, raw); assert.throws(() => readBootstrapInputs(request));
  }
  unlinkSync(f.transcript); symlinkSync(f.candidate, f.transcript);
  assert.throws(() => readBootstrapInputs(request), /links|canonical/);
});

test("both policy fields, malformed closed facts, or missing V2 ownership cannot authorize bootstrap", t => {
  const f = authorFixture(t), policy = { schemaVersion: 1, policy: "source-brief-cut", requestHash: "a".repeat(64),
    initialPlanSha256: "b".repeat(64), transcriptDigest: "c".repeat(64), preparationStartedAt: new Date().toISOString() };
  const ctx = { authoredCut: parseAuthoredCutPolicy(policy), workflowPolicy: "cut-first", deliveryPolicy: "mp4-only",
    workflowV2: { schemaVersion: 2, mode: "guided", afterCut: "treatment-then-intro", approvalPolicy: "explicit-human" } } as AutoEditCtx;
  assert.equal(hasGuidedBootstrap(ctx), true); assert.doesNotThrow(() => assertExistingCutContext(ctx));
  for (const patch of [{ extra: true }, { initialPlanSha256: "bad" }, { preparationStartedAt: "bad" },
    { preparationStartedAt: new Date(Date.now() + 60000).toISOString() }]) assert.throws(() => parseAuthoredCutPolicy({ ...policy, ...patch }));
  assert.throws(() => assertExistingCutContext({ ...ctx, existingCutCandidate: null } as never));
  assert.throws(() => assertExistingCutContext({ ...ctx, workflowPolicy: undefined } as never));
  assert.equal(f.launches(), 0);
});
