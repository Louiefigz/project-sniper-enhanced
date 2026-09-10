import assert from "node:assert/strict";
import { mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { test } from "node:test";
import { CutPreviewProcessError, runCutPreviewProcess } from "@/app/api/producer/auto-edit/cut-preview-process";
import { assertBodyOwnedOutcome, bodyNestedOwnership } from "../guided-body-process";
import { invokeStoppedBodyCleanup, bodyCleanupCanCommit } from "../guided-body-cleanup";
import { ownedProcessLedgerPath } from "../guided-opening-process-ledger";

const child = { command: process.execPath, args: ["-e", "process.stdout.write('TEST owned child')"],
  cwd: process.cwd(), env: { PATH: process.env.PATH, NODE_ENV: "test" as const } };

test("actual tiny body child and command observer accept only their separate bounded purposes", async () => {
  for (const [purpose, cap] of [["guided-body", 3_300_000], ["guided-body-command", 3_610_000]] as const) {
    assert.throws(() => runCutPreviewProcess({ ...child, purpose, timeoutMs: cap + 1 }), /bounded POSIX/);
    const result = await runCutPreviewProcess({ ...child, purpose, timeoutMs: cap });
    assert.equal(result.stdout, "TEST owned child"); assert.equal(result.stderr, "");
  }
  assert.throws(() => runCutPreviewProcess({ ...child, purpose: "guided-opening", timeoutMs: 3_300_000 }), /bounded POSIX/);
  assert.throws(() => runCutPreviewProcess({ ...child, purpose: "guided-body", timeoutMs: 1.5 }), /bounded POSIX/);
});

test("actual outer timeout still routes exact named cleanup but cannot clear unknown local ownership", async () => {
  const root = realpathSync(mkdtempSync("/private/tmp/sniper-body-timeout-")), start = new Date().toISOString();
  try {
    let failure: CutPreviewProcessError | undefined;
    try { await runCutPreviewProcess({ ...child, args: ["-e", "setInterval(()=>{},1000)"], purpose: "guided-body", timeoutMs: 100 }); }
    catch (error) { assert.ok(error instanceof CutPreviewProcessError); failure = error; }
    assert.ok(failure); assert.equal(failure.details.timedOut, true); assert.equal(failure.details.groupStopped, true);
    assert.equal(failure.details.forcedStop, true);
    const finishedAt = new Date().toISOString(), row = { ...failure.details, startedAt: start, finishedAt,
      elapsedMs: Date.parse(finishedAt) - Date.parse(start), status: "failed", error: failure.message, ledgerSha256: null };
    assertBodyOwnedOutcome(row, finishedAt, start);
    const ownership = bodyNestedOwnership({ root, row, script: "/TEST/never-rendered.py" });
    assert.match(ownership, /unresolved-forced/);
    let exactCleanupCalls = 0;
    await invokeStoppedBodyCleanup({ receipt: row }, async () => { exactCleanupCalls += 1; return "TEST named Docker reconciliation stub"; });
    assert.equal(exactCleanupCalls, 1);
    assert.equal(bodyCleanupCanCommit({ ownershipUnresolved: true }, { ownershipUnresolved: false }), false);
    assert.equal(bodyCleanupCanCommit({ ownershipUnresolved: false }, { ownershipUnresolved: true }), false);
    // Actual POSIX timeout/stop above; Docker callback is explicitly TEST-only. No container/media claim is minted.
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("unproved outer stop blocks cleanup; absent, truncated or malformed local ledgers never prove absence", async () => {
  let calls = 0;
  for (const groupStopped of [false, null, undefined, "true"]) {
    await assert.rejects(invokeStoppedBodyCleanup({ receipt: { groupStopped } }, async () => { calls += 1; }), /unproved/);
  }
  assert.equal(calls, 0);
  const root = realpathSync(mkdtempSync("/private/tmp/sniper-body-ledger-fault-"));
  try {
    const row = { forcedStop: false, ledgerSha256: "a".repeat(64) }, script = "/TEST/never-rendered.py";
    assert.match(bodyNestedOwnership({ root, row, script }), /unresolved-ledger/);
    for (const bytes of ["", "{", "{}\n", "null\n"]) {
      writeFileSync(ownedProcessLedgerPath(root, "media"), bytes);
      assert.match(bodyNestedOwnership({ root, row, script }), /unresolved-ledger/);
    }
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("forced failure remains distinct from complete, unbounded, contradictory or unproved outcomes", () => {
  const at = "2026-09-07T12:00:00.000Z", row = { startedAt: at, finishedAt: at, elapsedMs: 100, status: "failed",
    groupStopped: true, forcedStop: true, timedOut: true, error: "TEST timeout", stdout: "", stderr: "" };
  assert.doesNotThrow(() => assertBodyOwnedOutcome(row, at, at));
  for (const patch of [{ groupStopped: false }, { forcedStop: false }, { status: "complete", error: "" },
    { elapsedMs: 3_310_001 }, { elapsedMs: NaN }, { finishedAt: "2026-09-07T11:59:59.999Z" }]) {
    assert.throws(() => assertBodyOwnedOutcome({ ...row, ...patch }, at, at));
  }
});
