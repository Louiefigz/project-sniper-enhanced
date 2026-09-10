/** Real metadata files and actual finalizer branches; no child/daemon/media job. */
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { readBytes, sha } from "../../../app/api/producer/studio/import/files";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { writeRecord } from "../grade-observation-store";
import { v2Input, PROFILE, PROJECT_POLICY } from "../../../../scripts/producer/tests/live_grade_v2_contract";
import { assertCleanupReturn, finalizeV2Success, readCleanupProof, releaseV2Failed,
  type V2FinalChecks, type V2Finalization, type V2LiveReturn }
  from "../../../../scripts/producer/tests/live_grade_v2_finalization";

const UUID = "7758dfae-d894-4845-9bc5-b6870715640d";
function fixture(status: "complete" | "failed" = "complete") {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "grade-v2-finalize-TEST-")));
  fs.chmodSync(root, 0o700);
  const dir = path.join(root, "producer"); fs.mkdirSync(dir, { mode: 0o700 });
  for (const name of [path.join(root, "project.json"), path.join(dir, "edit_plan.json"), path.join(dir, "asset_manifest.json")])
    fs.writeFileSync(name, "{}\n");
  const input = v2Input(dir, UUID, "a".repeat(64));
  const inputHash = writeRecord(path.join(dir, "input.json"), input);
  const body = { schemaVersion: 2, policy: PROJECT_POLICY, profile: PROFILE, limits: {}, jobId: UUID,
    inputSha256: inputHash, status, cleanupVerified: true, cleanupMs: 3, workerPhaseMs: 5,
    replayMs: 0, gradeApplicable: false, deliveryApproved: false, elapsedMs: 8,
    ...(status === "failed" ? { errors: ["TEST decode failure"] } : {}) };
  const resultHash = writeRecord(path.join(dir, "observation.json"), { ...body, artifactHash: canonicalJsonSha256(body) });
  const claimHash = writeRecord(path.join(root, "active.json"), { jobId: UUID, dir, requestDigest: inputHash });
  const candidateHash = writeRecord(path.join(dir, "TEST-result.json"), { status: "candidate-only" });
  const live: V2LiveReturn = { held: { status, cleanupVerified: true, resultSha256: resultHash,
    handshake: { remainingMs: 110000, startupMs: 1 } }, closed: { code: 0, signal: null, absent: true },
    pid: 12345, stdout: "TEST", stderr: "" };
  const values: V2Finalization = { live, input: { path: path.join(dir, "input.json"), sha256: inputHash },
    result: { path: path.join(dir, "observation.json"), sha256: resultHash },
    claim: { path: path.join(root, "active.json"), sha256: claimHash },
    candidate: { path: path.join(dir, "TEST-result.json"), sha256: candidateHash }, deadline: BigInt(100) };
  let now = BigInt(1);
  const checks: V2FinalChecks = { ownership: () => {}, parents: () => {
    assert.equal(fs.readFileSync(path.join(dir, "edit_plan.json"), "utf8"), "{}\n");
  }, proof: () => { readCleanupProof(dir, input, inputHash, live); }, time: deadline => {
    if (now >= deadline) throw new Error("TEST original deadline expired");
  } };
  return { root, dir, input, inputHash, live, values, checks, advance: () => { now = BigInt(100); } };
}
function remove(root: string): void { fs.rmSync(root, { recursive: true }); }

