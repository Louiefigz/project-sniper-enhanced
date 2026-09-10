/** Actual TEMP tool hashes/invocation bytes; native, journal and tool selection remain TEST stubs.
 * No real interpreter, worker source, dependency or daemon file is modified or executed.
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import test, { type TestContext } from "node:test";
import { assertToolsUnchanged } from "../guided-opening-process";
import { runSourceColorCleanupProcess } from "../guided-source-color-cleanup-process";
import { ownedProcessLedgerPath } from "../guided-opening-process-ledger";
import { sourceColorCleanupProcessFixture } from "./_guided-source-color-cleanup-process-fixture";

function sha(bytes: Buffer): string { return createHash("sha256").update(bytes).digest("hex"); }

/** Select only inert files created under this exact fixture's canonical private root. */
function fixture(t: TestContext) {
  const f = sourceColorCleanupProcessFixture(t), root = path.join(f.staging.root, "TEST-inert-tool-pins");
  fs.mkdirSync(path.join(root, "venv/bin"), { recursive: true, mode: 0o700 });
  const files = { script: path.join(root, "cleanup.py"), runnerScript: path.join(root, "runner.py"),
    python: path.join(root, "venv/bin/python"), venvConfig: path.join(root, "venv/pyvenv.cfg") };
  for (const [role, file] of Object.entries(files)) {
    assert(file.startsWith(fs.realpathSync(f.staging.root) + path.sep));
    fs.writeFileSync(file, `TEST inert ${role}; must never execute\n`, { flag: "wx", mode: 0o600 });
  }
  Object.assign(f.tools, files, { scriptHash: sha(fs.readFileSync(files.script)),
    runnerScriptHash: sha(fs.readFileSync(files.runnerScript)), pythonResolved: files.python,
    pythonHash: sha(fs.readFileSync(files.python)), venvRoot: path.dirname(files.venvConfig),
    venvConfigHash: sha(fs.readFileSync(files.venvConfig)) });
  const captured: (typeof f.tools)[] = [];
  const dependencies = { ...f.dependencies, toolsUnchanged: (tools: typeof f.tools) => {
    captured.push(tools); assertToolsUnchanged(tools);
  } };
  return { ...f, dependencies, files, captured, invocation: path.join(f.directory, "invocation.json") };
}

/** Reject dependencies, aliases, hard links and unowned files BEFORE any fault write. */
function target(f: ReturnType<typeof fixture>, file: string): fs.Stats {
  assert([...Object.values(f.files), f.invocation].includes(file));
  assert(file.startsWith(fs.realpathSync(f.staging.root) + path.sep));
  assert.equal(fs.realpathSync(file), file);
  const stat = fs.lstatSync(file);
  assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  return stat;
}

/** Change only bytes on the held TEST inode, preserving the separately captured original SHA. */
function changeTool(f: ReturnType<typeof fixture>, file: string): void {
  const before = target(f, file), fd = fs.openSync(file, fs.constants.O_WRONLY | fs.constants.O_APPEND | fs.constants.O_NOFOLLOW);
  try {
    const actual = fs.fstatSync(fd);
    assert.equal(actual.ino, before.ino); assert.equal(actual.dev, before.dev); assert.equal(actual.nlink, 1);
    fs.writeSync(fd, "TEST changed bytes\n");
  } finally { fs.closeSync(fd); }
}

/** Replace only this attempt's known invocation with equal bytes on a new TEST-owned inode. */
function replaceInvocation(f: ReturnType<typeof fixture>): void {
  target(f, f.invocation);
  const temporary = path.join(f.directory, "TEST-new-invocation-inode.json");
  fs.writeFileSync(temporary, fs.readFileSync(f.invocation), { flag: "wx", mode: 0o600 });
  fs.renameSync(temporary, f.invocation);
}

