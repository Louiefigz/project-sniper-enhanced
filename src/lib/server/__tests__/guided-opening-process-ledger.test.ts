import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { liveRecordedDescendants, ownedProcessLedgerPath, parseEtime, readOwnedProcessLedger, unreapedRows,
  unrecordedSpawns, observeOwnedWorkerLedger, type ProcessProbe } from "../guided-opening-process-ledger";

function ledger(root: string, rows: Record<string, unknown>[]): void {
  writeFileSync(ownedProcessLedgerPath(root, "media"), rows.map((row) => JSON.stringify(row)).join("\n") + "\n");
}

test("worker lifecycle rejects unmatched endpoints, nested starts, skipped intents, rewound time and mutated held bytes", () => {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-ledger-lifecycle-")));
  const first = { event: "worker-started", pid: 42, argv0: "/TEST/worker.py", at: 100 };
  const last = { ...first, event: "worker-finished", at: 101 };
  try {
    ledger(root, [first, last]); const held = observeOwnedWorkerLedger(root, "media", first.argv0);
    for (const rows of [[first], [last], [first, { ...last, pid: 43 }], [first, { ...last, argv0: "/OTHER.py" }],
      [first, first, last], [first, { ...last, at: 99 }], [first, { ...first, event: "spawned" }, last]]) {
      ledger(root, rows); assert.throws(() => observeOwnedWorkerLedger(root, "media", first.argv0));
    }
    ledger(root, [first, { ...last, at: 102 }]); assert.throws(() => observeOwnedWorkerLedger(root, "media", first.argv0, held), /bytes changed/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("etime covers mm:ss, hh:mm:ss and dd-hh:mm:ss; anything else is refused", () => {
  assert.equal(parseEtime("00:07"), 7); assert.equal(parseEtime("01:02:03"), 3723); assert.equal(parseEtime("2-01:00:00"), 176_400);
  assert.throws(() => parseEtime("7")); assert.throws(() => parseEtime(""));
});

test("ledgers are per invocation kind; torn, foreign or relative rows are never skipped; reaped closes spawned", () => {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-ledger-")));
  try {
    assert.throws(() => readOwnedProcessLedger(root, "media"), /ownership is unproved/);
    ledger(root, [{ event: "intent", pid: null, argv0: "/TEST/ffprobe", at: 9 }, { event: "spawned", pid: 41, argv0: "/TEST/ffprobe", at: 10 },
      { event: "intent", pid: null, argv0: "/TEST/docker", at: 10.5 }, { event: "spawned", pid: 42, argv0: "/TEST/docker", at: 11 },
      { event: "reaped", pid: 41, argv0: "/TEST/ffprobe", at: 12, returncode: 0 }]);
    assert.deepEqual(unreapedRows(readOwnedProcessLedger(root, "media")).map((row) => row.pid), [42]);
    assert.deepEqual(readOwnedProcessLedger(root, "cleanup"), []);   // a cleanup child never poisons the media stop
    for (const bad of ['{"event":"spawned","pid":1,"argv0":"ffprobe","at":1}', '{"event":"exited","pid":1,"argv0":"/x","at":1}',
      '{"event":"spawned"', '{"event":"intent","pid":7,"argv0":"/x","at":1}', '{"event":"spawned","pid":null,"argv0":"/x","at":1}']) {
      writeFileSync(ownedProcessLedgerPath(root, "media"), `${bad}\n`);
      assert.throws(() => readOwnedProcessLedger(root, "media"), /ledger row/);
    }
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("an intent without its spawned row is an unknown child, never an absent one", () => {
  const rows = [{ event: "intent" as const, pid: null, argv0: "/TEST/ffprobe", at: 1 }, { event: "spawned" as const, pid: 5, argv0: "/TEST/ffprobe", at: 1 },
    { event: "intent" as const, pid: null, argv0: "/TEST/docker", at: 2 }];
  assert.deepEqual(unrecordedSpawns(rows), ["/TEST/docker"]);
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-ledger-intent-")));
  try {
    ledger(root, rows);
    const observed = liveRecordedDescendants(root, "media", () => ({ state: "absent" }), 10);
    assert.deepEqual(observed, { live: [], unknown: [], unrecordedSpawns: ["/TEST/docker"] });
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("a recorded pid stays ours while alive; older or foreign process observations remain uncertain", () => {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-ledger-live-")));
  try {
    const now = 1_000_000, at = now - 30;
    ledger(root, [101, 102, 103, 104, 105].map((pid) => ({ event: "spawned", pid, argv0: "/Users/x/My Projects/.venv/bin/python3", at })));
    const probe: ProcessProbe = (pid) => ({
      101: { state: "running" as const, elapsedS: 31, command: "/Users/x/My Projects/.venv/bin/python3 -c pass" },   // ours
      102: { state: "running" as const, elapsedS: 31, command: "/usr/bin/vim x" },                                    // pid reused by a foreign program
      103: { state: "running" as const, elapsedS: 900, command: "/Users/x/My Projects/.venv/bin/python3 -c pass" },   // started long before the spawn: reused
      104: { state: "running" as const, elapsedS: 40, command: "/Users/x/My Projects/.venv/bin/python3" },            // 10 s of clock skew: still ours
    }[pid] ?? { state: "absent" as const });
    const observed = liveRecordedDescendants(root, "media", probe, now);
    assert.deepEqual(observed.live.map((row) => row.pid), [101, 104]); assert.deepEqual(observed.unknown.map((row) => row.pid), [102, 103]);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("the real ps probe sees an actual recorded child while it lives and not after it is gone", async () => {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-ledger-ps-")));
  const child = spawn("/bin/sleep", ["30"], { stdio: "ignore" });
  try {
    await new Promise((resolve) => child.on("spawn", resolve));
    ledger(root, [{ event: "intent", pid: null, argv0: "/bin/sleep", at: Date.now() / 1000 }, { event: "spawned", pid: child.pid, argv0: "/bin/sleep", at: Date.now() / 1000 }]);
    assert.deepEqual(liveRecordedDescendants(root, "media").live.map((row) => row.pid), [child.pid]);
    child.kill("SIGKILL");
    await new Promise((resolve) => child.on("exit", resolve));
    assert.deepEqual(liveRecordedDescendants(root, "media"), { live: [], unknown: [], unrecordedSpawns: [] });
  } finally { child.kill("SIGKILL"); rmSync(root, { recursive: true, force: true }); }
});

test("a probe that cannot observe a recorded pid reports it unknown, never absent", () => {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-ledger-unknown-")));
  try {
    ledger(root, [{ event: "spawned", pid: 7, argv0: "/TEST/ffprobe", at: 100 }, { event: "spawned", pid: 8, argv0: "/TEST/docker", at: 100 }]);
    const probe: ProcessProbe = (pid) => pid === 7 ? { state: "unknown", reason: "ps timed out" } : { state: "absent" };
    const observed = liveRecordedDescendants(root, "media", probe, 130);
    assert.deepEqual(observed.live, []); assert.deepEqual(observed.unknown, [{ pid: 7, argv0: "/TEST/ffprobe", reason: "ps timed out" }]);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