test("normal failed worker retains source failure but can release exact live-proved cleanup", () => {
  const f = fixture("failed");
  try {
    assertCleanupReturn(f.live); readCleanupProof(f.dir, f.input, f.inputHash, f.live);
    assert.throws(() => finalizeV2Success(f.values, f.checks), /normal owner return/);
    releaseV2Failed(f.values, f.checks, "TEST failed worker");
    assert.equal(fs.existsSync(f.values.claim.path), false);
    assert.equal(JSON.parse(fs.readFileSync(f.values.result.path, "utf8")).status, "failed");
    assert.equal(JSON.parse(fs.readFileSync(f.values.candidate!.path, "utf8")).status, "candidate-only");
  } finally { remove(f.root); }
});
test("valid finalization releases matching claim but keeps stored result candidate-only", () => {
  const f = fixture();
  try {
    finalizeV2Success(f.values, f.checks);
    assert.equal(fs.existsSync(f.values.claim.path), false);
    assert.equal(JSON.parse(fs.readFileSync(f.values.candidate!.path, "utf8")).status, "candidate-only");
  } finally { remove(f.root); }
});
test("expired work may use separate bounded cleanup credit without success credit", () => {
  const f = fixture();
  try {
    assert.throws(() => finalizeV2Success({ ...f.values, deadline: BigInt(0) }, f.checks), /deadline/);
    releaseV2Failed(f.values, f.checks, "original work expired");
    assert.equal(fs.existsSync(f.values.claim.path), false);
  } finally { remove(f.root); }
});
test("tool proof or final lease failure preserves the shared fence", () => {
  const f = fixture();
  try {
    f.checks.proof = () => { throw new Error("TEST runtime changed"); };
    assert.throws(() => releaseV2Failed(f.values, f.checks, "failed"), /runtime changed/);
    assert.ok(fs.existsSync(f.values.claim.path));
    f.checks.proof = () => {};
    let calls = 0;
    f.checks.ownership = () => { if (++calls > 1) throw new Error("TEST lost lease"); };
    assert.throws(() => finalizeV2Success(f.values, f.checks), /lost lease/);
    assert.ok(fs.existsSync(f.values.claim.path));
  } finally { remove(f.root); }
});
test("post-verification parent failure permits cleanup only, never success", () => {
  const f = fixture();
  try {
    fs.writeFileSync(path.join(f.dir, "edit_plan.json"), '{"changed":true}');
    assert.throws(() => finalizeV2Success(f.values, f.checks));
    assert.ok(fs.existsSync(f.values.claim.path));
    releaseV2Failed(f.values, f.checks, "TEST changed parent");
    assert.equal(fs.existsSync(f.values.claim.path), false);
  } finally { remove(f.root); }
});
test("mutation during last claim read cannot return successful finalization", () => {
  const f = fixture();
  try {
    f.checks.readHash = file => {
      const held = sha(readBytes(file, 8 * 1024 * 1024));
      if (file === f.values.claim.path) fs.writeFileSync(path.join(f.dir, "edit_plan.json"), '{"late":true}');
      return held;
    };
    assert.throws(() => finalizeV2Success(f.values, f.checks));
    assert.ok(fs.existsSync(f.values.claim.path));
  } finally { remove(f.root); }
});
test("expiry during last claim read retains claim despite earlier valid work checks", () => {
  const f = fixture();
  try {
    f.checks.readHash = file => { const held = sha(readBytes(file, 8 * 1024 * 1024));
      if (file === f.values.claim.path) f.advance(); return held; };
    assert.throws(() => finalizeV2Success(f.values, f.checks), /deadline/);
    assert.ok(fs.existsSync(f.values.claim.path));
  } finally { remove(f.root); }
});
test("missing proof, nonnormal exit and ambiguous group absence retain ownership", () => {
  const f = fixture();
  try {
    for (const change of [{ cleanupVerified: false }, { resultSha256: null }, { status: "interrupted" as const }, { handshake: null }])
      assert.throws(() => assertCleanupReturn({ ...f.live, held: { ...f.live.held, ...change } }));
    for (const closed of [{ code: 1, signal: null, absent: true }, { code: 0, signal: "SIGKILL", absent: true },
      { code: 0, signal: null, absent: false }]) assert.throws(() => assertCleanupReturn({ ...f.live, closed }));
    f.live.held.cleanupVerified = false;
    assert.throws(() => releaseV2Failed(f.values, f.checks, "unknown"));
    assert.ok(fs.existsSync(f.values.claim.path));
  } finally { remove(f.root); }
});
test("changed input/result/claim/candidate bytes cannot finalize success", () => {
  for (const key of ["input", "result", "claim", "candidate"] as const) {
    const f = fixture();
    try {
      fs.chmodSync(f.values[key]!.path, 0o600); fs.writeFileSync(f.values[key]!.path, "{}\n");
      assert.throws(() => finalizeV2Success(f.values, f.checks));
      assert.ok(fs.existsSync(f.values.claim.path));
    } finally { remove(f.root); }
  }
});
test("cleanup-only metadata deadline also cannot be extended by a last read", () => {
  const f = fixture();
  try {
    f.checks.readHash = file => { const held = sha(readBytes(file, 8 * 1024 * 1024));
      if (file === f.values.claim.path) f.advance(); return held; };
    assert.throws(() => releaseV2Failed(f.values, f.checks, "TEST overrun"), /deadline/);
    assert.ok(fs.existsSync(f.values.claim.path));
  } finally { remove(f.root); }
});
