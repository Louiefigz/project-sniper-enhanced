/** Actual TEMP publication/unlink/CAS and leases only; fixture native/creative admission leaves stay inert. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { beginSourceColorPrelaunchCancellation, finishSourceColorPrelaunchCancellation } from "../guided-source-color-prelaunch-cancel";
import { observeOpeningControllerPrelaunchCancellation, releaseOpeningControllerLease } from "../guided-opening-controller-lifecycle";
import { enterSourceColorPrelaunchDispatch } from "../guided-source-color-prelaunch-owner";
import { prelaunchFixture, replacePrelaunchFile } from "./_guided-source-color-prelaunch-fixture";
import { cancellationFixture, replaceCancellationFile, contradictoryCancellationRecord } from "./_guided-source-color-prelaunch-cancel-fixture";

test("same-live no-publication cancellation clears only its actual claim and releases resource before project", t => {
  const f = prelaunchFixture(t), owner = f.hold(), before = observeHumanCutJob(f.staging.producerDir);
  const token = beginSourceColorPrelaunchCancellation(owner), result = finishSourceColorPrelaunchCancellation(token);
  const after = observeHumanCutJob(f.staging.producerDir), expected = structuredClone(before.job.guidedHandoffV2!);
  delete expected.openingExecutionClaimHash; assert.deepEqual(after.job.guidedHandoffV2, expected);
  assert.deepEqual(after.job.ctx, before.job.ctx); assert.equal(after.job.token, before.job.token);
  assert.equal(after.job.events.at(-1)!.payload.event, "opening_source_color_prelaunch_cancelled");
  assert.equal(result.claimRetained, false); assert.equal(result.openingApproved, false); f.assertLeases();
  assert(!fs.existsSync(f.active)); assert(!fs.existsSync(path.join(path.dirname(result.intent.path), "reservation.json")));
  assert.throws(() => observeOpeningControllerPrelaunchCancellation(f.parent.lifecycle, { ...result }), /actual exact terminal/);
  observeOpeningControllerPrelaunchCancellation(f.parent.lifecycle, result);
  assert.equal(releaseOpeningControllerLease(f.parent.lifecycle), true);
  assert.throws(f.parent.guard); assert.throws(f.staging.resource.assertResource);
});

test("a copied token cannot perform cancellation writes and dispatch entry remains irreversible", t => {
  const f = prelaunchFixture(t), owner = f.hold(), staged = f.stage(owner);
  enterSourceColorPrelaunchDispatch(owner, staged);
  assert.throws(() => beginSourceColorPrelaunchCancellation(owner), /cannot replay or follow dispatch/);
  const root = path.dirname(f.entered.bound.claimPath); assert(!fs.existsSync(path.join(root, "source-color-cancellation"))); f.assertLeases();
});

test("same-byte original journal replacement refuses before any cancellation publication", t => {
  const f = prelaunchFixture(t), owner = f.hold(); replacePrelaunchFile(f, "journal");
  assert.throws(() => beginSourceColorPrelaunchCancellation(owner)); f.assertLeases();
  assert(!fs.existsSync(path.join(path.dirname(f.entered.bound.claimPath), "source-color-cancellation")));
});

test("no-publication token metadata and same claim factory cannot supply cold recovery", t => {
  const f = prelaunchFixture(t), owner = f.hold(), token = beginSourceColorPrelaunchCancellation(owner);
  for (const copy of [{ ...token }, JSON.parse(JSON.stringify(token))]) assert.throws(() => finishSourceColorPrelaunchCancellation(copy), /same-live token/);
  assert.throws(() => beginSourceColorPrelaunchCancellation(owner)); assert.throws(f.hold, /already consumed/);
  assert(!fs.existsSync(path.join(path.dirname(f.entered.bound.claimPath), "source-color-cancellation"))); f.assertLeases();
});

test("an interrupted same-live intent retains the original claim and exact intent, then resumes without replacement", t => {
  const f = prelaunchFixture(t), owner = f.hold(), token = beginSourceColorPrelaunchCancellation(owner);
  const failure = new Error("TEST after original intent");
  assert.throws(() => finishSourceColorPrelaunchCancellation(token, { afterIntent: () => { throw failure; } }), error => error === failure);
  const file = path.join(path.dirname(f.entered.bound.claimPath), "source-color-cancellation/intent.json"), inode = fs.lstatSync(file).ino;
  assert.equal(observeHumanCutJob(f.staging.producerDir).sha256, f.entered.bound.journalHash); f.assertLeases();
  const result = finishSourceColorPrelaunchCancellation(token); assert.equal(fs.lstatSync(file).ino, inode);
  assert.equal(result.intent.path, file); assert.equal(result.claimRetained, false);
});

for (const stage of ["reservation", "partial", "full"] as const) test(`${stage} original staging cancels with exact archived bytes and no invented process cleanup`, t => {
  const f = cancellationFixture(t, stage), token = f.begin(), originalFiles = fs.readdirSync(path.dirname(f.active));
  const result = finishSourceColorPrelaunchCancellation(token), ack = JSON.parse(fs.readFileSync(result.acknowledgement.path, "utf8"));
  assert.deepEqual(fs.readFileSync(path.join(f.directory, "reservation.json")), f.bytes);
  assert.equal(ack.reservation.path, f.active); assert.equal(ack.disposition, "unlinked-original-by-this-live-cancellation");
  assert.deepEqual(fs.readdirSync(path.dirname(f.active)), originalFiles.filter(name => name !== "active.json"));
  const job = observeHumanCutJob(f.staging.producerDir).job; assert(!job.guidedHandoffV2!.openingExecutionClaimHash);
  assert(!job.guidedHandoffV2!.openingProcessOutcomeHash); assert(!job.guidedHandoffV2!.openingCleanupHash); f.assertLeases();
  assert.deepEqual(fs.readdirSync(f.directory).sort(), ["ack.json", "intent.json", "reservation.json"]);
});

test("the same token resumes after its own observed unlink without unlinking again", t => {
  const f = cancellationFixture(t, "reservation"), token = f.begin(), original = fs.unlinkSync; let calls = 0;
  t.mock.method(fs, "unlinkSync", (file: fs.PathLike) => { if (file === f.active) calls++; return original(file); });
  const failure = new Error("TEST after own unlink");
  assert.throws(() => finishSourceColorPrelaunchCancellation(token, { afterUnlink: () => { throw failure; } }), error => error === failure);
  assert.equal(calls, 1); assert(!fs.existsSync(f.active)); f.assertLeases();
  assert.equal(observeHumanCutJob(f.staging.producerDir).sha256, f.entered.bound.journalHash);
  finishSourceColorPrelaunchCancellation(token); assert.equal(calls, 1);
});

for (const role of ["archive", "intent", "ack"] as const) test(`same-byte ${role} replacement never becomes original cancellation evidence`, t => {
  const f = cancellationFixture(t, role === "archive" ? "reservation" : "none"), token = f.begin();
  const key = { archive: "afterArchive", intent: "afterIntent", ack: "afterAck" }[role];
  assert.throws(() => finishSourceColorPrelaunchCancellation(token, { [key]: () => replaceCancellationFile(f, role) }));
  assert.throws(() => finishSourceColorPrelaunchCancellation(token)); f.assertLeases();
  assert.equal(observeHumanCutJob(f.staging.producerDir).sha256, f.entered.bound.journalHash);
});

for (const name of ["media-process-intent.json", "media-process-result.json", "owned-process-ledger.media.jsonl"] as const) {
  test(`contradictory ${name} refuses live cancellation instead of implying absent children`, t => {
    const f = cancellationFixture(t); contradictoryCancellationRecord(f, name);
    assert.throws(f.begin); assert(!fs.existsSync(f.directory)); f.assertLeases();
  });
}

test("a prior missing active marker is not this token's observed unlink", t => {
  const f = cancellationFixture(t, "reservation"), token = f.begin();
  assert.equal(fs.realpathSync(f.active), f.active); const info = fs.lstatSync(f.active);
  assert(info.isFile()); assert.equal(info.nlink, 1); assert.equal(info.uid, process.getuid!()); fs.unlinkSync(f.active);
  assert.throws(() => finishSourceColorPrelaunchCancellation(token)); assert(!fs.existsSync(f.directory)); f.assertLeases();
});

test("a staging publisher that threw before its original inode handoff stays unresolved", t => {
  const f = prelaunchFixture(t), owner = f.hold(), original = fs.chmodSync, failure = new Error("TEST original publisher interrupted");
  t.mock.method(fs, "chmodSync", (file: fs.PathLike, mode: fs.Mode) => {
    original(file, mode); if (file === f.active) throw failure;
  });
  assert.throws(() => f.stage(owner), error => error === failure);
  assert(fs.existsSync(f.active)); assert.throws(() => beginSourceColorPrelaunchCancellation(owner), /original inode handoff/); f.assertLeases();
});

test("the original protected clock is not renewed across an interrupted cancellation", t => {
  const f = cancellationFixture(t), now = performance.now.bind(performance); let offset = 0;
  t.mock.method(performance, "now", () => now() + offset); const token = f.begin();
  assert.throws(() => finishSourceColorPrelaunchCancellation(token, { afterIntent: () => { offset = 300_001; } }), /deadline|clock/);
  assert.throws(() => finishSourceColorPrelaunchCancellation(token), /deadline|clock/);
  assert.equal(observeHumanCutJob(f.staging.producerDir).sha256, f.entered.bound.journalHash); f.assertLeases();
});

test("original callbacks cannot reenter cancellation or its consumed owner", t => {
  const f = cancellationFixture(t), token = f.begin(); let observed = false;
  const result = finishSourceColorPrelaunchCancellation(token, { afterIntent: () => {
    observed = true; assert.throws(() => finishSourceColorPrelaunchCancellation(token), /non-reentrant/);
    assert.throws(f.begin, /cannot replay/);
  } });
  assert(observed); assert.equal(result.claimRetained, false); f.assertLeases();
});

for (const kind of ["project", "resource"] as const) test(`lost original ${kind} lease refuses before unlink or claim clearing`, t => {
  const f = cancellationFixture(t), token = f.begin();
  const lease = kind === "project" ? f.parent.lease : f.staging.resource.lease;
  assert.throws(() => finishSourceColorPrelaunchCancellation(token, { afterIntent: () => lease.release() }));
  assert.equal(observeHumanCutJob(f.staging.producerDir).sha256, f.entered.bound.journalHash);
});

test("failure after actual CAS retains the new exact journal and resumes without repeating the CAS", t => {
  const f = cancellationFixture(t), token = f.begin(), failure = new Error("TEST after actual cancellation CAS");
  assert.throws(() => finishSourceColorPrelaunchCancellation(token, { afterCas: () => { throw failure; } }), error => error === failure);
  const after = observeHumanCutJob(f.staging.producerDir); assert(!after.job.guidedHandoffV2!.openingExecutionClaimHash);
  const result = finishSourceColorPrelaunchCancellation(token); assert.equal(result.cancelledJournalHash, after.sha256);
  assert.equal(observeHumanCutJob(f.staging.producerDir).sha256, after.sha256);
  assert(!fs.existsSync(path.join(f.directory, "failure.json"))); f.assertLeases();
});

test("final callback evidence mutation never mints a terminal release proof", t => {
  const f = cancellationFixture(t), token = f.begin();
  assert.throws(() => finishSourceColorPrelaunchCancellation(token, { beforeReturn: () => replaceCancellationFile(f, "ack") }));
  assert.equal(releaseOpeningControllerLease(f.parent.lifecycle), false); f.assertLeases();
  assert.throws(() => finishSourceColorPrelaunchCancellation(token));
});

for (const invocation of [1, 2]) test(`failure in actual CAS guard ${invocation} retains claim and forbids blind CAS retry`, t => {
  const f = cancellationFixture(t), token = f.begin(), failure = new Error("TEST original CAS guard failure");
  assert.throws(() => finishSourceColorPrelaunchCancellation(token, { beforeCasGuard: current => {
    if (current === invocation) throw failure;
  } }), error => error === failure);
  assert.equal(observeHumanCutJob(f.staging.producerDir).sha256, f.entered.bound.journalHash);
  assert(fs.existsSync(path.join(f.directory, "ack.json"))); assert(!fs.existsSync(path.join(f.directory, "failure.json")));
  assert.throws(() => finishSourceColorPrelaunchCancellation(token), /unresolved/); f.assertLeases();
});

test("an interrupted intent publisher with a created file cannot later recapture that file", t => {
  const f = cancellationFixture(t), token = f.begin(), original = fs.linkSync, failure = new Error("TEST after exact intent link");
  const expected = path.join(f.directory, "intent.json");
  t.mock.method(fs, "linkSync", (existing: fs.PathLike, target: fs.PathLike) => {
    original(existing, target);
    if (target === expected) { assert.equal(fs.realpathSync(path.dirname(expected)), f.directory); throw failure; }
  });
  assert.throws(() => finishSourceColorPrelaunchCancellation(token), error => error === failure);
  assert(fs.existsSync(expected)); assert.throws(() => finishSourceColorPrelaunchCancellation(token));
  assert.equal(observeHumanCutJob(f.staging.producerDir).sha256, f.entered.bound.journalHash); f.assertLeases();
});

test("an active marker reappearing after this token's unlink is retained, never unlinked again", t => {
  const f = cancellationFixture(t, "reservation"), token = f.begin();
  assert.throws(() => finishSourceColorPrelaunchCancellation(token, { afterUnlink: () => {
    assert.equal(fs.realpathSync(path.dirname(f.active)), f.staging.resource.resource);
    fs.writeFileSync(f.active, f.bytes!, { flag: "wx", mode: 0o400 });
  } }));
  assert.deepEqual(fs.readFileSync(f.active), f.bytes); assert.throws(() => finishSourceColorPrelaunchCancellation(token));
  assert.equal(observeHumanCutJob(f.staging.producerDir).sha256, f.entered.bound.journalHash); f.assertLeases();
});

test("terminal registration cannot reenter through its original resource callback", t => {
  const f = prelaunchFixture(t), original = f.staging.resource.assertResource; let nested: (() => void) | undefined;
  f.staging.resource.assertResource = () => { original(); nested?.(); };
  const owner = f.hold(), token = beginSourceColorPrelaunchCancellation(owner), result = finishSourceColorPrelaunchCancellation(token);
  let calls = 0; nested = () => { calls++; assert.throws(() => observeOpeningControllerPrelaunchCancellation(f.parent.lifecycle, result), /cannot replay/); };
  observeOpeningControllerPrelaunchCancellation(f.parent.lifecycle, result); assert(calls > 0); nested = undefined;
  assert.equal(releaseOpeningControllerLease(f.parent.lifecycle), true);
});

test("actual terminal release unlinks the original resource lock before the original project lock", t => {
  const f = cancellationFixture(t), result = finishSourceColorPrelaunchCancellation(f.begin()), original = fs.unlinkSync;
  const resource = path.join(f.staging.resource.resource, ".sniper-project-mutation.lock");
  const project = path.join(fs.realpathSync(f.staging.root), ".sniper-project-mutation.lock"), order: string[] = [];
  t.mock.method(fs, "unlinkSync", (file: fs.PathLike) => {
    if (file === resource || file === project) order.push(String(file)); return original(file);
  });
  observeOpeningControllerPrelaunchCancellation(f.parent.lifecycle, result); assert.equal(releaseOpeningControllerLease(f.parent.lifecycle), true);
  assert.deepEqual(order, [resource, project]); assert.throws(f.parent.guard); assert.throws(f.staging.resource.assertResource);
});

test("the final claimed-job edge preserves every unrelated semantic field and exact original snapshot bytes", t => {
  const f = cancellationFixture(t), before = observeHumanCutJob(f.staging.producerDir), result = finishSourceColorPrelaunchCancellation(f.begin());
  const after = observeHumanCutJob(f.staging.producerDir).job, expected = structuredClone(before.job);
  delete expected.guidedHandoffV2!.openingExecutionClaimHash;
  expected.updatedAt = after.updatedAt; expected.message = after.message; expected.nextEventId++;
  expected.events = [...expected.events, after.events.at(-1)!].slice(-256); assert.deepEqual(after, expected);
  assert.deepEqual(fs.readFileSync(path.join(f.staging.producerDir, "human-cut-job-snapshots", `${before.sha256}.json`)), before.bytes);
  assert.equal(result.claimedJournalHash, before.sha256); f.assertLeases();
});

for (const fault of ["ack", "deadline"] as const) test(`final project release ${fault} fault refuses success without blind re-release`, t => {
  const f = cancellationFixture(t), now = performance.now.bind(performance); let offset = 0, calls = 0;
  t.mock.method(performance, "now", () => now() + offset);
  const result = finishSourceColorPrelaunchCancellation(f.begin()); observeOpeningControllerPrelaunchCancellation(f.parent.lifecycle, result);
  const project = path.join(fs.realpathSync(f.staging.root), ".sniper-project-mutation.lock"), original = fs.unlinkSync;
  t.mock.method(fs, "unlinkSync", (file: fs.PathLike) => {
    original(file); if (file !== project) return; calls++;
    if (fault === "ack") replaceCancellationFile(f, "ack"); else offset = 300_001;
  });
  assert.throws(() => releaseOpeningControllerLease(f.parent.lifecycle)); assert.equal(calls, 1);
  assert.throws(f.parent.guard); assert.throws(f.staging.resource.assertResource);
  assert.throws(() => releaseOpeningControllerLease(f.parent.lifecycle), /cannot replay|release.*unverified/); assert.equal(calls, 1);
  assert(fs.existsSync(result.acknowledgement.path)); assert(!fs.existsSync(path.join(f.directory, "failure.json")));
});
