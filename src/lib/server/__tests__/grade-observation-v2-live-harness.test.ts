/** Inert real-file protocol tests, never genuine admission or media evidence. */
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import type { GradeProcessResult } from "../grade-observation-process";
import { assertLiveReturn, assertResult, fixtureProducer, PROFILE, PROJECT_POLICY, v2Input, workerArgs, WORK_NS }
  from "../../../../scripts/producer/tests/live_grade_v2_contract";

const UUID = "7758dfae-d894-4845-9bc5-b6870715640d";
function inputFixture() {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "grade-v2-protocol-")));
  const dir = path.join(root, "producer"); fs.mkdirSync(dir);
  for (const file of [path.join(root, "project.json"), path.join(dir, "edit_plan.json"), path.join(dir, "asset_manifest.json")])
    fs.writeFileSync(file, "{}\n");
  return { root, dir, input: v2Input(dir, UUID, "a".repeat(64)) };
}
function resultFor(input: ReturnType<typeof v2Input>): Record<string, unknown> {
  const body = { schemaVersion: 2, policy: PROJECT_POLICY, profile: PROFILE, limits: {}, jobId: input.jobId,
    inputSha256: "b".repeat(64), status: "complete", cleanupVerified: true, cleanupMs: 1, workerPhaseMs: 1,
    replayMs: 1, gradeApplicable: false, deliveryApproved: false, parentsSha256: "c".repeat(64),
    implementation: [], elapsedMs: 3, observation: {
      source: { sourceId: "raw-1", fps: "24000/1001", frameCount: 24,
        declarationSha256: canonicalJsonSha256(input.declaration) }, decodedFrames: 24, width: 3840, height: 2160,
      firstPts: 0, timeBase: "1/24000", stepTicks: 1001, gradeApplicable: false, deliveryApproved: false,
      sourceMetadata: { profile: PROFILE, transfer: "iec61966-2-4", transformApplicable: false } } };
  return { ...body, artifactHash: canonicalJsonSha256(body) };
}
test("TEST invocation always supplies explicit V2 profile and the live held input SHA", () => {
  const args = workerArgs("/root/worker.py", "/owned/attempt", "a".repeat(64));
  assert.deepEqual(args, ["-I", "-S", "-B", "/root/worker.py", "/owned/attempt/input.json", "a".repeat(64), "--profile", PROFILE]);
  assert.throws(() => workerArgs("relative.py", "/owned", "a".repeat(64)));
  assert.throws(() => workerArgs("/worker.py", "/owned", "unknown"));
  assert.equal(WORK_NS, BigInt(120_000_000_000));
});
test("actual owner input has current parent hashes and explicit unknown camera/history; no inherited V1", () => {
  const f = inputFixture();
  try {
    assert.equal(f.input.ownerPid, process.pid); assert.equal(f.input.schemaVersion, 2);
    assert.equal(f.input.profile, PROFILE); assert.equal(f.input.declaration.historyState, "unknown");
    assert.equal(f.input.declaration.lightingGroups[0].endFrame, 24);
    fs.writeFileSync(path.join(f.dir, "edit_plan.json"), '{"changed":true}');
    assert.notEqual(v2Input(f.dir, UUID, "a".repeat(64)).expected.planSha256, f.input.expected.planSha256);
    assert.throws(() => v2Input(f.dir, "wrong", "a".repeat(64)));
  } finally { fs.rmSync(f.root, { recursive: true }); }
});
test("creator directories and unmarked ordinary metadata cannot enter opt-in fixture owner", () => {
  const f = inputFixture();
  try { assert.throws(() => fixtureProducer(f.dir), /TEST producer/); }
  finally { fs.rmSync(f.root, { recursive: true }); }
});
test("normal exit, exact live receipt, group absence and cleanup are independently mandatory", () => {
  const held: GradeProcessResult = { resultSha256: "a".repeat(64), status: "complete", cleanupVerified: true,
    handshake: { remainingMs: 119000, startupMs: 1000 } };
  const closed = { code: 0, signal: null, absent: true };
  assertLiveReturn(held, closed);
  for (const change of [{ status: "failed" as const }, { cleanupVerified: false }, { resultSha256: null }, { handshake: null }])
    assert.throws(() => assertLiveReturn({ ...held, ...change }, closed));
  for (const change of [{ code: 1 }, { signal: "SIGKILL" }, { absent: false }])
    assert.throws(() => assertLiveReturn(held, { ...closed, ...change }));
});
test("whole original frame clock and transfer cannot be upgraded from self-consistent wrong result", () => {
  const f = inputFixture();
  try {
    const good = resultFor(f.input);
    assertResult(good, f.input, "b".repeat(64));
    for (const change of [{ schemaVersion: 1 }, { extra: true }, { gradeApplicable: true }, { inputSha256: "d".repeat(64) }]) {
      const body: Record<string, unknown> = { ...good, ...change }; delete body.artifactHash;
      assert.throws(() => assertResult({ ...body, artifactHash: canonicalJsonSha256(body) }, f.input, "b".repeat(64)));
    }
    const bad = resultFor(f.input), observed = bad.observation as Record<string, unknown>;
    observed.decodedFrames = 12;
    const body = { ...bad }; delete body.artifactHash;
    assert.throws(() => assertResult({ ...body, artifactHash: canonicalJsonSha256(body) }, f.input, "b".repeat(64)));
  } finally { fs.rmSync(f.root, { recursive: true }); }
});
