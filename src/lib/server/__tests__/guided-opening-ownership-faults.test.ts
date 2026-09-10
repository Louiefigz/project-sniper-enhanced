import assert from "node:assert/strict";
import childProcess from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { liveRecordedDescendants, ownedProcessLedgerPath, parseEtime, type ProcessProbe } from "../guided-opening-process-ledger";
import { cleanupPointerAfterStop } from "../guided-opening-cleanup";

function fixture() {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sniper-ownership-fault-")));
  const file = ownedProcessLedgerPath(root, "media");
  fs.writeFileSync(file, [
    { event: "intent", pid: null, argv0: "/TEST/ffprobe", at: 100 },
    { event: "spawned", pid: 123456, argv0: "/TEST/ffprobe", at: 100 },
  ].map((row) => JSON.stringify(row)).join("\n") + "\n");
  return { root, file, cleanup: () => fs.rmSync(root, { recursive: true, force: true }) };
}

function assertUnresolved(observed: ReturnType<typeof liveRecordedDescendants>): void {
  assert.equal(observed.unknown.length, 1, "an unobservable pid must remain unknown");
  const pointer = { schemaVersion: 2 as const, cutDecisionHash: "a".repeat(64), cutActivationHash: "a".repeat(64),
    pictureLockedRevisionHash: "a".repeat(64), openingExecutionClaimHash: "b".repeat(64), openingProcessOutcomeHash: "c".repeat(64) };
  const result = cleanupPointerAfterStop(pointer, "d".repeat(64), { receipt: { forcedStop: false },
    nestedOwnership: observed.unknown.length ? "unresolved-unknown-descendant" : "resolved-by-normal-return" });
  assert.equal(result.claimRetained, true);
  assert.equal(result.pointer.openingExecutionClaimHash, pointer.openingExecutionClaimHash);
  assert.equal(result.pointer.openingProcessOutcomeHash, pointer.openingProcessOutcomeHash);
}

test("actual ps error decoding preserves the claim: timeout, diagnostic exit, empty, malformed and multiple rows", (t) => {
  const f = fixture();
  let reply: Record<string, unknown>;
  t.mock.method(childProcess, "spawnSync", () => reply);
  try {
    for (reply of [
      { error: Object.assign(new Error("TEST timeout"), { code: "ETIMEDOUT" }), status: null, stdout: "", stderr: "" },
      { status: 1, stdout: "", stderr: "ps: TEST permission denied" },
      { status: null, signal: "SIGKILL", stdout: "", stderr: "" },
      { status: 0, stdout: "", stderr: "" },
      { status: 0, stdout: "00:30\n", stderr: "" },
      { status: 0, stdout: "00:99 /TEST/ffprobe", stderr: "" },
      { status: 0, stdout: "00:30 /OTHER/program\n00:30 /TEST/ffprobe", stderr: "" },
      { status: 0, stdout: "00:30 /OTHER/program", stderr: "" },
      { status: 0, stdout: "99:00 /TEST/ffprobe", stderr: "" },
    ]) assertUnresolved(liveRecordedDescendants(f.root, "media", undefined, 130));
  } finally { f.cleanup(); }
});

test("ps no-match needs a corroborating ESRCH; permission failure and a still-live pid are not absence", (t) => {
  const f = fixture();
  t.mock.method(childProcess, "spawnSync", () => ({ status: 1, signal: null, stdout: "", stderr: "" }));
  const kill = t.mock.method(process, "kill", () => true);
  try {
    assertUnresolved(liveRecordedDescendants(f.root, "media"));
    kill.mock.mockImplementation(() => { throw Object.assign(new Error("TEST inaccessible"), { code: "EPERM" }); });
    assertUnresolved(liveRecordedDescendants(f.root, "media"));
    kill.mock.mockImplementation(() => { throw Object.assign(new Error("TEST absent"), { code: "ESRCH" }); });
    assert.deepEqual(liveRecordedDescendants(f.root, "media"), { live: [], unknown: [], unrecordedSpawns: [] });
    for (const call of kill.mock.calls) assert.deepEqual(call.arguments, [123456, 0]);
  } finally { f.cleanup(); }
});

