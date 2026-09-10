import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { runAutoEditPipeline } from "@/app/api/producer/auto-edit/pipeline";
import { cutReviewDescription, currentCutReview, currentCutReviewForMedia, cutReviewReads } from "@/app/api/producer/cut-review/state";
import type { CutPreviewReceiptV1 } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { pauseAutoEditForCutApproval } from "@/lib/server/auto-edit-cut-pause-store";
import { guidedFixture } from "./_guided-cut-fixture";

/** Only preview/media qualification is stubbed here; real decode tests live in cut-preview.test.ts. */
async function fixture(run: (value: Awaited<ReturnType<typeof makeFixture>>) => Promise<void>) {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-cut-review-state-")));
  try { await run(await makeFixture(root)); } finally { rmSync(root, { recursive: true, force: true }); }
}

async function makeFixture(root: string) {
  const fixture = guidedFixture(root);
  const result = await runAutoEditPipeline(fixture.run, fixture.deps);
  if (result.status !== "awaiting_cut_approval" || !result.preview) throw new Error("missing test cut boundary");
  const waiting = pauseAutoEditForCutApproval(fixture.jobPath, fixture.run.job.token, result.request, result.preview);
  const manifestHash = readCutPreviewObject(fixture.ctx.manifestPath).sha256;
  const receipt = { ...result.request, ...result.preview, runId: waiting.token, attempt: waiting.attempts,
    manifestHash, sourceSetDigest: "3".repeat(64), sourceSetReceiptHash: "4".repeat(64),
    createdAt: result.request.createdAt, scope: "cut-only-source-aspect-ungraded-unmixed-not-delivery",
    media: { sha256: "5".repeat(64), videoFrames: 90 }, profile: { fps: "30/1", width: 960, height: 540 },
  } as unknown as CutPreviewReceiptV1;
  const reads: typeof cutReviewReads = { ...cutReviewReads, canonical: () => fixture.ctx.dir,
    preview: (directory, request) => {
      assert.equal(directory, path.join(fixture.ctx.dir, "cut-previews", request.requestHash, receipt.executionKey));
      return receipt;
    },
    object: (file) => {
      const observed = readCutPreviewObject(file);
      return file === fixture.ctx.manifestPath ? { ...observed,
        value: { ...observed.value, sourceSetAdmission: { sourceSetDigest: "3".repeat(64), receiptSha256: "4".repeat(64) } } } : observed;
    },
  };
  return { ...fixture, waiting, result, receipt, reads };
}

test("read-only description binds exact waiting identities without manufacturing acceptance", async () => fixture(async (f) => {
  const before = readFileSync(f.jobPath);
  const review = currentCutReview(f.ctx.dir, f.reads);
  const description = cutReviewDescription(review);
  assert.equal(description.accepted, false);
  assert.equal(description.expectedToken, f.waiting.token);
  assert.equal(description.durationSeconds, 3);
  assert.equal(description.waitStartedAt, f.waiting.updatedAt);
  assert.equal(description.previewStartedAt, f.receipt.createdAt);
  const url = new URL(description.mediaUrl, "http://localhost");
  assert.equal(url.pathname, "/api/producer/cut-review/video");
  assert.equal(url.searchParams.get("requestHash"), f.result.request.requestHash);
  assert.equal(url.searchParams.get("receiptHash"), f.receipt.receiptHash);
  assert.equal(url.searchParams.has("path"), false);
  assert.match(description.caveat, /not an approved final/);
  assert.deepEqual(readFileSync(f.jobPath), before);
}));

test("media route observes proofs without a duplicate movie hash or a current-media claim", async () => fixture(async (f) => {
  let evidenceReads = 0;
  const review = currentCutReviewForMedia(f.ctx.dir, { ...f.reads,
    preview: () => { throw new Error("Duplicate media hash must not run"); },
    evidence: () => { evidenceReads += 1; return { receipt: f.receipt,
      observationScope: "receipt-proofs-and-toolchain-only", mediaBytesObserved: false }; },
  });
  assert.equal(evidenceReads, 1);
  assert.equal(review.mediaBytesObserved, false);
  assert.equal(review.receipt.media.sha256, f.receipt.media.sha256);
}));

