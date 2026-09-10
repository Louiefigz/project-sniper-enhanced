/** Body opening-EVIDENCE consumers only. Actual TEST approval/CAS; native, readiness and source admission remain explicit TEST leaves. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import test, { type TestContext } from "node:test";
import { approveGuidedOpeningUnderLease } from "../guided-opening-approval";
import { readSelectedOpeningMedia, readHistoricalOpeningSelection } from "../guided-opening-selection";
import { readBodyOpeningResult, retainBodyOpeningMetadata,
  verifyBodyOpeningInput, retainBodyOpeningVerification, bodyOpeningVersionServices } from "../guided-body-opening-version";
import { readBodyOpeningApproval } from "../guided-body-approval";
import { sourceColorApprovalDependencies } from "../guided-source-color-approval";
import { saveHumanCutJobSnapshot } from "../human-cut-acceptance-store";
import { sourceColorApprovalFixture, replaceApprovalFixtureFile } from "./_guided-source-color-approval-fixture";

/** Reuse the original fixture allowance, actual lease and actual service wrapper; no new body clock or admission. */
async function evidence(t: TestContext) {
  const f = await sourceColorApprovalFixture(t), committed = await approveGuidedOpeningUnderLease(f.input);
  const selected = readSelectedOpeningMedia(f.input.dir), callbacks = { bodyGuard: () => {} }, calls = { bodyGuard: 0 };
  const guard = () => { calls.bodyGuard++; f.input.remainingMs(); callbacks.bodyGuard(); };
  const result = readBodyOpeningResult({ selected, guard });
  const request = { dir: f.input.dir, current: selected.observed, selected, result, guard };
  const approval = readBodyOpeningApproval(request), metadata = retainBodyOpeningMetadata({ selected, result, approval });
  return { f, committed, selected, result, request, approval, metadata, guard, callbacks, calls };
}

