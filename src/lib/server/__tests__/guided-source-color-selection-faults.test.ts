/** Exact TEMP callback/tail faults; actual metadata writes and CAS stay enabled, native is forbidden. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { assertOpeningSelectionMetadata, readSelectedOpeningMedia, readHistoricalOpeningSelection } from "../guided-opening-selection";
import { readSourceColorSelection } from "../guided-source-color-selection-read";
import { observeHumanCutJob, saveHumanCutJobSnapshot } from "../human-cut-acceptance-store";
import { sourceColorSelectionFixture, replaceSelectionFixtureFile } from "./_guided-source-color-selection-fixture";

test("first original selection callback cannot replace a later actual range inode", async t => {
  const f = await sourceColorSelectionFixture(t), before = observeHumanCutJob(f.input.dir).sha256;
  f.callbacks.remaining = () => { if (f.calls.remaining === 1) replaceSelectionFixtureFile(f, "core"); };
  assert.throws(f.select, /changed/); assert.equal(observeHumanCutJob(f.input.dir).sha256, before);
});

test("archive change immediately after actual selection CAS rejects without undoing or fabricating failure", async t => {
  const f = await sourceColorSelectionFixture(t), original = fs.renameSync; let changed = false;
  t.mock.method(fs, "renameSync", (...args: Parameters<typeof fs.renameSync>) => {
    original(...args);
    if (String(args[1]) === f.files.journal && !changed) { changed = true; replaceSelectionFixtureFile(f, "archive"); }
  });
  assert.throws(f.select, /changed|identity/); assert.equal(changed, true);
  assert(observeHumanCutJob(f.input.dir).job.guidedHandoffV2!.openingMediaSelectionHash);
  assert.equal(fs.existsSync(f.verified.receipt.path.replace("verified.json", "failure.json")), false);
});

test("actual CAS tail consumes the original remainder without calling a new work budget", async t => {
  const f = await sourceColorSelectionFixture(t), original = fs.renameSync, now = performance.now.bind(performance); let delay = 0, calls = -1;
  t.mock.method(performance, "now", () => now() + delay);
  t.mock.method(fs, "renameSync", (...args: Parameters<typeof fs.renameSync>) => {
    original(...args);
    if (String(args[1]) === f.files.journal) { delay = 31_000; calls = f.calls.remaining; }
  });
  assert.throws(f.select, /CAS tail expired/); assert.equal(f.calls.remaining, calls);
  assert(observeHumanCutJob(f.input.dir).job.guidedHandoffV2!.openingMediaSelectionHash);
  assert.equal(fs.existsSync(f.verified.receipt.path.replace("verified.json", "failure.json")), false);
});

test("current cold final journal IO remains inside its one entry allowance", async t => {
  const f = await sourceColorSelectionFixture(t); f.select();
  const original = fs.openSync, now = performance.now.bind(performance); let count = 0, last = Infinity, delay = 0;
  t.mock.method(performance, "now", () => now() + delay);
  t.mock.method(fs, "openSync", (...args: Parameters<typeof fs.openSync>) => {
    const fd = original(...args);
    if (String(args[0]) === f.files.journal && ++count === last) delay = 31_000;
    return fd;
  });
  readSelectedOpeningMedia(f.input.dir); last = count; count = 0;
  assert.throws(() => readSelectedOpeningMedia(f.input.dir), /read allowance expired/);
  assert.equal(count, last);
});

test("historical wrapper retains its genuine private inner proof and refuses equal DTO copies", async t => {
  const f = await sourceColorSelectionFixture(t); f.select(); const current = observeHumanCutJob(f.input.dir);
  saveHumanCutJobSnapshot(f.input.dir, current); let expired = false;
  const historical = readHistoricalOpeningSelection(f.input.dir, current.sha256, () => { if (expired) throw new Error("TEST old operation expired"); });
  expired = true; assert.doesNotThrow(() => assertOpeningSelectionMetadata(historical));
  assert.throws(() => assertOpeningSelectionMetadata({ ...historical }), /actual/);
  historical.fact.schemaVersion = 1; assert.throws(() => assertOpeningSelectionMetadata(historical), /changed/);
});

test("reentry with the old actual verifier after selection never rewrites the original selection index", async t => {
  const f = await sourceColorSelectionFixture(t), selected = f.select(), journal = observeHumanCutJob(f.input.dir).sha256;
  const file = f.verified.receipt.path.replace("verified.json", "selection.json"), bytes = fs.readFileSync(file), stat = fs.lstatSync(file, { bigint: true });
  assert.throws(f.select, /changed|identity/); assert.equal(observeHumanCutJob(f.input.dir).sha256, journal);
  assert.deepEqual(fs.readFileSync(file), bytes); assert.deepEqual(fs.lstatSync(file, { bigint: true }), stat);
  assertOpeningSelectionMetadata(selected);
});

test("direct cold selection rejects malformed hash and foreign directory before resolving publication IO", async t => {
  const f = await sourceColorSelectionFixture(t); f.select(); const selected = readSelectedOpeningMedia(f.input.dir);
  const target = path.join(f.cleanup.held.claim.outputRoot, "media-result.json"), root = fs.realpathSync(f.staging.root);
  assert.equal(target, f.files.result); assert(target.startsWith(root + path.sep)); assert.equal(fs.realpathSync(target), target);
  const stat = fs.lstatSync(target); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  const receipts = path.join(f.input.dir, ".sniper-authority-v1/objects/receipts");
  const traversal = path.relative(receipts, target).replace(/\.json$/, "");
  assert.equal(path.join(receipts, `${traversal}.json`), target);
  const foreignPublication = path.join(root, ".sniper-authority-v1/objects/receipts", `${selected.selectionHash}.json`);
  const open = fs.openSync, lstat = fs.lstatSync; let unintendedOpens = 0, foreignStats = 0, callbacks = 0;
  t.mock.method(fs, "openSync", (...args: Parameters<typeof fs.openSync>) => {
    if (String(args[0]) === target) unintendedOpens++;
    return open(...args);
  });
  t.mock.method(fs, "lstatSync", (...args: Parameters<typeof fs.lstatSync>) => {
    if (String(args[0]) === foreignPublication) foreignStats++;
    return lstat(...args);
  });
  for (const variant of [{ dir: f.input.dir, selectionHash: traversal }, { dir: root, selectionHash: selected.selectionHash }]) {
    assert.throws(() => readSourceColorSelection({ ...variant, observed: selected.observed, fact: selected.fact }, () => { callbacks++; }));
  }
  assert.equal(unintendedOpens, 0); assert.equal(foreignStats, 0); assert.equal(callbacks, 0);
});
