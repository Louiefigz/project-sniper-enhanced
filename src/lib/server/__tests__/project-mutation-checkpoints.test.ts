import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { NextRequest } from "next/server";
import { POST } from "@/app/api/producer/save-plan/route";
import { POST as ingest } from "@/app/api/producer/ingest/route";
import { guardProjectMutation, type CheckpointVerification } from "@/app/api/_lib/project-mutation";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { guidedFixture } from "@/lib/producer/__tests__/_guided-cut-fixture";
import { autoEditRequestKey, canonicalJsonSha256 } from "../auto-edit-hash";
import { parseAutoEditJobRecord } from "../auto-edit-job-persistence";
import { clearProducerRun } from "../producer-run-registry";
import { acquireProjectMutationLease } from "../project-mutation-lease";
import { QC_PROMOTION_RECONCILIATION_FILE } from "../ask-editor-reconciliation";
import type { AutoEditJobStatus } from "../auto-edit-job-types";

const HASH = "a".repeat(64);
type Fixture = ReturnType<typeof fixture>;

/** Synthetic durable journal shapes only: no preview, human decision or delivery is qualified. */
function fixture(status: AutoEditJobStatus, version: 1 | 2 = 1) {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-checkpoint-guard-")));
  try { return fixtureAt(root, status, version); } catch (error) {
    clearProducerRun(path.join(root, "producer")); rmSync(root, { recursive: true, force: true }); throw error;
  }
}

function fixtureAt(root: string, status: AutoEditJobStatus, version: 1 | 2) {
  const fixture = guidedFixture(root), job = structuredClone(fixture.run.job);
  if (version === 2) job.ctx.workflowV2 = { schemaVersion: 2, mode: "guided",
    afterCut: "treatment-then-intro", approvalPolicy: "explicit-human" };
  job.requestKey = autoEditRequestKey(job.ctx);
  const request = { schemaVersion: 1 as const, requestKey: job.requestKey, planHash: HASH,
    authorityDigest: HASH, cutAuthorityDigest: HASH, cutApprovalReceiptHash: HASH,
    cutReviewApprovalReceiptHash: HASH, pictureLockHash: HASH, timelineMapHash: HASH,
    projectionReceiptHash: HASH, createdAt: new Date().toISOString() };
  Object.assign(job, { status, checkpoint: "cut_reviewed", workerPid: undefined, workerIdentity: undefined,
    cutApprovalWaitStartedAt: request.createdAt,
    cutApprovalRequest: { ...request, requestHash: canonicalJsonSha256(request) },
    cutPreview: { executionKey: HASH, receiptHash: HASH } });
  if (status === "cut_accepted") job.cutAcceptance = { acceptanceHash: HASH };
  if (["awaiting_treatment_brief", "treatment_admitted"].includes(status)) job.guidedHandoffV2 = {
    schemaVersion: 2, cutDecisionHash: HASH, cutActivationHash: HASH, pictureLockedRevisionHash: HASH,
    ...(status === "treatment_admitted" ? { treatmentAdmissionHash: HASH } : {}),
  };
  parseAutoEditJobRecord(job);
  writeFileSync(fixture.jobPath, JSON.stringify(job));
  return { ...fixture, root, job, cleanup: () => {
    clearProducerRun(fixture.ctx.dir); rmSync(root, { recursive: true, force: true });
  } };
}

const checkpoints: Array<[AutoEditJobStatus, 1 | 2]> = [
  ["awaiting_cut_approval", 1], ["cut_accepted", 1], ["awaiting_cut_approval", 2],
  ["awaiting_treatment_brief", 2], ["treatment_admitted", 2], ["failed", 2], ["interrupted", 2], ["complete", 2],
];

for (const [status, version] of checkpoints) test(`direct stale save preserves v${version} ${status} plan and journal`, async () => {
  const item = fixture(status, version);
  try {
    const planBefore = readFileSync(item.ctx.planPath), journalBefore = readFileSync(item.jobPath);
    const plan = JSON.parse(planBefore.toString()); plan.target.pace = "measured";
    const response = await POST(new NextRequest("http://localhost/api/producer/save-plan", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: item.ctx.planPath, plan, timebase: "full-plan" }),
    }));
    assert.equal(response.status, 409, JSON.stringify(await response.json()));
    assert.deepEqual(readFileSync(item.ctx.planPath), planBefore);
    assert.deepEqual(readFileSync(item.jobPath), journalBefore);
  } finally { item.cleanup(); }
});