/** Fault permission is only the actual approval index returned by this fixture's real cold reader. */
function replaceIndex(e: Awaited<ReturnType<typeof evidence>>): void {
  const file = path.join(e.approval.files.root, "approval.json"), root = fs.realpathSync(e.f.staging.root);
  assert(file.startsWith(root + path.sep)); assert.equal(fs.realpathSync(file), file);
  assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.nlink, 1); assert.equal(stat.uid, process.getuid!());
  const temporary = path.join(path.dirname(file), `TEST-body-opening-${randomUUID()}.json`);
  fs.writeFileSync(temporary, fs.readFileSync(file), { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
}

test("generic approval to actual body opening result/approval retains genuine source2 evidence only", async t => {
  const e = await evidence(t); e.metadata();
  assert.equal(e.approval.summary.approvalHash, e.committed.approvalHash);
  assert.equal(e.result.completion.schemaVersion, 2); assert.equal(e.approval.fact.schemaVersion, 2);
  assert.equal(e.approval.fact.bodyGenerated, false); assert.equal(e.approval.fact.deliveryApproved, false);
  assert.equal(e.f.calls.native, 1); // Only the fixture's earlier TEST opening requalification leaf.
});

test("body evidence refuses copied selection, result and approval handles", async t => {
  const e = await evidence(t);
  assert.throws(() => readBodyOpeningResult({ selected: { ...e.selected }, guard: e.guard }), /actual original/);
  assert.throws(() => readBodyOpeningApproval({ ...e.request, result: { ...e.result } }), /actual original/);
  for (const change of [{ selected: { ...e.selected } }, { result: { ...e.result } }, { approval: { ...e.approval } }]) {
    assert.throws(() => retainBodyOpeningMetadata({ selected: e.selected, result: e.result, approval: e.approval, ...change }), /actual original/);
  }
});

test("retained body metadata cannot lose source obligations through a changed selection discriminator", async t => {
  const e = await evidence(t); e.selected.fact.schemaVersion = 1;
  assert.throws(e.metadata, /changed/);
});

test("known source selection downgrade must not invoke a supplied legacy result reader", async t => {
  const e = await evidence(t); e.selected.fact.schemaVersion = 1; let legacy = 0;
  assert.throws(() => readBodyOpeningResult({ selected: e.selected, guard: e.guard }, () => {
    legacy++; throw new Error("TEST legacy reader must remain untouched");
  }));
  assert.equal(legacy, 0);
});

test("first body approval callback cannot replace its already-held actual approval index", async t => {
  const e = await evidence(t); e.calls.bodyGuard = 0;
  e.callbacks.bodyGuard = () => { if (e.calls.bodyGuard === 1) replaceIndex(e); };
  assert.throws(() => readBodyOpeningApproval(e.request), /changed|identity/);
});

test("later body metadata detects exact original range replacement without replaying work callbacks", async t => {
  const e = await evidence(t), count = e.calls.bodyGuard;
  e.callbacks.bodyGuard = () => { throw new Error("TEST expired operation must not run again"); };
  e.metadata(); assert.equal(e.calls.bodyGuard, count);
  replaceApprovalFixtureFile(e.f, "core"); assert.throws(e.metadata, /changed|identity/);
});

test("body verifier returns actual same-owner source capability and retained verification rejects copies", async t => {
  const e = await evidence(t), request = { dir: e.f.input.dir, lease: e.f.input.lease,
    expectedCleanupHash: String(e.selected.fact.cleanupHash), remainingMs: e.f.input.remainingMs };
  t.mock.method(bodyOpeningVersionServices, "sourceVerify", sourceColorApprovalDependencies.verify);
  const verified = await verifyBodyOpeningInput({ request, selected: e.selected });
  const metadata = retainBodyOpeningVerification(true, verified); metadata(); assert.equal(e.f.calls.native, 2);
  assert.throws(() => retainBodyOpeningVerification(true, { ...verified }), /actual original/);
  assert.equal(verified.result.schemaVersion, 2); assert.equal(verified.deliveryApproved, false);
});

test("body source verifier cannot rebaseline its original lease or remaining callback before actual delegation", async t => {
  const e = await evidence(t); let replace: "lease" | "remaining" = "lease";
  t.mock.method(bodyOpeningVersionServices, "sourceVerify", async (request: Parameters<typeof bodyOpeningVersionServices.sourceVerify>[0]) => {
    if (replace === "lease") request.lease = { ...request.lease };
    else { const original = request.remainingMs; request.remainingMs = () => original(); }
    return sourceColorApprovalDependencies.verify(request);
  });
  for (const role of ["lease", "remaining"] as const) {
    replace = role;
    const request = { dir: e.f.input.dir, lease: e.f.input.lease,
      expectedCleanupHash: String(e.selected.fact.cleanupHash), remainingMs: e.f.input.remainingMs };
    await assert.rejects(verifyBodyOpeningInput({ request, selected: e.selected }), /original request owner changed/);
    if (role === "lease") assert.notEqual(request.lease, e.f.input.lease);
    else assert.notEqual(request.remainingMs, e.f.input.remainingMs);
    e.f.assertProject();
  }
  assert.equal(e.f.calls.native, 3); // Original TEST approval plus two actual-wrapper TEST requalification leaves.
});

test("historical body approval accepts only the exact approved journal, not its before-approval parent", async t => {
  const e = await evidence(t); saveHumanCutJobSnapshot(e.f.input.dir, e.selected.observed);
  const selected = readHistoricalOpeningSelection(e.f.input.dir, e.selected.observed.sha256, e.guard);
  const result = readBodyOpeningResult({ selected, guard: e.guard });
  const approval = readBodyOpeningApproval({ dir: e.f.input.dir, current: selected.observed, selected, result, guard: e.guard });
  retainBodyOpeningMetadata({ selected, result, approval })();
  const before = readHistoricalOpeningSelection(e.f.input.dir, String(e.approval.fact.beforeJournalHash), e.guard);
  assert.throws(() => readBodyOpeningApproval({ dir: e.f.input.dir, current: before.observed, selected,
    result, guard: e.guard }), /selected journal|changed/);
});
