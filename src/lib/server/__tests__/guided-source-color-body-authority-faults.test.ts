/** Genuine original source2 holders with TEST-only clocks/callbacks. No native or source/tool fault writes. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import test, { type TestContext } from "node:test";
import { sourceColorBodyAuthorityFixture } from "./_guided-source-color-body-authority-fixture";
import { saveHumanCutJobSnapshot, type observeHumanCutJob } from "../human-cut-acceptance-store";
import { autoEditJobPath } from "../auto-edit-job-persistence";
import { bodyClaimLineageReads, readGuidedBodyClaim, assertBodyClaimSourceColorMetadata,
  bodyAdmissionInputVersion, readHistoricalBodyAdmission } from "../guided-body-lineage";
import { bodyMediaInputAdmissionFixture } from "./_guided-body-media-input-admission-fixture";

type Fixture = Awaited<ReturnType<typeof sourceColorBodyAuthorityFixture>>;

/** The slow filesystem observation is only the actual original archive, not a dependency-selected target. */
function finalArchiveDeadline(t: TestContext, e: Fixture) {
  const root = fs.realpathSync(e.f.staging.root), archive = e.f.recorded.fact.archive.path;
  assert.equal(archive, path.join(path.dirname(e.selected.held.claimPath), "cleanup-attempts", e.f.recorded.fact.cleanupAttemptId, "reservation.json"));
  assert(archive.startsWith(root + path.sep)); assert.equal(fs.realpathSync(archive), archive);
  const stat = fs.lstatSync(archive); assert(stat.isFile()); assert.equal(stat.uid, process.getuid!()); assert.equal(stat.nlink, 1);
  let now = performance.now(), advanced = false; const end = now + 20_000;
  t.mock.method(performance, "now", () => now); e.request.remainingMs = () => Math.floor(end - now);
  const original = fs.lstatSync, limit = Error.stackTraceLimit;
  Error.stackTraceLimit = 100; t.after(() => { Error.stackTraceLimit = limit; });
  t.mock.method(fs, "lstatSync", (...args: Parameters<typeof fs.lstatSync>) => {
    const result = original(...args);
    if (!advanced && args[0] === archive && new Error().stack?.includes("retainSourceInput")) {
      advanced = true; now = end + 1;
    }
    return result;
  });
  return { assertReached: () => { assert.equal(advanced, true); assert(now > end); } };
}

test("source2 body hold charges original final metadata IO before returning authority", async t => {
  const e = await sourceColorBodyAuthorityFixture(t), clock = finalArchiveDeadline(t, e);
  let error: unknown;
  try { await e.hold(); } catch (failure) { error = failure; }
  clock.assertReached();
  assert.match(String(error), /expired|exhausted|budget|remaining|remainder/);
  assert.equal(e.f.calls.native, 2); e.f.assertProject();
});

test("first body remainder callback cannot rebaseline in-place original submission values", async t => {
  const e = await sourceColorBodyAuthorityFixture(t), original = e.request.submission.idempotencyKey;
  const remaining = e.request.remainingMs; let changed = false;
  e.request.remainingMs = () => {
    if (!changed) { changed = true; e.request.submission.idempotencyKey = randomUUID(); }
    return remaining();
  };
  let error: unknown;
  try { await e.hold(); } catch (failure) { error = failure; }
  assert.equal(changed, true); assert.notEqual(e.request.submission.idempotencyKey, original);
  assert.match(String(error), /original|changed/);
  assert.equal(e.f.calls.native, 1); e.f.assertProject();
});

