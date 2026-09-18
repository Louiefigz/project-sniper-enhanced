/** Metadata-only all-prior reads; native/claim admission remains explicitly TEST-stubbed. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID, createHash } from "node:crypto";
import test from "node:test";
import { assertSourceColorCleanupHistoryMetadata } from "../guided-source-color-cleanup-history";
import { CleanupHistoryHold } from "../guided-source-color-cleanup-history-hold";
import { canonicalJsonSha256 } from "../auto-edit-hash";
import { cleanupHistoryFixture, historyFile, replaceHistoryFile, alterPrepared } from "./_guided-source-color-cleanup-history-fixture";
import { replaceAttemptMediaFile } from "./_guided-source-color-cleanup-attempt-media-fixture";

test("actual complete reads preserve raw prepared references, Buffer evidence and all ordered names", async t => {
  const f = await cleanupHistoryFixture(t, 2), result = f.readHistory();
  assert.equal(result.scope, "all-prior-completed-source-color-cleanup-not-adoption-or-retirement");
  assert.equal(result.attempts.length, 2); assert.deepEqual(result.attempts.map(row => row.attemptId), f.ids);
  assert(Buffer.isBuffer(f.historyInput.held.bytes)); assert(Object.isFrozen(result.attempts));
  for (const row of result.attempts) {
    const bytes = fs.readFileSync(row.preparedRef.path);
    assert.equal(row.preparedRef.sizeBytes, bytes.length); assert.equal(row.preparedRef.sha256, createHash("sha256").update(bytes).digest("hex"));
    assert.equal(row.factHash, canonicalJsonSha256(row.fact)); assert(Object.isFrozen(row.fact));
    assert.deepEqual(row.evidence.containerNames, f.input.reservation.containerNames); assert.equal(row.evidence.openingApproved, false);
  }
  result.assertCurrent(); assertSourceColorCleanupHistoryMetadata(result);
  assert.deepEqual(fs.readFileSync(f.staged.reservation.path), f.activeBytes); f.staging.resource.assertResource();
  assert.equal(f.historyCalls.guard, 2); assert.equal(f.historyCalls.remaining, 2);
});

test("metadata helper requires actual read identity and invokes no owner callbacks", async t => {
  const f = await cleanupHistoryFixture(t), result = f.readHistory(), before = { ...f.historyCalls };
  assertSourceColorCleanupHistoryMetadata(result); assert.deepEqual(f.historyCalls, before);
  assert.throws(() => assertSourceColorCleanupHistoryMetadata({ ...result }), /actual original read/);
  assert.throws(() => assertSourceColorCleanupHistoryMetadata(JSON.parse(JSON.stringify(result))), /actual original read/);
});

test("current active bytes and installed tools are not consulted by archive-only history", async t => {
  const f = await cleanupHistoryFixture(t), file = f.staged.reservation.path;
  assert(file.startsWith(f.staging.root + path.sep)); assert.equal(fs.realpathSync(file), file);
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1);
  fs.renameSync(file, path.join(f.staging.resource.resource, "TEST-retained-active.json"));
  const result = f.readHistory(); result.assertCurrent(); assert.equal(result.attempts.length, 1);
  assert(!fs.existsSync(f.tools.script)); assert(!fs.existsSync(f.tools.python));
});

for (const name of ["prepared.json", "start.json", "invocation.json", "output.json", "reservation.json", "owned-process-ledger.cleanup.jsonl"]) {
  test(`missing ${name} is unresolved before the first owner callback`, async t => {
    const f = await cleanupHistoryFixture(t), file = historyFile(f, name);
    fs.renameSync(file, path.join(f.staging.root, `TEST-missing-${name}`));
    assert.throws(f.readHistory, /file set/); assert.equal(f.historyCalls.guard, 0);
  });
}

for (const name of ["failure.json", "retirement-ack.json", "TEST-unknown.json"]) {
  test(`${name} is not silently omitted from completed history`, async t => {
    const f = await cleanupHistoryFixture(t);
    fs.writeFileSync(path.join(f.directory, name), "TEST", { flag: "wx", mode: 0o600 });
    assert.throws(f.readHistory, /entry count|file set/); assert.equal(f.historyCalls.guard, 0);
  });
}

test("empty, non-UUID and dangling sibling attempts all refuse", async t => {
  const f = await cleanupHistoryFixture(t), sibling = path.join(f.root, randomUUID());
  fs.mkdirSync(sibling, { mode: 0o700 }); assert.throws(f.readHistory, /file set/); fs.rmdirSync(sibling);
  const unknown = path.join(f.root, "TEST-unknown"); fs.mkdirSync(unknown, { mode: 0o700 }); assert.throws(f.readHistory, /UUID|uuid/);
  fs.rmdirSync(unknown); fs.symlinkSync(path.join(f.staging.root, "TEST-absent"), sibling);
  assert.throws(f.readHistory); assert.equal(f.historyCalls.guard, 0);
});

test("first caller callback cannot replace a later attempt before its reader runs", async t => {
  const f = await cleanupHistoryFixture(t, 2);
  f.historyCallbacks.guard = () => replaceHistoryFile(f, "output.json", f.ids[1]);
  assert.throws(f.readHistory, /file identity/); assert.equal(f.historyCalls.guard, 1);
});

test("first remaining callback cannot replace a later prepared record", async t => {
  const f = await cleanupHistoryFixture(t, 2);
  f.historyCallbacks.remaining = () => replaceHistoryFile(f, "prepared.json", f.ids[1]);
  assert.throws(f.readHistory, /file identity/);
});

for (const role of ["activation", "priorJournal", "intent", "outcome", "ledger"] as const) {
  test(`original ${role} media identity is held before first callback`, async t => {
    const f = await cleanupHistoryFixture(t);
    f.historyCallbacks.guard = () => replaceAttemptMediaFile(f.media, role);
    assert.throws(f.readHistory, /file identity/);
  });
}

test("later callback entry insertion and original raw Buffer mutation invalidate the held history", async t => {
  const f = await cleanupHistoryFixture(t), result = f.readHistory();
  f.historyCallbacks.guard = () => fs.mkdirSync(path.join(f.root, randomUUID()), { mode: 0o700 });
  assert.throws(result.assertCurrent, /entry set/);
  f.historyInput.held.bytes[0] ^= 1;
  assert.throws(() => assertSourceColorCleanupHistoryMetadata(result), /held claim metadata/);
});

test("original callbacks cannot be replaced or recursively reenter an active read", async t => {
  const f = await cleanupHistoryFixture(t), result = f.readHistory();
  f.historyCallbacks.guard = () => result.assertCurrent(); assert.throws(result.assertCurrent, /reenter/);
  f.historyInput.guard = () => {}; assert.throws(result.assertCurrent, /caller identity/);
});

test("invalid/expired original allowance rejects and child reads never resample it", async t => {
  const f = await cleanupHistoryFixture(t, 2);
  for (const allowance of [0, -1, NaN, Infinity, 300_010]) {
    f.historyInput.remainingMs = () => allowance;
    assert.throws(f.readHistory, /protected remainder/);
  }
  f.historyInput.remainingMs = () => 0.001;
  assert.throws(f.readHistory, /deadline expired/);
});

test("prepared raw identity is distinct from canonical fact identity and semantics remain closed", async t => {
  const f = await cleanupHistoryFixture(t);
  const file = historyFile(f, "prepared.json"), value = JSON.parse(fs.readFileSync(file, "utf8"));
  fs.chmodSync(file, 0o600); fs.writeFileSync(file, JSON.stringify(value, null, 2), { flag: "w" });
  const result = f.readHistory(); assert.notEqual(result.attempts[0].factHash, result.attempts[0].preparedRef.sha256);
  alterPrepared(f, row => { row.claimHash = "0".repeat(64); }); assert.throws(f.readHistory, /bindings|authority/);
});

test("matching ledger hashes cannot launder an unmatched spawn intent", async t => {
  const f = await cleanupHistoryFixture(t), ledger = historyFile(f, "owned-process-ledger.cleanup.jsonl");
  const rows = fs.readFileSync(ledger, "utf8").trimEnd().split("\n").map(row => JSON.parse(row));
  rows.splice(1, 0, { event: "intent", pid: null, argv0: "/TEST/docker", at: rows[0].at });
  fs.chmodSync(ledger, 0o600); fs.writeFileSync(ledger, rows.map(row => JSON.stringify(row)).join("\n") + "\n");
  assert.throws(f.readHistory, /unbalanced/);
});

test("unreaped recorded PID and malformed lifecycle refuse without process discovery", async t => {
  const f = await cleanupHistoryFixture(t), ledger = historyFile(f, "owned-process-ledger.cleanup.jsonl");
  const rows = fs.readFileSync(ledger, "utf8").trimEnd().split("\n").map(row => JSON.parse(row));
  rows.splice(1, 0, { event: "intent", pid: null, argv0: "/TEST/docker", at: rows[0].at },
    { event: "spawned", pid: 999999, argv0: "/TEST/docker", at: rows[0].at });
  fs.chmodSync(ledger, 0o600); fs.writeFileSync(ledger, rows.map(row => JSON.stringify(row)).join("\n") + "\n");
  assert.throws(f.readHistory, /unbalanced/);
  fs.writeFileSync(ledger, JSON.stringify(rows[0]) + "\n"); assert.throws(f.readHistory, /lifecycle/);
});

test("33 entries and more than64MiB of actual file sizes reject before reads/callbacks", async t => {
  const f = await cleanupHistoryFixture(t, 2), directories = [];
  for (let index = 0; index < 31; index++) { const directory = path.join(f.root, randomUUID()); fs.mkdirSync(directory, { mode: 0o700 }); directories.push(directory); }
  assert.throws(f.readHistory, /entry count/); for (const directory of directories) fs.rmdirSync(directory);
  for (const id of f.ids) { const file = historyFile(f, "owned-process-ledger.cleanup.jsonl", id); fs.chmodSync(file, 0o600); fs.truncateSync(file, 32 * 1024 * 1024); }
  assert.throws(f.readHistory, /64MiB/); assert.equal(f.historyCalls.guard, 0);
});

test("exactly32 entries fit the private capture bound without claiming32 completed readers ran", async t => {
  const f = await cleanupHistoryFixture(t, 32), hold = new CleanupHistoryHold(f.historyInput, f.readerDependencies.media);
  assert.equal(hold.attemptIds.length, 32); assert.equal(f.historyCalls.guard, 0);
  hold.run(() => hold.check()); assert.equal(f.historyCalls.guard, 1);
});

test("exactly64MiB fits actual raw inventory counting but does not qualify synthetic ledger content", async t => {
  const f = await cleanupHistoryFixture(t, 2), files = f.ids.flatMap(id => fs.readdirSync(path.join(f.root, id)).map(name => path.join(f.root, id, name)));
  files.push(...f.media.files.map(row => row.path));
  const first = historyFile(f, "owned-process-ledger.cleanup.jsonl", f.ids[0]), second = historyFile(f, "owned-process-ledger.cleanup.jsonl", f.ids[1]);
  const otherBytes = files.filter(file => file !== first && file !== second).reduce((sum, file) => sum + fs.statSync(file).size, 0);
  fs.chmodSync(first, 0o600); fs.chmodSync(second, 0o600); fs.truncateSync(first, 32 * 1024 * 1024);
  fs.truncateSync(second, 32 * 1024 * 1024 - otherBytes);
  assert.equal(files.reduce((sum, file) => sum + fs.statSync(file).size, 0), 64 * 1024 * 1024);
  const hold = new CleanupHistoryHold(f.historyInput, f.readerDependencies.media);
  hold.run(() => hold.observeAll()); assert.equal(f.historyCalls.guard, 1);
});

test("zero prior attempts is not a completed-history proof", async t => {
  const f = await cleanupHistoryFixture(t);
  fs.renameSync(f.directory, path.join(f.staging.root, "TEST-retained-complete-attempt"));
  assert.throws(f.readHistory, /1\.\.32/); assert.equal(f.historyCalls.guard, 0);
});

test("hardlinked, nonprivate and symlinked metadata are rejected before caller callbacks", async t => {
  const f = await cleanupHistoryFixture(t), file = historyFile(f, "prepared.json"), link = path.join(f.staging.root, "TEST-hardlink");
  fs.linkSync(file, link); assert.throws(f.readHistory, /single-link/); fs.unlinkSync(link);
  fs.chmodSync(file, 0o644); assert.throws(f.readHistory, /private/); fs.chmodSync(file, 0o600);
  fs.renameSync(file, path.join(f.staging.root, "TEST-retained-prepared.json"));
  fs.symlinkSync(path.join(f.staging.root, "TEST-absent"), file); assert.throws(f.readHistory, /single-link/);
  assert.equal(f.historyCalls.guard, 0);
});

test("unbalanced historical refusal does not call even the code-only descendant observer", async t => {
  const f = await cleanupHistoryFixture(t), ledger = historyFile(f, "owned-process-ledger.cleanup.jsonl");
  const rows = fs.readFileSync(ledger, "utf8").trimEnd().split("\n").map(row => JSON.parse(row));
  rows.splice(1, 0, { event: "intent", pid: null, argv0: "/TEST/docker", at: rows[0].at });
  fs.chmodSync(ledger, 0o600); fs.writeFileSync(ledger, rows.map(row => JSON.stringify(row)).join("\n") + "\n");
  let observed = 0; f.readerDependencies.descendants = () => { observed++; throw new Error("TEST unexpected process discovery"); };
  assert.throws(f.readHistory, /unbalanced/); assert.equal(observed, 0);
});
