/** Actual new-only completion bytes; original source/native/time remain explicit TEST leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import test from "node:test";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { assertRecordedSourceColorCleanupAttempt, assertRecordedSourceColorCleanupMetadata } from "../guided-source-color-cleanup-attempt";
import { CleanupPreparationPublication } from "../guided-source-color-cleanup-preparation";
import { commitPreparedSourceColorCleanup } from "../guided-source-color-cleanup-pending-commit";
import { cleanupPendingCommitFixture } from "./_guided-source-color-cleanup-pending-commit-fixture";
import { cleanupAttemptWriterFixture, assertWriterRetained, replaceWriterOutput, type CleanupAttemptWriterFixture }
  from "./_guided-source-color-cleanup-attempt-fixture";

function preparedPath(f: CleanupAttemptWriterFixture): string {
  const root = fs.realpathSync(f.staging.root), directory = fs.realpathSync(f.directory);
  assert.equal(directory, f.directory); assert(directory.startsWith(root + path.sep));
  const info = fs.lstatSync(directory); assert(info.isDirectory()); assert.equal(info.uid, process.getuid!());
  assert.equal(info.mode & 0o777, 0o700); return path.join(directory, "prepared.json");
}
function replacePreparation(f: CleanupAttemptWriterFixture): void {
  const file = preparedPath(f); assert.equal(fs.realpathSync(file), file);
  const info = fs.lstatSync(file); assert(info.isFile()); assert.equal(info.nlink, 1); assert.equal(info.uid, process.getuid!());
  const temporary = path.join(f.directory, `TEST-preparation-replacement-${randomUUID()}.json`);
  fs.writeFileSync(temporary, fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}

test("actual completed writer publishes one exact discoverable prepared fact before any journal CAS", async t => {
  const f = cleanupAttemptWriterFixture(t), recorded = await f.write(), file = preparedPath(f), raw = readCutPreviewObject(file);
  assert.deepEqual(raw.value, recorded.fact); assert.equal(raw.sha256, recorded.factHash);
  assert.deepEqual(recorded.preparedRef, { path: file, sha256: raw.sha256, sizeBytes: raw.sizeBytes });
  assert(Object.isFrozen(recorded.preparedRef)); assertRecordedSourceColorCleanupAttempt(recorded);
  assert.equal(f.calls.length, 1); assertWriterRetained(f);
});

for (const kind of ["regular", "dangling", "directory"] as const) {
  test(`a preexisting ${kind} preparation entry refuses before native work`, async t => {
    const f = cleanupAttemptWriterFixture(t), file = preparedPath(f);
    if (kind === "regular") fs.writeFileSync(file, "TEST retained partial record", { flag: "wx", mode: 0o600 });
    else if (kind === "dangling") fs.symlinkSync(path.join(f.directory, "TEST-never-existing-preparation"), file);
    else fs.mkdirSync(file, { mode: 0o700 });
    await assert.rejects(f.write(), /already has a preparation entry/);
    assert.equal(f.counts.run, 0); assert.equal(f.calls.length, 0); assertWriterRetained(f);
  });
}

test("failed actual historical read cannot publish a durable prepared fact", async t => {
  const f = cleanupAttemptWriterFixture(t), read = f.writerDependencies.read;
  f.writerDependencies.read = input => { const observed = read(input); replaceWriterOutput(f); return observed; };
  await assert.rejects(f.write(), /original file identity changed/);
  assert(!fs.existsSync(preparedPath(f))); assert.equal(f.calls.length, 1); assertWriterRetained(f);
});

test("the last original clock callback cannot replace newly published preparation bytes or inode", async t => {
  const f = cleanupAttemptWriterFixture(t); let changed = false;
  f.clockCallbacks.remaining = () => {
    if (!changed && fs.existsSync(preparedPath(f))) { changed = true; replacePreparation(f); }
  };
  await assert.rejects(f.write(), /preparation original published file identity changed/);
  assert(changed); assert(fs.existsSync(preparedPath(f))); assert.equal(f.calls.length, 1); assertWriterRetained(f);
});

test("expiry after publication preserves actual completion without creating a live commit capability", async t => {
  const f = cleanupAttemptWriterFixture(t);
  f.clockCallbacks.remaining = () => { if (fs.existsSync(preparedPath(f))) f.timing.elapsed = 300_000; };
  await assert.rejects(f.write(), /original protected remainder/);
  assert(fs.existsSync(preparedPath(f))); assert.equal(f.calls.length, 1); assertWriterRetained(f);
  await assert.rejects(f.write(), /already has a preparation entry/); assert.equal(f.calls.length, 1);
});

test("first CAS and metadata-only handoff keep the original prepared publication identity", async t => {
  const f = cleanupPendingCommitFixture(t), recorded = await f.write(); replacePreparation(f);
  assert.throws(() => assertRecordedSourceColorCleanupMetadata(recorded), /preparation original published file identity changed/);
  assert.throws(() => commitPreparedSourceColorCleanup(recorded), /preparation original published file identity changed/);
  assert.equal(f.calls.length, 1); assertWriterRetained(f);
});

test("an earlier publication handle cannot overwrite a completed preparation entry", async t => {
  const f = cleanupAttemptWriterFixture(t);
  const publication = new CleanupPreparationPublication({ held: f.input.held, attemptId: f.writerInput.attemptId });
  const recorded = await f.write();
  assert.throws(() => publication.publish({ ...recorded.fact, claimHash: "f".repeat(64) }), /already has a preparation entry/);
  assert.equal(f.calls.length, 1); assertWriterRetained(f);
});
