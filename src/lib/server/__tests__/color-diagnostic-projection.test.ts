import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { completedStatus } from "../../../app/api/producer/color-diagnostic/projection";
import { hash, type JobRequest } from "../../../app/api/producer/color-diagnostic/files";
import { unknownColorContext } from "../../producer/color-diagnostic";

function evidence() {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "color-projection-test-")));
  const dir = path.join(root, "producer"); fs.mkdirSync(dir, { mode: 0o700 });
  const diagnosticId = randomUUID(), source = { id: "raw-1", label: "inert", duration: 90, sha256: "a".repeat(64) };
  const context = unknownColorContext(source), planText = JSON.stringify({ cutTrack: [{ sourceId: "raw-1", start: 0, end: 90 }] });
  const request = { schema: 1, request: { dir, jobId: randomUUID(), expectedPlanHash: hash(planText), expectedManifestHash: "b".repeat(64), contexts: [context] },
    descriptor: { sources: [source] }, startedAt: new Date().toISOString(), digest: "c".repeat(64), planText } as JobRequest;
  const invocation = { schemaVersion: 1, policy: "sniper-private-source-color-v1", diagnosticId, producerDir: dir,
    planHash: request.request.expectedPlanHash, manifestHash: request.request.expectedManifestHash, contexts: [context] };
  const samples = [0.1, 20, 40, 60, 89.9].map((sourceTime, i) => ({ id: `sample-${i}`, sourceId: source.id, groupId: "whole-source", sourceTime, intervalIndex: 0, maximumSeekDeltaS: 0.05 }));
  const group = { sourceId: source.id, groupId: "whole-source", intent: "unknown", context,
    retainedIntervals: [{ sourceStart: 0, sourceEnd: 90, outStart: 0, outEnd: 90 }], samples,
    observations: samples.map(sample => ({ id: sample.id, requestedTime: sample.sourceTime, actualSourceTime: sample.sourceTime, status: "sampled", elapsedMs: 1 })),
    unsampledIntervalIndices: [], summary: { sampledFrames: 5 }, metadata: { supportedSamplingClass: "limited-8bit-bt709" }, suggestions: [] as unknown[], warnings: [] };
  const result = { schemaVersion: 1, policy: invocation.policy, diagnosticId, requestHash: canonicalJsonSha256(invocation),
    state: "complete", reviewState: "unreviewed", deliveryApproved: false, qualityQualified: false, writesGrade: false, inputsRevalidated: true,
    bindings: { planHash: invocation.planHash, manifestHash: invocation.manifestHash, declaredContextHash: canonicalJsonSha256([context]) },
    sources: [{ sourceId: source.id, sha256: source.sha256 }], groups: [group], workers: [], caveats: [] };
  const store = path.join(dir, ".sniper-color-diagnostics"), attempt = path.join(store, diagnosticId);
  fs.mkdirSync(store, { mode: 0o700 }); fs.mkdirSync(attempt, { mode: 0o700 });
  const publish = () => {
    fs.writeFileSync(path.join(attempt, "request.json"), JSON.stringify({ ...invocation, artifactHash: canonicalJsonSha256(invocation) }));
    fs.writeFileSync(path.join(attempt, "result.json"), JSON.stringify({ ...result, artifactHash: canonicalJsonSha256(result) }));
  };
  publish();
  return { root, request, result, invocation, publish, terminal: { diagnosticId, cleanupVerified: true, elapsedMs: 1200, interrupted: false, requestDigest: request.digest },
    cleanup: () => fs.rmSync(root, { recursive: true, force: true }) };
}
test("result is source/context/cut-bound and strips private filesystem paths", () => {
  const f = evidence();
  try {
    const result = completedStatus(f.request, f.terminal, true);
    assert.equal(result.groups[0].sampledFrames, 5); assert.equal(result.writesGrade, false);
    assert(!JSON.stringify(result).includes(f.root));
    f.result.groups[0].retainedIntervals[0].sourceEnd = 91; f.publish();
    assert.throws(() => completedStatus(f.request, f.terminal, true), /retained intervals/);
  } finally { f.cleanup(); }
});
test("re-sealed unknown lighting proposal, changed source SHA and duplicate source groups are rejected", () => {
  const f = evidence();
  try {
    f.result.groups[0].suggestions = [{ kind: "review-normalized-luma-offset", value: 0.02, applicableToPlan: false,
      requiresOperatorComparison: true, confidence: "screening-only" }]; f.publish();
    assert.throws(() => completedStatus(f.request, f.terminal, true), /Unsupported context/);
    f.result.groups[0].suggestions = []; f.result.sources[0].sha256 = "f".repeat(64); f.publish();
    assert.throws(() => completedStatus(f.request, f.terminal, true), /source\/parent/);
    f.result.sources[0].sha256 = "a".repeat(64); f.result.groups.push(f.result.groups[0]); f.publish();
    assert.throws(() => completedStatus(f.request, f.terminal, true), /source closure/);
  } finally { f.cleanup(); }
});
test("cleanup aggregation is sticky across an uncertain first source then a successful second", () => {
  const script = path.join(process.cwd(), "src/app/api/producer/color-diagnostic/worker.py");
  const code = "import importlib.util,sys; s=importlib.util.spec_from_file_location('owned',sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); t=m.CleanupTracker(); t.record(t.verified,False); t.record(t.verified,True); assert t.verified is False";
  const result = spawnSync(path.join(process.cwd(), ".venv/bin/python"), ["-c", code, script], { timeout: 5000, encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
});
