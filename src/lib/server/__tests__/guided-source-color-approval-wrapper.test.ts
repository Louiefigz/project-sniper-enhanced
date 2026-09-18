/** Actual public TEMP approval/replay, leases and records; every human decision/native reply is explicitly TEST-only. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test, { type TestContext } from "node:test";
import { canonicalProducerDir } from "@/app/api/producer/auto-edit/request";
import { approveGuidedOpening, readGuidedOpeningApproval } from "../guided-opening-approval";
import { autoEditJobPath } from "../auto-edit-job-persistence";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { readGuidedObject, writeGuidedObject } from "../guided-cut-v2-store";
import { sourceColorApprovalFixture, replaceApprovalFixtureFile,
  type SourceColorApprovalFixture } from "./_guided-source-color-approval-fixture";

/** Use the existing process-local isolated workspace; the actual public canonical path policy stays enabled. */
function isolatedWorkspace(t: TestContext, f: SourceColorApprovalFixture): void {
  const previous = process.env.SNIPER_WORKSPACE_ROOT;
  process.env.SNIPER_WORKSPACE_ROOT = fs.realpathSync(f.staging.root);
  t.after(() => {
    if (previous === undefined) delete process.env.SNIPER_WORKSPACE_ROOT;
    else process.env.SNIPER_WORKSPACE_ROOT = previous;
  });
  assert.equal(canonicalProducerDir(f.input.dir), f.input.dir);
}

/** New-only TEST fact plus ONE allowlisted original journal fault; never follow a source/tool inventory. */
function downgradeApproval(f: SourceColorApprovalFixture, hash: string): string {
  const fact = readGuidedObject(f.input.dir, hash); assert.equal(fact.schemaVersion, 2);
  const root = fs.realpathSync(f.staging.root), file = autoEditJobPath(f.input.dir);
  assert(file.startsWith(root + path.sep)); assert.equal(fs.realpathSync(file), file);
  assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file); assert(stat.isFile()); assert.equal(stat.uid, process.getuid!()); assert.equal(stat.nlink, 1);
  const receipts = path.join(f.input.dir, ".sniper-authority-v1/objects/receipts");
  assert(receipts.startsWith(root + path.sep)); assert.equal(fs.realpathSync(receipts), receipts);
  const downgraded = writeGuidedObject(f.input.dir, { ...fact, schemaVersion: 1 });
  const observed = observeHumanCutJob(f.input.dir); observed.job.guidedHandoffV2!.openingApprovalHash = downgraded;
  fs.writeFileSync(file, JSON.stringify(observed.job), { flag: "w", mode: 0o600 }); return downgraded;
}

/** The real append happens first; the injected action represents only its exact final telemetry tail. */
function afterApprovalTiming(t: TestContext, action: () => void): void {
  const write = fs.writeSync;
  t.mock.method(fs, "writeSync", (...args: Parameters<typeof fs.writeSync>) => {
    const result = write(...args), bytes = String(args[1]);
    if (bytes.includes('"stage":"guided_opening_human_approval"') && bytes.includes('"event":"end"')) action();
    return result;
  });
}

test("public replay refuses a downgraded V1 approval fact for the actual source2 selection", async t => {
  const f = await sourceColorApprovalFixture(t), approved = await f.approve(); isolatedWorkspace(t, f);
  const downgraded = downgradeApproval(f, approved.approvalHash), invokes = f.calls.native;
  await assert.rejects(approveGuidedOpening({ dir: f.input.dir, submission: f.input.submission }), /version|source|selection/i);
  assert.throws(() => readGuidedOpeningApproval(f.input.dir, f.selected.selectionHash), /version|source|selection/i);
  assert.equal(f.calls.native, invokes);
  assert.equal(observeHumanCutJob(f.input.dir).job.guidedHandoffV2!.openingApprovalHash, downgraded);
});

test("public source2 approval charges final timing append to its original protected allowance", async t => {
  const f = await sourceColorApprovalFixture(t); isolatedWorkspace(t, f); f.projectLease.release();
  const now = performance.now.bind(performance); let delay = 0, advanced = false;
  t.mock.method(performance, "now", () => now() + delay);
  afterApprovalTiming(t, () => { advanced = true; delay = 600_001; });
  await assert.rejects(approveGuidedOpening({ dir: f.input.dir, submission: f.input.submission }), /allowance|expired|remainder/i);
  assert(advanced); assert.equal(f.calls.native, 1);
  assert(observeHumanCutJob(f.input.dir).job.guidedHandoffV2!.openingApprovalHash);
});

test("public source2 approval retains its original archive identity through timing completion", async t => {
  const f = await sourceColorApprovalFixture(t); isolatedWorkspace(t, f); f.projectLease.release(); let changed = false;
  afterApprovalTiming(t, () => { replaceApprovalFixtureFile(f, "archive"); changed = true; });
  await assert.rejects(approveGuidedOpening({ dir: f.input.dir, submission: f.input.submission }), /identity|changed|metadata/i);
  assert(changed); assert.equal(f.calls.native, 1);
  assert(observeHumanCutJob(f.input.dir).job.guidedHandoffV2!.openingApprovalHash);
});