function verification(item: Fixture): CheckpointVerification {
  return { workflowVersion: 1, action: "accept-cut-and-continue", expectedStatus: "awaiting_cut_approval",
    expectedToken: item.job.token, expectedJournalHash: readCutPreviewObject(item.jobPath).sha256 };
}

function guard(item: Fixture, value?: CheckpointVerification) {
  return guardProjectMutation({ projectRoot: item.root, producerDir: item.ctx.dir,
    operation: "accepting the reviewed cut", ...(value === undefined ? {} : { checkpointVerification: value }) });
}

const allowed: Array<[AutoEditJobStatus, CheckpointVerification["workflowVersion"], CheckpointVerification["action"]]> = [
  ["awaiting_cut_approval", 1, "accept-cut-and-continue"], ["cut_accepted", 1, "retry-cut-continuation"],
  ["awaiting_cut_approval", 2, "accept-cut-await-treatment"], ["awaiting_treatment_brief", 2, "admit-post-cut-treatment"],
  ["treatment_admitted", 2, "compile-post-cut-proposal"],
  ["treatment_admitted", 2, "review-post-cut-proposal"],
  ["treatment_admitted", 2, "prepare-guided-opening"],
  ["treatment_admitted", 2, "reconcile-guided-opening"],
  ["treatment_admitted", 2, "continue-approved-opening"],
];
for (const [status, workflowVersion, action] of allowed) test(`exact ${action} admits a lease, never changes authority`, () => {
  const item = fixture(status, workflowVersion);
  try {
    const before = readFileSync(item.jobPath), plan = readFileSync(item.ctx.planPath);
    const value = { ...verification(item), workflowVersion, action, expectedStatus: status } as CheckpointVerification;
    const granted = guard(item, value); assert.ok(granted.lease);
    const verify = cutPreviewLeaseGuard(item.ctx.dir, granted.lease); verify();
    assert.deepEqual(readFileSync(item.jobPath), before); assert.deepEqual(readFileSync(item.ctx.planPath), plan);
    granted.lease.release(); assert.throws(verify, /ENOENT/);
  } finally { item.cleanup(); }
});

const malformed = [
  { expectedToken: "another-token" }, { expectedJournalHash: "b".repeat(64) }, { expectedJournalHash: true },
  { workflowVersion: 2 }, { action: "saving timeline changes" }, { expectedStatus: "cut_accepted" }, { extra: true },
];
for (const patch of malformed) test(`verification fails closed for ${JSON.stringify(patch)}`, () => {
  const item = fixture("awaiting_cut_approval");
  try {
    const before = readFileSync(item.jobPath);
    const blocked = guard(item, { ...verification(item), ...patch } as CheckpointVerification);
    assert.equal(blocked.response?.status, 409); assert.equal(blocked.lease, undefined);
    assert.deepEqual(readFileSync(item.jobPath), before);
    const next = acquireProjectMutationLease(item.root, "prove failed verification released lease");
    assert.ok(next.lease); next.lease.release();
  } finally { item.cleanup(); }
});

test("operation labels and request JSON cannot supply a checkpoint bypass", async () => {
  const item = fixture("awaiting_cut_approval");
  try {
    assert.equal(guard(item).response?.status, 409);
    const before = readFileSync(item.ctx.planPath), journal = readFileSync(item.jobPath), plan = JSON.parse(before.toString());
    plan.target.pace = "slow";
    const response = await POST(new NextRequest("http://localhost/api/producer/save-plan", { method: "POST",
      body: JSON.stringify({ path: item.ctx.planPath, plan, checkpointVerification: verification(item) }) }));
    assert.equal(response.status, 409); assert.deepEqual(readFileSync(item.ctx.planPath), before);
    assert.deepEqual(readFileSync(item.jobPath), journal);
  } finally { item.cleanup(); }
});

test("a journal race with unchanged token/status invalidates the exact verification capability", () => {
  const item = fixture("awaiting_cut_approval");
  try {
    const value = verification(item);
    writeFileSync(item.jobPath, `${readFileSync(item.jobPath, "utf8")}\n`);
    assert.equal(guard(item, value).response?.status, 409);
  } finally { item.cleanup(); }
});

