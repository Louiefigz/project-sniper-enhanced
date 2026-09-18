import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import childProcess, { execFileSync } from "node:child_process";
import { readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { canonicalJson, canonicalJsonSha256 } from "../auto-edit-hash";
import { openingPythonIdentity, readStoppedOpeningProcess } from "../guided-opening-process";
import { openingProcessFixture as fixture } from "./_guided-opening-process-fixture";
import { assertCleanupOwnershipFresh, cleanupPointerAfterStop } from "../guided-opening-cleanup";
import { commitGuidedJob } from "../guided-cut-v2";
import { autoEditJobPath } from "../auto-edit-job-persistence";

const HASH = "a".repeat(64);

test("v2 normal stop requires the exact separately held completed worker ledger; missing/torn/resealed bytes never clear ownership", () => {
  const f = fixture({}, 2);
  try {
    f.write(); assert.equal(readStoppedOpeningProcess(f.held).nestedOwnership, "resolved-by-normal-return");
    const file = path.join(f.root, "owned-process-ledger.media.jsonl"), bytes = readFileSync(file);
    const job = autoEditJobPath(f.held.job.ctx.dir); writeFileSync(job, canonicalJson(f.held.job)); const heldJob = readFileSync(job);
    for (const changed of [Buffer.alloc(0), bytes.subarray(0, bytes.length - 1), Buffer.from(bytes.toString().replace("123456", "123457"))]) {
      writeFileSync(file, changed); assert.throws(() => readStoppedOpeningProcess(f.held)); assert.deepEqual(readFileSync(job), heldJob);
    }
    rmSync(file); assert.throws(() => readStoppedOpeningProcess(f.held)); assert.deepEqual(readFileSync(job), heldJob);
  } finally { f.cleanup(); }
});

test("retained stopped-outcome parser binds exact start/claim/input/journal; this is protocol-only not a live process fixture", () => {
  const f = fixture();
  try {
    f.write(); assert.equal(readStoppedOpeningProcess(f.held).resourceAbsence, "not-observed");
    for (const patch of [{ claimHash: "b".repeat(64) }, { inputSha256: "b".repeat(64) }, { executionId: randomUUID() },
      { groupStopped: false }, { groupStopped: "true" }, { forcedStop: "false" }, { timedOut: true }, { intentHash: "b".repeat(64) }, { elapsedMs: -1 }, { elapsedMs: Infinity },
      { finishedAt: "2026-09-06T11:00:00.000Z" }, { status: "complete" }, { mediaApproved: true },
      { stdout: "x".repeat(2 * 1024 * 1024 + 1) }]) {
      assert.throws(() => { f.write(f.intent, { ...f.outcome, ...patch } as typeof f.outcome); readStoppedOpeningProcess(f.held); });
    }
  } finally { f.cleanup(); }
});

test("missing media ledger cannot turn a held stopped outcome into proved ownership or clear journal bytes", () => {
  const f = fixture();
  try {
    f.write(); const file = autoEditJobPath(f.held.job.ctx.dir);
    writeFileSync(file, canonicalJson(f.held.job)); const before = readFileSync(file);
    rmSync(path.join(f.root, "owned-process-ledger.media.jsonl"));
    assert.throws(() => readStoppedOpeningProcess(f.held), /ownership is unproved and requires manual recovery/);
    assert.deepEqual(readFileSync(file), before);
  } finally { f.cleanup(); }
});

test("resealed intent cannot move a retained process to another journal/clock/script or invent start time", () => {
  const f = fixture();
  try {
    for (const patch of [{ journalHash: "b".repeat(64) }, { clockHash: "b".repeat(64) }, { executionId: randomUUID() },
      { startedAt: "2026-09-06T11:59:59.000Z" }, { tools: { ...f.intent.tools, script: "/private/tmp/OTHER.py" } },
      { tools: { ...f.intent.tools, scriptHash: "b".repeat(64) } }, { claimedGroupStopped: true }]) {
      const intent = { ...f.intent, ...patch };
      f.write(intent, { ...f.outcome, intentHash: canonicalJsonSha256(intent) });
      assert.throws(() => readStoppedOpeningProcess(f.held));
    }
  } finally { f.cleanup(); }
});

test("crash before durable outcome remains explicitly unresolved; a missing stop receipt never becomes empty cleanup", () => {
  const f = fixture();
  try { writeFileSync(path.join(f.root, "media-process-intent.json"), JSON.stringify(f.intent)); assert.throws(() => readStoppedOpeningProcess(f.held)); }
  finally { f.cleanup(); }
});

test("mutually resealed sidecars without separately journal-held actual outcome authority remain rejected", () => {
  const f = fixture();
  try {
    f.write(); delete f.held.job.guidedHandoffV2!.openingProcessOutcomeHash;
    assert.throws(() => readStoppedOpeningProcess(f.held), /No durable actual opening process outcome/);
  } finally { f.cleanup(); }
});

test("actual private worker command retains venv prefix and cv2/numpy/scipy imports instead of invoking the resolved base executable", () => {
  const held = openingPythonIdentity(); assert.notEqual(held.python, held.pythonResolved);
  const raw = execFileSync(held.python, ["-B", "-c", "import json,sys,cv2,numpy,scipy; print(json.dumps({'prefix':sys.prefix,'base':sys.base_prefix}))"],
    { encoding: "utf8", timeout: 15_000, env: { ...process.env, PYTHONHOME: undefined, PYTHONNOUSERSITE: "1" } });
  const observed = JSON.parse(raw); assert.equal(observed.prefix, held.venvRoot); assert.notEqual(observed.prefix, observed.base);
});

test("a live pid the worker itself recorded keeps a normal return unresolved until it is gone", async () => {
  const { spawn } = await import("node:child_process");
  const normal = fixture(), child = spawn("/bin/sleep", ["30"], { stdio: "ignore" });
  try {
    await new Promise((resolve) => child.on("spawn", resolve));
    normal.write();
    writeFileSync(path.join(normal.root, "owned-process-ledger.media.jsonl"), JSON.stringify({ event: "spawned", pid: child.pid, argv0: "/bin/sleep", at: Date.now() / 1000 }) + "\n");
    const live = readStoppedOpeningProcess(normal.held);
    assert.equal(live.nestedOwnership, "unresolved-live-recorded-descendant"); assert.deepEqual(live.liveDescendants.map((row) => row.pid), [child.pid]);
    child.kill("SIGKILL"); await new Promise((resolve) => child.on("exit", resolve));
    assert.equal(readStoppedOpeningProcess(normal.held).nestedOwnership, "resolved-by-normal-return");
    writeFileSync(path.join(normal.root, "owned-process-ledger.media.jsonl"), JSON.stringify({ event: "intent", pid: null, argv0: "/TEST/ffprobe", at: Date.now() / 1000 }) + "\n");
    const unknown = readStoppedOpeningProcess(normal.held);
    assert.equal(unknown.nestedOwnership, "unresolved-unrecorded-spawn"); assert.deepEqual(unknown.unrecordedSpawns, ["/TEST/ffprobe"]);
  } finally { child.kill("SIGKILL"); normal.cleanup(); }
});

test("a forced outer stop is retained as unresolved nested ownership, never a complete or selectable outcome", () => {
  const forced = fixture({ forcedStop: true, timedOut: true, error: "cut preview process-group deadline exceeded" });
  const normal = fixture(), fakeComplete = fixture({ status: "complete", error: "", forcedStop: true });
  try {
    forced.write(); assert.equal(readStoppedOpeningProcess(forced.held).nestedOwnership, "unresolved-forced-outer-stop");
    normal.write(); assert.equal(readStoppedOpeningProcess(normal.held).nestedOwnership, "resolved-by-normal-return");
    fakeComplete.write(); assert.throws(() => readStoppedOpeningProcess(fakeComplete.held), /absent, ambiguous or changed/);
  } finally { forced.cleanup(); normal.cleanup(); fakeComplete.cleanup(); }
});

test("actual journal CAS preserves claim bytes when the final live ownership read becomes unknown", (t) => {
  const f = fixture(); let uncertain = false, checks = 0;
  t.mock.method(childProcess, "spawnSync", () => uncertain
    ? { status: 1, stdout: "", stderr: "TEST ps observation unavailable" }
    : { status: 1, stdout: "", stderr: "" });
  t.mock.method(process, "kill", () => { throw Object.assign(new Error("TEST absent"), { code: "ESRCH" }); });
  try {
    f.write();
    writeFileSync(path.join(f.root, "owned-process-ledger.media.jsonl"), [
      { event: "intent", pid: null, argv0: "/TEST/ffprobe", at: 100 },
      { event: "spawned", pid: 123456, argv0: "/TEST/ffprobe", at: 100 },
    ].map((row) => JSON.stringify(row)).join("\n") + "\n");
    const initial = readStoppedOpeningProcess(f.held), file = autoEditJobPath(f.held.job.ctx.dir);
    assert.equal(initial.nestedOwnership, "resolved-by-normal-return");
    writeFileSync(file, canonicalJson(f.held.job)); const before = readFileSync(file);
    const policy = cleanupPointerAfterStop(f.held.job.guidedHandoffV2!, HASH, initial);
    assert.throws(() => commitGuidedJob({ beforeHash: canonicalJsonSha256(f.held.job),
      job: { ...f.held.job, guidedHandoffV2: policy.pointer }, guard: () => {
        uncertain = ++checks === 2;
        assertCleanupOwnershipFresh(initial, readStoppedOpeningProcess(f.held));
      } }), /became unresolved/);
    assert.equal(checks, 2); assert.deepEqual(readFileSync(file), before);
  } finally { f.cleanup(); }
});
