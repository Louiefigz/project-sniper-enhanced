/** TEST metadata/faults only. No daemon, observer, source or approval. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { exactIdentity, groupState, requireStoppedV2, type V2Lifecycle } from "./live_grade_v2_lifecycle";
import { cleanupResult, finishV2Recovery } from "./live_grade_v2_recovery";
import { writeHeldRecord } from "./live_grade_v2_finalization";

test("unknown EPERM and invalid group identifiers never mean absence", t => {
  t.mock.method(process, "kill", () => { throw Object.assign(new Error("TEST denied"), { code: "EPERM" }); });
  assert.equal(groupState(12345), "unknown"); assert.equal(groupState(-1), "unknown");
});
test("only exact ESRCH means an absent group", t => {
  t.mock.method(process, "kill", () => { throw Object.assign(new Error("TEST absent"), { code: "ESRCH" }); });
  assert.equal(groupState(12345), "absent");
});
test("a recycled live leader PID blocks even when its old group is absent", t => {
  const original = exactIdentity(process.pid);
  const value = { supervisor: { ...original, pid: 12345 } } as V2Lifecycle;
  t.mock.method(process, "kill", (target: number) => {
    if (Number(target) < 0) throw Object.assign(new Error("TEST absent group"), { code: "ESRCH" });
    return true;
  });
  assert.throws(() => requireStoppedV2(value), /live or reused/);
});
test("malformed cleanup, wrong names, and no-launch inference are rejected", () => {
  const name = "sniper-grade-observation-" + "a".repeat(32);
  const row = { state: "reconciled", containerName: name, cleanupVerified: true, intentSha256: null,
    removal: { containerRef: name, canonicalAbsenceProved: true } };
  assert.deepEqual(cleanupResult(JSON.stringify(row), name), row);
  for (const delta of [{ state: "not-launched" }, { containerName: "other" }, { cleanupVerified: false }, { extra: true },
    { removal: { containerRef: "other", canonicalAbsenceProved: true } }, { intentSha256: "unbound" }])
    assert.throws(() => cleanupResult(JSON.stringify({ ...row, ...delta }), name));
  assert.throws(() => cleanupResult(JSON.stringify(row) + "\n{}", name));
});
function metadata() {
  const root = fs.mkdtempSync("/private/tmp/TEST-v2-recovery-"), claim = path.join(root, "active.json");
  fs.chmodSync(root, 0o700);
  const claimSha = writeHeldRecord(claim, { exact: "TEST original claim", originalDeadlineNs: "120000000001" });
  const outcome = path.join(root, "actual-return.json"), sha = writeHeldRecord(outcome, { TEST: "not actual media" });
  return { root, claim: { path: claim, sha256: claimSha }, retained: [{ path: outcome, sha256: sha }] };
}
test("final cleanup guard after all reads prevents deadline/lease failure from clearing", () => {
  for (const reason of ["expired original cleanup allowance", "lost resource lease", "group identity became unknown"]) {
    const f = metadata(); let calls = 0;
    try {
      assert.throws(() => finishV2Recovery(f.claim, f.retained, () => { if (++calls === 2) throw new Error(reason); }), new RegExp(reason));
      assert.ok(fs.existsSync(f.claim.path));
    } finally { fs.rmSync(f.root, { recursive: true }); }
  }
});
test("changed exact claim or retained actual return blocks final cleanup", () => {
  for (const which of ["claim", "outcome"]) {
    const f = metadata();
    try {
      const file = which === "claim" ? f.claim.path : f.retained[0].path;
      fs.chmodSync(file, 0o600); fs.writeFileSync(file, "changed");
      assert.throws(() => finishV2Recovery(f.claim, f.retained, () => {}), /changed/);
      assert.ok(fs.existsSync(f.claim.path));
    } finally { fs.rmSync(f.root, { recursive: true }); }
  }
});
test("exact metadata-only finalizer removes only named claim and preserves deadline evidence", () => {
  const f = metadata();
  try {
    const other = path.join(f.root, "unrelated.json"); fs.writeFileSync(other, "keep");
    finishV2Recovery(f.claim, f.retained, () => {});
    assert.equal(fs.existsSync(f.claim.path), false); assert.equal(fs.readFileSync(other, "utf8"), "keep");
    assert.equal(fs.existsSync(f.retained[0].path), true);
  } finally { fs.rmSync(f.root, { recursive: true }); }
});