test("direct source ingest is blocked before media preparation or source metadata mutation", async () => {
  const item = fixture("awaiting_treatment_brief", 2);
  try {
    const source = path.join(item.root, "synthetic-unopened-source.mp4"); writeFileSync(source, "not decoded by this test");
    const manifest = readFileSync(item.ctx.manifestPath), journal = readFileSync(item.jobPath), plan = readFileSync(item.ctx.planPath);
    const response = await ingest(new NextRequest("http://localhost/api/producer/ingest", { method: "POST",
      body: JSON.stringify({ inputPath: source, projectRoot: item.root, noTranscribe: true }) }));
    assert.equal(response.status, 409); assert.deepEqual(readFileSync(item.ctx.manifestPath), manifest);
    assert.deepEqual(readFileSync(item.ctx.planPath), plan); assert.deepEqual(readFileSync(item.jobPath), journal);
  } finally { item.cleanup(); }
});

test("an already-started editor save cannot cross a newly committed cut checkpoint", async () => {
  const item = fixture("awaiting_cut_approval");
  try {
    const paused = readFileSync(item.jobPath), planBefore = readFileSync(item.ctx.planPath);
    writeFileSync(item.jobPath, JSON.stringify({ ...item.job, status: "failed" }));
    const changed = JSON.parse(planBefore.toString()); changed.target.pace = "fast";
    let writer: ReadableStreamDefaultController<Uint8Array> | undefined;
    const body = new ReadableStream<Uint8Array>({ start: (controller) => { writer = controller; } });
    const response = POST(new NextRequest("http://localhost/api/producer/save-plan", { method: "POST", body }));
    writeFileSync(item.jobPath, paused); // The durable pause wins while request JSON is still in flight.
    writer!.enqueue(new TextEncoder().encode(JSON.stringify({ path: item.ctx.planPath, plan: changed })));
    writer!.close();
    assert.equal((await response).status, 409);
    assert.deepEqual(readFileSync(item.ctx.planPath), planBefore); assert.deepEqual(readFileSync(item.jobPath), paused);
  } finally { item.cleanup(); }
});

test("verification cannot skip a competing live lease, missing journal, or missing actual lease", () => {
  const item = fixture("awaiting_cut_approval");
  try {
    const value = verification(item), held = acquireProjectMutationLease(item.root, "another source mutation");
    assert.ok(held.lease);
    assert.equal(guard(item, value).response?.status, 409); held.lease.release();
    assert.throws(() => cutPreviewLeaseGuard(item.ctx.dir, { release: () => {} }), /ENOENT/);
    rmSync(item.jobPath); assert.equal(guard(item, value).response?.status, 409);
  } finally { item.cleanup(); }
});

test("present malformed or linked journals never become permission to save", () => {
  const item = fixture("awaiting_cut_approval");
  try {
    const original = readFileSync(item.jobPath), linked = path.join(item.ctx.dir, "test-only-journal.json");
    writeFileSync(item.jobPath, "{}"); assert.equal(guard(item).response?.status, 409);
    rmSync(item.jobPath); writeFileSync(linked, original); symlinkSync(linked, item.jobPath);
    assert.equal(guard(item).response?.status, 409); assert.deepEqual(readFileSync(linked), original);
  } finally { item.cleanup(); }
});

test("the verification exemption preserves promotion and cut-repair reconciliation checks", async () => {
  const item = fixture("awaiting_cut_approval");
  try {
    const value = verification(item), marker = path.join(item.ctx.dir, QC_PROMOTION_RECONCILIATION_FILE);
    writeFileSync(marker, "{}");
    const promotion = guard(item, value); assert.ok(promotion.response);
    assert.equal((await promotion.response.json()).code, "PROJECT_RECONCILIATION_REQUIRED"); rmSync(marker);
    const directory = path.join(item.ctx.dir, ".sniper-authority-v1/sagas/cut-repair-review/intents");
    mkdirSync(directory, { recursive: true });
    writeFileSync(path.join(directory, "pending.json"), JSON.stringify({ schemaVersion: 1, idempotencyKey: randomUUID(),
      requestDigest: HASH, expectedParentRevisionHash: HASH, childRevisionHash: HASH, state: "PREPARING",
      artifactHashes: {}, receiptHash: null, recordedAt: new Date().toISOString(), updatedAt: new Date().toISOString() }));
    const repair = guardProjectMutation({ projectRoot: item.root, producerDir: item.ctx.dir,
      operation: "verification cannot waive recovery", allowCutRepairRecovery: true, checkpointVerification: value });
    assert.ok(repair.response); assert.equal((await repair.response.json()).code, "CUT_REPAIR_RECOVERY_REQUIRED");
  } finally { item.cleanup(); }
});