test("actual TEMP pins and immutable invocation carry the same frozen tools to the native stub", async t => {
  const f = fixture(t), expected = structuredClone(f.tools);
  const output = await runSourceColorCleanupProcess(f.input, f.dependencies);
  assert(f.captured.length >= 5); assert(f.captured.every(tools => Object.isFrozen(tools)));
  assert.deepEqual(output.tools, expected); assert.deepEqual(f.calls[0].tools, expected);
  assert.equal(output.invocation.path, f.invocation); assert.equal(sha(fs.readFileSync(f.invocation)), output.invocation.sha256);
  assert.deepEqual(JSON.parse(fs.readFileSync(f.invocation, "utf8")).tools, expected);
  assert.equal(output.mediaSelected, false); assert.equal(output.deliveryApproved, false);
});

test("real tool-byte verification rejects each original pin before invocation publication or spawn", async t => {
  for (const role of ["script", "runnerScript", "python", "venvConfig"] as const) await t.test(role, async t => {
    const f = fixture(t); let changed = false;
    f.input.guard = () => {
      if (changed || !f.events.toolReads) return;
      changed = true; changeTool(f, f.files[role]);
    };
    await assert.rejects(runSourceColorCleanupProcess(f.input, f.dependencies), /actual interpreter or worker bytes changed/);
    assert(changed); assert.equal(f.calls.length, 0); assert.equal(fs.existsSync(f.invocation), false);
    assert(fs.existsSync(f.staged.reservation.path));
  });
});

test("real tool-byte verification rejects each post-return change while retaining invocation and ledger", async t => {
  for (const role of ["script", "runnerScript", "python", "venvConfig"] as const) await t.test(role, async t => {
    const f = fixture(t); f.events.afterInvoke = () => changeTool(f, f.files[role]);
    await assert.rejects(runSourceColorCleanupProcess(f.input, f.dependencies), /actual interpreter or worker bytes changed/);
    assert.equal(f.calls.length, 1); assert(fs.existsSync(f.invocation));
    assert(fs.existsSync(ownedProcessLedgerPath(f.directory, "cleanup"))); assert(fs.existsSync(f.staged.reservation.path));
  });
});

test("invocation inode substitution fails in the actual pre-spawn guarded remainder", async t => {
  const f = fixture(t), invoke = f.dependencies.invoke;
  f.dependencies.invoke = async request => {
    replaceInvocation(f); request.remainingMs(); return invoke(request);
  };
  await assert.rejects(runSourceColorCleanupProcess(f.input, f.dependencies), /invocation file identity/);
  assert.equal(f.calls.length, 0); assert(fs.existsSync(f.invocation));
  assert.equal(fs.existsSync(ownedProcessLedgerPath(f.directory, "cleanup")), false);
  assert(fs.existsSync(f.staged.reservation.path));
});

test("last original post-return guard cannot replace the invocation with equal bytes", async t => {
  const f = fixture(t); let armed = false, changed = false;
  f.events.afterInvoke = () => { armed = true; };
  f.input.guard = () => { if (armed && !changed) { changed = true; replaceInvocation(f); } };
  await assert.rejects(runSourceColorCleanupProcess(f.input, f.dependencies), /invocation file identity/);
  assert(changed); assert.equal(f.calls.length, 1); assert(fs.existsSync(f.invocation));
  assert(fs.existsSync(ownedProcessLedgerPath(f.directory, "cleanup"))); assert(fs.existsSync(f.staged.reservation.path));
});

test("mutating the caller's detached tool DTO cannot redirect the actual captured tool arguments", async t => {
  const f = fixture(t), original = structuredClone(f.tools); let changed = false;
  f.input.guard = () => {
    if (changed || !f.events.toolReads) return;
    changed = true; f.tools.pythonHash = "0".repeat(64);
  };
  const result = await runSourceColorCleanupProcess(f.input, f.dependencies);
  assert(changed); assert.notEqual(f.tools.pythonHash, original.pythonHash);
  assert.deepEqual(f.calls[0].tools, original); assert.deepEqual(result.tools, original);
  assert.deepEqual(result.invocation.value.tools, original);
});