test("pointerless checkpoints and mismatched run/attempt/manifest/source proof cannot be reviewed", async () => fixture(async (f) => {
  const original = readFileSync(f.jobPath);
  for (const patch of [{ cutPreview: undefined }, { status: "running" },
    { cutPreview: { ...f.waiting.cutPreview, receiptHash: "6".repeat(64) } }]) {
    writeFileSync(f.jobPath, JSON.stringify({ ...f.waiting, ...patch }));
    assert.throws(() => currentCutReview(f.ctx.dir, f.reads));
    writeFileSync(f.jobPath, original);
  }
  for (const patch of [{ runId: "other" }, { attempt: f.waiting.attempts + 1 },
    { manifestHash: "0".repeat(64) }, { sourceSetDigest: "0".repeat(64) },
    { sourceSetReceiptHash: "0".repeat(64) }, { receiptHash: "0".repeat(64) }]) {
    assert.throws(() => currentCutReview(f.ctx.dir, { ...f.reads, preview: () => ({ ...f.receipt, ...patch }) }), /does not match/);
  }
  assert.deepEqual(readFileSync(f.jobPath), original);
}));

test("a changed journal during private media observation fails without writeback", async () => fixture(async (f) => {
  const changed = JSON.stringify({ ...f.waiting, message: "Changed by another process" });
  const reads = { ...f.reads, preview: () => { writeFileSync(f.jobPath, changed); return f.receipt; } };
  assert.throws(() => currentCutReview(f.ctx.dir, reads), /checkpoint changed/);
  assert.equal(readFileSync(f.jobPath, "utf8"), changed);
}));

test("malformed and backwards waiting clocks cannot appear as qualified user time", async () => fixture(async (f) => {
  const original = readFileSync(f.jobPath);
  for (const updatedAt of [undefined, "invalid", "2026-09-06", "2000-01-01T00:00:00.000Z", "2999-01-01T00:00:00.000Z"]) {
    const changed = JSON.stringify({ ...f.waiting, updatedAt });
    writeFileSync(f.jobPath, changed);
    assert.throws(() => currentCutReview(f.ctx.dir, f.reads), /clocks/);
    assert.equal(readFileSync(f.jobPath, "utf8"), changed);
  }
  writeFileSync(f.jobPath, original);
}));

test("acceptance verification stops user wait and a failed attempt starts a new visible interval", async () => fixture(async (f) => {
  const at = Date.parse(f.waiting.updatedAt), iso = (offset: number) => new Date(at + offset).toISOString();
  const attempt = { idempotencyKey: "12345678-1234-4234-8234-123456789abc",
    executionId: "12345678-1234-4234-8234-123456789abd", decisionHash: "9".repeat(64),
    receivedAt: iso(1000), startedAt: iso(2000), state: "verifying", completedAt: null, error: null };
  writeFileSync(f.jobPath, JSON.stringify({ ...f.waiting, updatedAt: iso(2000), cutAcceptanceAttempt: attempt }));
  const verifying = cutReviewDescription(currentCutReview(f.ctx.dir, f.reads));
  assert.equal(verifying.waitStartedAt, f.waiting.updatedAt);
  assert.equal(verifying.waitStoppedAt, iso(1000)); assert.equal(verifying.acceptanceState, "verifying");
  assert.equal(verifying.accepted, false);
  const failed = { ...f.waiting, updatedAt: iso(3000), cutApprovalWaitStartedAt: iso(3000),
    cutAcceptanceAttempt: { ...attempt, state: "failed", completedAt: iso(3000), error: "Source changed" } };
  writeFileSync(f.jobPath, JSON.stringify(failed));
  const retry = cutReviewDescription(currentCutReview(f.ctx.dir, f.reads));
  assert.equal(retry.waitStartedAt, iso(3000)); assert.equal(retry.waitStoppedAt, null);
  assert.equal(retry.acceptanceState, "verification-failed"); assert.equal(retry.acceptanceError, "Source changed");
  writeFileSync(f.jobPath, JSON.stringify({ ...failed, cutApprovalWaitStartedAt: iso(2500) }));
  assert.throws(() => currentCutReview(f.ctx.dir, f.reads), /new operator waiting interval/);
}));
