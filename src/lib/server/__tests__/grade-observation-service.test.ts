import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { observeProjectSource, persistObservationCandidate, type PrivateGradeObservation } from "../grade-observation-service";
import { translatedDeadline, type GradeInvocation, type GradeProcessResult } from "../grade-observation-process";
import { parents, POLICY, readRecord, validateRequest, writeRecord } from "../grade-observation-store";
import { acquireProjectMutationLease } from "../project-mutation-lease";

function fixture() {
  const previous = process.env.SNIPER_WORKSPACE_ROOT;
  const workspace = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "grade-owner-unit-")));
  const project = path.join(workspace, "synthetic"), dir = path.join(project, "producer");
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(project, "project.json"), JSON.stringify({ origin: "raw", history: [], syntheticTestOnly: true }));
  fs.writeFileSync(path.join(dir, "edit_plan.json"), JSON.stringify({ planVersion: 1, cutTrack: [{ sourceId: "raw-1", start: 60, end: 70 }] }));
  fs.writeFileSync(path.join(dir, "asset_manifest.json"), JSON.stringify({ inertUnitTestOnly: true }));
  process.env.SNIPER_WORKSPACE_ROOT = workspace;
  const observed = parents(dir);
  const request = { dir, sourceId: "raw-1", expectedPlanHash: observed.planSha256, expectedManifestHash: observed.manifestSha256,
    declaration: { schemaVersion: 1, sourceId: "raw-1", sourceProfile: "bt709-sdr", cameraProfile: null,
      historyState: "known", transformHistory: [], lightingGroups: [{ id: "whole", startFrame: 0, endFrame: 180,
        intent: "unknown", description: "Inert lease test, never a real source proof" }] } };
  return { workspace, project, dir, request, cleanup: () => {
    if (previous === undefined) delete process.env.SNIPER_WORKSPACE_ROOT; else process.env.SNIPER_WORKSPACE_ROOT = previous;
    fs.rmSync(workspace, { recursive: true, force: true });
  } };
}
function failed(input: GradeInvocation, cleanupVerified = true): GradeProcessResult {
  const request = readRecord(path.join(input.directory, "input.json"));
  const body = { schemaVersion: 1, policy: POLICY, jobId: request.jobId, inputSha256: input.inputHash,
    status: "failed", cleanupVerified, cleanupMs: 7, gradeApplicable: false, deliveryApproved: false,
    errors: ["Synthetic unit failure; no media was decoded"] };
  const resultSha256 = writeRecord(path.join(input.directory, "observation.json"), { ...body, artifactHash: canonicalJsonSha256(body) });
  return { resultSha256, cleanupVerified, status: "failed", handshake: null };
}
test("clock translation is conservative across unrelated epochs and never refreshes the admitted budget", () => {
  assert.equal(translatedDeadline("5000000000000", BigInt(120000000000), BigInt(20000000000)), "5100000000000");
  assert.throws(() => translatedDeadline("123", BigInt(120), BigInt(121)), /budget/);
  assert.throws(() => translatedDeadline("123", BigInt(120000000001), BigInt(0)), /budget/);
  assert.throws(() => translatedDeadline("-123", BigInt(10), BigInt(0)), /sample/);
});
test("request has no path/hash/receipt override and bounded declaration input", () => {
  const f = fixture();
  try {
    assert.throws(() => validateRequest({ ...f.request, sourceSha256: "a".repeat(64) } as never), /Invalid/);
    assert.throws(() => validateRequest({ ...f.request, dir: f.dir + "/../producer" }), /Invalid/);
    let nested: unknown = {};
    for (let index = 0; index < 10; index++) nested = { nested };
    assert.throws(() => validateRequest({ ...f.request, declaration: nested as never }), /nested/);
    assert.throws(() => validateRequest({ ...f.request, declaration: { text: "x".repeat(33000) } }), /large/);
  } finally { f.cleanup(); }
});
test("clean failure is private, releases both exact leases, and never writes canonical media or plans", async () => {
  const f = fixture(), before = fs.readFileSync(path.join(f.dir, "edit_plan.json"));
  try {
    const result = await observeProjectSource(f.request, { run: async input => failed(input) });
    assert(!(result instanceof Response)); assert.equal(result.status, "failed"); assert.equal(result.cleanupVerified, true);
    assert.equal(result.gradeApplicable, false); assert.equal(result.deliveryApproved, false);
    assert.deepEqual(fs.readFileSync(path.join(f.dir, "edit_plan.json")), before);
    assert(!fs.existsSync(path.join(f.project, ".sniper-project-mutation.lock")));
    assert(!fs.existsSync(path.join(f.workspace, ".sniper-color-resource/active.json")));
    assert(!fs.existsSync(path.join(f.dir, "final.mp4")));
  } finally { f.cleanup(); }
});
test("uncertain daemon cleanup retains project and shared resource ownership", async () => {
  const f = fixture();
  try {
    const result = await observeProjectSource(f.request, { run: async input => failed(input, false) });
    assert(!(result instanceof Response)); assert.equal(result.cleanupVerified, false);
    assert(fs.existsSync(path.join(f.project, ".sniper-project-mutation.lock")));
    assert(fs.existsSync(path.join(f.workspace, ".sniper-color-resource/active.json")));
    assert.equal((await observeProjectSource(f.request)) instanceof Response, true);
  } finally { f.cleanup(); }
});
test("changed active claim cannot be silently cleared or followed by lease release", async () => {
  const f = fixture();
  try {
    const result = await observeProjectSource(f.request, { run: async input => {
      const active = path.join(f.workspace, ".sniper-color-resource/active.json");
      fs.chmodSync(active, 0o600); fs.writeFileSync(active, JSON.stringify({ requestDigest: "other-owner" }));
      return failed(input);
    } });
    assert(!(result instanceof Response)); assert.equal(result.status, "interrupted");
    assert(fs.existsSync(path.join(f.project, ".sniper-project-mutation.lock")));
    assert.equal(readRecord(path.join(f.workspace, ".sniper-color-resource/active.json")).requestDigest, "other-owner");
  } finally { f.cleanup(); }
});
test("an existing sampled-color resource lease blocks full-source work", async () => {
  const f = fixture(); let calls = 0;
  const resource = path.join(f.workspace, ".sniper-color-resource"); fs.mkdirSync(resource, { mode: 0o700 });
  const held = acquireProjectMutationLease(resource, "existing sampled color diagnostic"); assert(held.lease);
  try {
    await assert.rejects(observeProjectSource(f.request, { run: async input => { calls++; return failed(input); } }), /busy/);
    assert.equal(calls, 0); assert(!fs.existsSync(path.join(f.dir, ".sniper-grade-observations")));
  } finally { held.lease.release(); f.cleanup(); }
});
test("expiry during persistence leaves only nonselectable candidate evidence, never durable complete", () => {
  const f = fixture();
  const result: PrivateGradeObservation = { jobId: "unit", sourceId: "raw-1", status: "complete", cleanupVerified: true,
    elapsedMs: 119999, cleanupMs: 5, decodedFrames: 180, error: null, gradeApplicable: false, deliveryApproved: false };
  let calls = 0;
  try {
    fs.chmodSync(f.dir, 0o700);
    persistObservationCandidate(result, { directory: f.dir, deadline: BigInt(120),
      held: { status: "complete", cleanupVerified: true, resultSha256: "a".repeat(64), handshake: null } },
    { write: writeRecord, check: () => { if (++calls === 2) throw new Error("deadline during persistence"); } });
    const retained = readRecord(path.join(f.dir, "server-result.json"));
    assert.equal(result.status, "interrupted"); assert.equal(result.decodedFrames, null);
    assert.equal(retained.status, "candidate-only"); assert.equal(retained.selection, "live-return-only");
    assert.match(result.error ?? "", /deadline during persistence/);
  } finally { f.cleanup(); }
});
