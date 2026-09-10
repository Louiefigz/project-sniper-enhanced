/** Original media file holds under TEST provenance leaves; no native or source/grade job IO. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import test from "node:test";
import { CLEANUP_MEDIA_ROLES, captureSourceColorCleanupMedia, cleanupMediaReference,
  type CleanupMediaReference } from "../guided-source-color-cleanup-attempt-media";
import { readSourceColorCleanupAttempt, sourceColorCleanupAttemptReadDependencies,
  assertSourceColorCleanupAttemptMetadata } from "../guided-source-color-cleanup-attempt-read";
import { cleanupAttemptReadFixture } from "./_guided-source-color-cleanup-attempt-read-fixture";
import { replaceAttemptMediaFile } from "./_guided-source-color-cleanup-attempt-media-fixture";
import { openingProcessFixture } from "./_guided-opening-process-fixture";
import { observeCutPreviewFile } from "@/app/api/producer/auto-edit/cut-preview-receipt";

test("default media reference capture remains the actual original activation reader", () => {
  assert.equal(sourceColorCleanupAttemptReadDependencies.media, captureSourceColorCleanupMedia);
});

test("actual default provider joins five raw TEST records through the real activation parser", t => {
  const f = openingProcessFixture({}, 3); t.after(f.cleanup); f.write();
  const rows: CleanupMediaReference[] = [];
  const capture = (ref: CleanupMediaReference) => {
    assert(ref.path.startsWith(f.root + path.sep));
    const observed = observeCutPreviewFile(ref.path, cleanupMediaReference(ref, f.held), true);
    assert.equal(observed.sha256, ref.sha256); rows.push(ref); return observed.bytes;
  };
  captureSourceColorCleanupMedia(f.held, capture);
  assert.deepEqual(rows.map(row => row.role), CLEANUP_MEDIA_ROLES);
  assert.equal(rows[0].sha256, f.held.job.guidedHandoffV2!.openingProcessOutcomeHash);
  assert.equal(rows[1].sha256, f.activation.beforeJournalHash);
  f.held.job.token = randomUUID();
  assert.throws(() => captureSourceColorCleanupMedia(f.held, capture), /journal lineage/);
});

for (const role of CLEANUP_MEDIA_ROLES) {
  test(`original media ${role} is held before the first arbitrary caller callback`, async t => {
    const f = await cleanupAttemptReadFixture(t); let changed = false;
    f.callbacks.guard = () => { if (!changed) { changed = true; replaceAttemptMediaFile(f.media, role); } };
    assert.throws(f.read, /file identity/);
  });
  test(`final cleanup settlement cannot replace original media ${role}`, async t => {
    const f = await cleanupAttemptReadFixture(t);
    const dependencies = { ...f.readerDependencies, descendants: (...args: Parameters<typeof f.readerDependencies.descendants>) => {
      const result = f.readerDependencies.descendants(...args); replaceAttemptMediaFile(f.media, role); return result;
    } };
    assert.throws(() => readSourceColorCleanupAttempt(f.readInput, dependencies), /file identity/);
  });
}

test("original media activation reference cannot be replaced during the last callback", async t => {
  const f = await cleanupAttemptReadFixture(t);
  const dependencies = { ...f.readerDependencies, descendants: (...args: Parameters<typeof f.readerDependencies.descendants>) => {
    const result = f.readerDependencies.descendants(...args);
    f.readInput.held.job.guidedHandoffV2!.openingProcessOutcomeHash = "0".repeat(64); return result;
  } };
  assert.throws(() => readSourceColorCleanupAttempt(f.readInput, dependencies), /context metadata/);
});

test("original proof parent cannot be replaced even while retaining the identical file inode", async t => {
  const f = await cleanupAttemptReadFixture(t), file = f.media.files.find(row => row.role === "activation")!.path;
  const directory = path.dirname(file), temporary = path.join(path.dirname(directory), `TEST-prior-receipts-${randomUUID()}`);
  assert(directory.startsWith(f.staging.root + path.sep)); assert.equal(fs.realpathSync(directory), directory);
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  f.callbacks.guard = () => {
    fs.renameSync(directory, temporary); fs.mkdirSync(directory, { mode: 0o700 });
    fs.renameSync(path.join(temporary, path.basename(file)), file);
  };
  assert.throws(f.read, /parent identity/);
});

test("later read and callback-free metadata sweep both retain original media files", async t => {
  const f = await cleanupAttemptReadFixture(t), value = f.read(); replaceAttemptMediaFile(f.media, "priorJournal");
  assert.throws(value.assertCurrent, /file identity/);
  assert.throws(() => assertSourceColorCleanupAttemptMetadata(value), /file identity/);
});

test("metadata provider cannot invent another namespace or omit one original file", async t => {
  const f = await cleanupAttemptReadFixture(t), original = f.media.files[0];
  const wrong = { ...f.readerDependencies, media: (_held: typeof f.input.held, capture: Parameters<typeof captureSourceColorCleanupMedia>[1]) => {
    capture({ ...original, path: "/TEST/unowned/proof.json" });
  } };
  assert.throws(() => readSourceColorCleanupAttempt(f.readInput, wrong), /namespace/);
  const absent = { ...f.readerDependencies, media: () => {} };
  assert.throws(() => readSourceColorCleanupAttempt(f.readInput, absent), /coverage is incomplete/);
});

test("actual stopped return must match the original outcome, intent and ledger raw references", async t => {
  const f = await cleanupAttemptReadFixture(t), altered = { ...f.readerDependencies,
    stopped: () => ({ ...f.actual, receipt: { ...f.actual.receipt, ledgerSha256: "0".repeat(64) } }) };
  assert.throws(() => readSourceColorCleanupAttempt(f.readInput, altered), /original media raw references/);
});