test("thrown and malformed injected process observations remain unknown and do not stop later pid checks", () => {
  const f = fixture();
  try {
    for (const probe of [() => { throw new Error("TEST probe failure"); }, () => null, () => ({}),
      () => ({ state: "running", elapsedS: NaN, command: "/TEST/ffprobe" }),
      () => ({ state: "running", elapsedS: -1, command: "/TEST/ffprobe" }),
      () => ({ state: "running", elapsedS: 1, command: "" })]) {
      assertUnresolved(liveRecordedDescendants(f.root, "media", probe as unknown as ProcessProbe, 130));
    }
    fs.appendFileSync(f.file, JSON.stringify({ event: "spawned", pid: 123457, argv0: "/TEST/ffprobe", at: 100 }) + "\n");
    const observed = liveRecordedDescendants(f.root, "media", (pid) => {
      if (pid === 123456) throw new Error("TEST first pid unavailable");
      return { state: "running", elapsedS: 30, command: "/TEST/ffprobe" };
    }, 130);
    assert.equal(observed.unknown.length, 1); assert.deepEqual(observed.live.map((row) => row.pid), [123457]);
  } finally { f.cleanup(); }
});

test("ledger access failures cannot be converted to missing by existsSync, and existing empty/torn/linked ledgers reject", (t) => {
  const f = fixture();
  try {
    t.mock.method(fs, "existsSync", () => false);
    assertUnresolved(liveRecordedDescendants(f.root, "media", () => ({ state: "unknown", reason: "TEST" })));
    for (const contents of ["", "\n", '{"event":"intent","pid":null,"argv0":"/TEST/ffprobe","at":100}']) {
      fs.writeFileSync(f.file, contents);
      assert.throws(() => liveRecordedDescendants(f.root, "media"), /ledger|artifact/);
    }
    fs.unlinkSync(f.file); fs.symlinkSync(path.join(f.root, "missing-target"), f.file);
    assert.throws(() => liveRecordedDescendants(f.root, "media"));
  } finally { f.cleanup(); }
});

test("invalid elapsed clock fields are rejected rather than proving an older unrelated process", () => {
  for (const value of ["00:60", "60:00", "24:00:00", "1-99:00:00", "999999999999999999999999-00:00:00"]) {
    assert.throws(() => parseEtime(value));
  }
});

test("ledger permission and same-path read failures propagate without allowing a claimed absence", (t) => {
  const f = fixture(), original = fs.lstatSync;
  t.mock.method(fs, "lstatSync", (...args: Parameters<typeof fs.lstatSync>) => {
    if (args[0] === f.file) throw Object.assign(new Error("TEST ledger permission denied"), { code: "EACCES" });
    return original(...args);
  });
  try { assert.throws(() => liveRecordedDescendants(f.root, "media"), /TEST ledger permission denied/); }
  finally { t.mock.restoreAll(); f.cleanup(); }
});

test("a mismatched, orphaned or out-of-order reap cannot hide an unreaped recorded process", () => {
  const f = fixture(), spawned = { event: "spawned", pid: 123456, argv0: "/TEST/ffprobe", at: 100 };
  try {
    for (const rows of [[spawned, { ...spawned, event: "reaped", argv0: "/OTHER/program" }],
      [spawned, { ...spawned, event: "reaped", at: 99 }], [spawned, spawned], [{ ...spawned, event: "reaped" }]]) {
      fs.writeFileSync(f.file, rows.map((row) => JSON.stringify(row)).join("\n") + "\n");
      assert.throws(() => liveRecordedDescendants(f.root, "media"), /owned process ledger/);
    }
  } finally { f.cleanup(); }
});
