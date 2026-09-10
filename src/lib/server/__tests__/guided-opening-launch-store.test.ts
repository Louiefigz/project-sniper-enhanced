import assert from "node:assert/strict";
import test from "node:test";
import { randomUUID } from "node:crypto";
import { mkdtempSync, realpathSync, rmSync, symlinkSync, readFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import os from "node:os";
import { createOpeningLaunchRecord, openingLaunchDirectory, readOpeningLaunchIntent,
  readOpeningLaunchActivation, strictOpeningControllerIdentity, optionalLaunchRecord, assertOpeningControllerTools } from "../guided-opening-launch-store";
import { waitForOpeningHandoff } from "../guided-opening-controller";
import { captureOpeningAttemptStart } from "../opening-deadline";
import { captureProcessIdentity } from "../process-liveness";

/** TEST protocol records only. No proposal, process activation, render or human approval is claimed. */
function fixture() {
  const dir = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-launch-store-"))), journal = "a".repeat(64);
  const origin = { clockHash: "c".repeat(64), startedAt: "2026-09-07T03:00:00.000Z" };
  const intent = { schemaVersion: 1, kind: "guided-opening-launch-intent", dir, launchId: randomUUID(), origin,
    submission: { schemaVersion: 1, operation: "prepare-guided-opening", idempotencyKey: randomUUID(),
      expectedToken: randomUUID(), expectedJournalHash: journal, proposalReadinessHash: "d".repeat(64), treatmentDraftRevisionHash: "e".repeat(64) },
    receivedAt: origin.startedAt, controllerFiles: ["guided-opening-launch-store.ts", "guided-opening-launcher.ts",
      "guided-opening-controller.ts", "guided-opening-execution.ts", "opening-handoff-clock.ts"]
      .map((name) => ({ path: `src/lib/server/${name}`, sha256: "f".repeat(64) })) };
  const root = openingLaunchDirectory(dir, journal, true);
  const write = () => createOpeningLaunchRecord(root, "intent.json", intent);
  return { dir, journal, origin, intent, root, write, cleanup: () => rmSync(dir, { recursive: true, force: true }) };
}

test("checkpoint singleton is exclusive even for byte-identical repeated publication", () => {
  const f = fixture();
  try {
    assert.equal(readOpeningLaunchIntent(f.dir, f.journal), null);
    const hash = f.write(), before = readFileSync(path.join(f.root, "intent.json"));
    assert.throws(f.write, (error: NodeJS.ErrnoException) => error.code === "EEXIST");
    assert.throws(() => createOpeningLaunchRecord(f.root, "intent.json", { ...f.intent, launchId: randomUUID() }),
      (error: NodeJS.ErrnoException) => error.code === "EEXIST");
    assert.deepEqual(readFileSync(path.join(f.root, "intent.json")), before);
    assert.equal(readOpeningLaunchIntent(f.dir, f.journal)?.hash, hash);
  } finally { f.cleanup(); }
});

test("an interrupted parent with no activation/release never enters the controller handoff", async () => {
  const f = fixture();
  try {
    f.write(); const held = readOpeningLaunchIntent(f.dir, f.journal)!;
    assert.equal(readOpeningLaunchActivation(held), null);
    await assert.rejects(waitForOpeningHandoff(held, 20), /not confirmed/);
    assert.equal(optionalLaunchRecord(path.join(f.root, "controller-started.json")), null);
    assert.equal(optionalLaunchRecord(path.join(f.root, "outcome.json")), null);
  } finally { f.cleanup(); }
});

test("malformed, wrong-project and old-controller inventories are never absent or launchable", () => {
  for (const mutate of [
    (f: ReturnType<typeof fixture>) => ({ ...f.intent, dir: "/TEST/wrong-project" }),
    (f: ReturnType<typeof fixture>) => ({ ...f.intent, controllerFiles: f.intent.controllerFiles.slice(1) }),
    (f: ReturnType<typeof fixture>) => ({ ...f.intent, extra: true }),
    (f: ReturnType<typeof fixture>) => ({ ...f.intent, submission: { ...f.intent.submission, expectedJournalHash: "b".repeat(64) } }),
  ]) {
    const f = fixture();
    try { createOpeningLaunchRecord(f.root, "intent.json", mutate(f)); assert.throws(() => readOpeningLaunchIntent(f.dir, f.journal)); }
    finally { f.cleanup(); }
  }
});

test("a broken symlink or directory in place of a launch file fails closed", () => {
  for (const kind of ["link", "directory"]) {
    const f = fixture(), target = path.join(f.root, "intent.json");
    try {
      if (kind === "link") symlinkSync(path.join(f.root, "missing.json"), target);
      else mkdirSync(target);
      assert.throws(() => readOpeningLaunchIntent(f.dir, f.journal));
    } finally { f.cleanup(); }
  }
});

test("new activation refuses PID-only, missing boot/start and unrelated intent clocks", () => {
  for (const value of [{ pid: 2 }, { pid: 2, bootSession: "boot" }, { pid: 2, startToken: "start" },
    { pid: 2, bootSession: "", startToken: "start" }, { pid: 0, bootSession: "boot", startToken: "start" }]) {
    assert.throws(() => strictOpeningControllerIdentity(value));
  }
  const f = fixture();
  try {
    f.write(); const held = readOpeningLaunchIntent(f.dir, f.journal)!;
    const captured = captureOpeningAttemptStart({ wall: () => Date.parse(f.origin.startedAt), monotonic: () => 0 });
    const clock = captured.start(f.origin);
    createOpeningLaunchRecord(f.root, "activation.json", { schemaVersion: 1, kind: "guided-opening-controller-activation",
      intentHash: "0".repeat(64), owner: { pid: 2, bootSession: "TEST", startToken: "TEST" },
      handoff: { receivedAt: captured.receivedAt, admission: clock.admission, observation: clock.observe() } });
    assert.throws(() => readOpeningLaunchActivation(held), /not bound/);
  } finally { f.cleanup(); }
});

test("controller-started is a one-time fence and launch path derivation rejects traversal", () => {
  const f = fixture();
  try {
    const value = { scope: "TEST startup marker only" };
    createOpeningLaunchRecord(f.root, "controller-started.json", value);
    assert.throws(() => createOpeningLaunchRecord(f.root, "controller-started.json", value));
    assert.throws(() => openingLaunchDirectory(f.dir, "../../elsewhere", true));
    assert.throws(() => createOpeningLaunchRecord(f.root, "../other.json", value));
  } finally { f.cleanup(); }
});

test("missing or relative sealed tool pins fail before any launch intent is published", () => {
  const f = fixture(), names = ["SNIPER_NODE_PATH", "HYPERFRAMES_BROWSER_PATH", "HYPERFRAMES_FFMPEG_PATH", "HYPERFRAMES_FFPROBE_PATH"];
  try {
    const environment: NodeJS.ProcessEnv = { NODE_ENV: "test", ...Object.fromEntries(names.map((name) => [name, process.execPath])) };
    assert.doesNotThrow(() => assertOpeningControllerTools(environment));
    for (const name of names) {
      for (const value of [undefined, "node", f.dir]) assert.throws(() => assertOpeningControllerTools({ ...environment, [name]: value }));
    }
    assert.equal(readOpeningLaunchIntent(f.dir, f.journal), null);
  } finally { f.cleanup(); }
});

/** Tiny actual OS identity probe, no media or other process is launched/terminated. */
test("activation alone cannot hand off; the exact release marker unlocks only the recorded process", async () => {
  const f = fixture();
  try {
    f.write(); const held = readOpeningLaunchIntent(f.dir, f.journal)!;
    const owner = strictOpeningControllerIdentity(captureProcessIdentity(process.pid));
    const captured = captureOpeningAttemptStart({ wall: () => Date.parse(f.origin.startedAt), monotonic: () => 0 });
    const budget = captured.start(f.origin);
    const activationHash = createOpeningLaunchRecord(f.root, "activation.json", {
      schemaVersion: 1, kind: "guided-opening-controller-activation", intentHash: held.hash, owner,
      handoff: { receivedAt: captured.receivedAt, admission: budget.admission, observation: budget.observe() } });
    await assert.rejects(waitForOpeningHandoff(held, 20), /not confirmed/);
    createOpeningLaunchRecord(f.root, "released.json", { schemaVersion: 1, intentHash: held.hash, activationHash });
    assert.equal((await waitForOpeningHandoff(held, 2000)).hash, activationHash);
    assert.equal(optionalLaunchRecord(path.join(f.root, "controller-started.json")), null);
  } finally { f.cleanup(); }
});