test("body admission captures original current Buffer and parsed metadata before historical callbacks", async t => {
  const f = await bodyMediaInputAdmissionFixture(t);
  await f.run(async ({ admission }) => {
    assert.equal(bodyAdmissionInputVersion(admission), 2); assertBodyClaimSourceColorMetadata(admission);
    assert.throws(() => assertBodyClaimSourceColorMetadata({ ...admission }), /actual original/);
    const raw = fs.readFileSync(autoEditJobPath(f.f.request.dir), "utf8"), actualConcat = Buffer.concat, actualParse = JSON.parse;
    const actualSelection = bodyClaimLineageReads.selection;
    let current: { bytes?: Buffer; job?: ReturnType<typeof observeHumanCutJob>["job"] } = {};
    let mode: "bytes" | "job" = "bytes", changed = false;
    t.mock.method(Buffer, "concat", (...args: Parameters<typeof Buffer.concat>) => {
      const value = actualConcat(...args); if (!current.bytes && value.toString("utf8") === raw) current.bytes = value; return value;
    });
    t.mock.method(JSON, "parse", (...args: Parameters<typeof JSON.parse>) => {
      const value = actualParse(...args); if (!current.job && args[0] === raw) current.job = value; return value;
    });
    t.mock.method(bodyClaimLineageReads, "selection", (...args: Parameters<typeof actualSelection>) => {
      assert(current.bytes); assert(current.job); changed = true;
      if (mode === "bytes") current.bytes[0] ^= 1;
      else current.job.ctx.planPath += ".TEST-unpublished-change";
      return actualSelection(...args);
    });
    for (const role of ["bytes", "job"] as const) {
      mode = role; current = {}; changed = false;
      assert.throws(() => readGuidedBodyClaim(f.f.request.dir), /current.*changed|original.*changed/);
      assert.equal(changed, true);
    }
    assertBodyClaimSourceColorMetadata(admission);
  });
});

test("later body assertUnchanged charges its final original verification metadata IO", async t => {
  const e = await sourceColorBodyAuthorityFixture(t);
  let now = performance.now(), reached = false, recordsChecked = false; const end = now + 20_000;
  t.mock.method(performance, "now", () => now); e.request.remainingMs = () => Math.floor(end - now);
  const held = await e.hold(), file = held.verification.receiptPath, record = e.reads.record, stat = fs.lstatSync;
  e.reads.record = value => {
    record(value); if (value.path === path.join(path.dirname(file), "output.json")) recordsChecked = true;
  };
  t.mock.method(fs, "lstatSync", (...args: Parameters<typeof fs.lstatSync>) => {
    const value = stat(...args);
    if (!reached && recordsChecked && args[0] === file) { reached = true; now = end + 1; }
    return value;
  });
  let error: unknown;
  try { held.assertUnchanged(); } catch (failure) { error = failure; }
  assert.equal(reached, true); assert(now > end);
  assert.match(String(error), /exhausted|expired|remaining|budget|remainder/);
  assert.equal(e.f.calls.native, 2);
});

/** Only the original current journal or its explicit retained snapshot is writable; no inventory path is consulted. */
function replaceBodyJournal(f: Awaited<ReturnType<typeof bodyMediaInputAdmissionFixture>>, entry: { role: "current" | "snapshot"; hash: string }): void {
  const root = fs.realpathSync(f.f.f.staging.root), dir = f.f.request.dir;
  assert.match(entry.hash, /^[a-f0-9]{64}$/u); assert.equal(dir, path.join(root, "producer"));
  const file = entry.role === "current" ? autoEditJobPath(dir) : path.join(dir, "human-cut-job-snapshots", `${entry.hash}.json`);
  assert.equal(fs.realpathSync(file), file); assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.uid, process.getuid!()); assert.equal(stat.nlink, 1);
  const temp = path.join(path.dirname(file), `TEST-body-current-${randomUUID()}.json`);
  fs.writeFileSync(temp, fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temp, file);
}

test("body admission cannot rebaseline its exact current or retained entry file during historical callback", async t => {
  const f = await bodyMediaInputAdmissionFixture(t);
  await f.run(async ({ admission }) => {
    const hash = admission.current.sha256; saveHumanCutJobSnapshot(f.f.request.dir, admission.current);
    const selection = bodyClaimLineageReads.selection; let replaced = false, role: "current" | "snapshot" = "current";
    t.mock.method(bodyClaimLineageReads, "selection", (...args: Parameters<typeof selection>) => {
      if (!replaced) { replaceBodyJournal(f, { role, hash }); replaced = true; }
      return selection(...args);
    });
    for (const entry of ["current", "snapshot"] as const) {
      role = entry; replaced = false; let error: unknown;
      const read = entry === "current" ? () => readGuidedBodyClaim(f.f.request.dir)
        : () => readHistoricalBodyAdmission(f.f.request.dir, hash);
      try { read(); } catch (failure) { error = failure; }
      assert.equal(replaced, true); assert.match(String(error), /changed|identity/);
    }
  });
});
