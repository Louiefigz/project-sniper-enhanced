/** Actual TEMP handoffs only; explicit TEST decisions and inert native replies are not audiovisual approval. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import test from "node:test";
import { approveGuidedOpeningUnderLease, readGuidedOpeningApproval,
  assertSourceColorOpeningApprovalSummaryMetadata } from "../guided-opening-approval";
import { readGuidedOpeningStatus, guidedOpeningStatusReads } from "../guided-opening-status";
import { readSelectedOpeningMedia } from "../guided-opening-selection";
import { readGuidedObject } from "../guided-cut-v2-store";
import { observeHumanCutJob } from "../human-cut-acceptance-store";
import { sourceColorApprovalFixture, type SourceColorApprovalFixture } from "./_guided-source-color-approval-fixture";

/** Resolve ONE newly created TEST approval index before installing a fault; never follow source/tool inventories. */
function originalIndexReplacement(f: SourceColorApprovalFixture, approvalHash: string): () => void {
  const fact = readGuidedObject(f.input.dir, approvalHash), row = fact.requalification as { readbackDirectory: string };
  const file = path.join(path.dirname(f.selected.held.claimPath), "readback-attempts", row.readbackDirectory, "approval.json");
  const root = fs.realpathSync(f.staging.root); assert(file.startsWith(root + path.sep)); assert.equal(fs.realpathSync(file), file);
  assert.equal(fs.realpathSync(path.dirname(file)), path.dirname(file));
  const stat = fs.lstatSync(file, { bigint: true }), bytes = fs.readFileSync(file);
  assert(stat.isFile()); assert.equal(stat.nlink, BigInt(1)); assert.equal(stat.uid, BigInt(process.getuid!()));
  return () => {
    assert.equal(fs.realpathSync(file), file); assert.deepEqual(fs.lstatSync(file, { bigint: true }), stat);
    const temporary = path.join(path.dirname(file), `TEST-approval-index-${randomUUID()}.json`);
    fs.writeFileSync(temporary, bytes, { flag: "wx", mode: 0o600 }); fs.renameSync(temporary, file);
  };
}

test("generic under-lease approval dispatch uses actual source2 verification and retains strict status proof", async t => {
  const f = await sourceColorApprovalFixture(t), decision = await approveGuidedOpeningUnderLease(f.input);
  assert.equal(f.calls.verifier, 1); assert.equal(f.calls.native, 1);
  const selected = readSelectedOpeningMedia(f.input.dir), summary = readGuidedOpeningApproval(f.input.dir, selected.selectionHash, selected);
  assert(summary); assert.equal(summary.approvalHash, decision.approvalHash);
  f.callbacks.remaining = () => { throw new Error("TEST old approval allowance expired"); };
  assert.doesNotThrow(() => assertSourceColorOpeningApprovalSummaryMetadata(summary));
  assert.throws(() => assertSourceColorOpeningApprovalSummaryMetadata({ ...summary }), /actual original/);
  const status = readGuidedOpeningStatus(f.input.dir);
  assert.equal(status.state, "ready-for-review"); assert.equal(status.openingApproved, true);
  assert.equal(status.deliveryApproved, false); assert.equal(status.subjectiveListening, "not-performed-by-system");
  f.assertProject();
});

test("a later final status journal callback cannot replace the actual approval index unnoticed", async t => {
  const f = await sourceColorApprovalFixture(t), decision = await approveGuidedOpeningUnderLease(f.input);
  const replace = originalIndexReplacement(f, decision.approvalHash); let calls = 0;
  const reads = { ...guidedOpeningStatusReads, job: (dir: string) => {
    const result = observeHumanCutJob(dir); if (++calls === 3) replace(); return result;
  } };
  assert.throws(() => readGuidedOpeningStatus(f.input.dir, reads), /changed|identity/); assert.equal(calls, 3);
  assert.equal(observeHumanCutJob(f.input.dir).job.guidedHandoffV2!.openingApprovalHash, decision.approvalHash);
});

test("source2 approval status cannot borrow an equal selection DTO or another selected hash", async t => {
  const f = await sourceColorApprovalFixture(t); await approveGuidedOpeningUnderLease(f.input);
  const selected = readSelectedOpeningMedia(f.input.dir);
  assert.throws(() => readGuidedOpeningApproval(f.input.dir, selected.selectionHash, { ...selected }), /actual|original/);
  assert.throws(() => readGuidedOpeningApproval(f.input.dir, "f".repeat(64), selected), /stale/);
});

test("unsupported selection version refuses before any source requalification or approval publication", async t => {
  const f = await sourceColorApprovalFixture(t); f.input.selected.fact.schemaVersion = 9;
  await assert.rejects(approveGuidedOpeningUnderLease(f.input), /unsupported/);
  assert.equal(f.calls.verifier, 0); assert(!observeHumanCutJob(f.input.dir).job.guidedHandoffV2!.openingApprovalHash);
});
