import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { test } from "node:test";
import { parseGuidedOpeningApprovalSubmission } from "@/lib/producer/contracts/guided-opening-approval-v1";
import { parseGuidedOpeningApprovalResult, parseGuidedOpeningStatus } from "@/lib/producer/guided-opening-client";
import { GUIDED_OPENING_STATUS_SCOPE } from "@/lib/producer/contracts/guided-opening-status-v1";
import { openingMediaUrl } from "../guided-opening-selection";

const HASH = "a".repeat(64), DIR = "/Users/TEST/producer", SELECTION = "b".repeat(64);
const attestation = { watchedOpening: true, watchedBodyTransition: true, listened: true, approvesOpening: true, understandsBodyPending: true };
function submission(patch: Record<string, unknown> = {}) {
  return { schemaVersion: 1, operation: "approve-guided-opening", idempotencyKey: randomUUID(), expectedToken: "guided-job", expectedJournalHash: HASH,
    selectionHash: SELECTION, coreMediaSha256: HASH, reviewMediaSha256: HASH, attestation, ...patch };
}
function descriptor(range: "core" | "review", end: number, samples: number) {
  return { url: openingMediaUrl({ dir: DIR, selectionHash: SELECTION, mediaSha256: HASH, range }), mediaSha256: HASH, sizeBytes: 10, width: 1920, height: 1080,
    frameRate: "30000/1001", videoFrames: end, startFrame: 0, endFrameExclusive: end, audioSamples: samples };
}
function ready(patch: Record<string, unknown> = {}) {
  return { ok: true, schemaVersion: 1, scope: GUIDED_OPENING_STATUS_SCOPE, state: "ready-for-review", requestId: randomUUID(), executionId: randomUUID(),
    claimHash: HASH, openingApproved: false, deliveryApproved: false, subjectiveListening: "not-performed-by-system", detail: "TEST",
    timing: { generationStartedAt: "2026-09-06T00:00:00.000Z", engineElapsedMs: 10, cleanupElapsedMs: 5, elapsedStatus: "completed", coverage: "recorded-owned-attempt-only" },
    selectionHash: SELECTION, receiptHash: HASH, receiptSha256: HASH, selectionQualifiedAt: "2026-09-06T00:02:01.250Z", sourceFreshness: "not-rechecked-by-status",
    media: { core: descriptor("core", 1800, 2882880), review: descriptor("review", 2100, 3363360) },
    journal: { token: "guided-job", sha256: HASH }, approval: null, ...patch };
}

test("approval submission is closed and every attestation must be explicitly true", () => {
  parseGuidedOpeningApprovalSubmission(submission());
  for (const patch of [{ operation: "approve" }, { attestation: { ...attestation, listened: false } }, { attestation: { ...attestation, extra: true } },
    { selectionHash: "x" }, { expectedToken: "" }, { idempotencyKey: "nope" }, { deliveryApproved: true }]) {
    assert.throws(() => parseGuidedOpeningApprovalSubmission(submission(patch)), `accepted ${JSON.stringify(patch)}`);
  }
  const { attestation: _drop, ...missing } = submission(); void _drop;
  assert.throws(() => parseGuidedOpeningApprovalSubmission(missing));
});

test("the browser accepts approval only as a verified object that agrees with the flag and selection time", () => {
  const plain = parseGuidedOpeningStatus(ready(), DIR);
  assert.equal(plain.openingApproved, false);
  const approved = parseGuidedOpeningStatus(ready({ openingApproved: true, approval: { approvalHash: HASH, approvedAt: "2026-09-06T00:10:00.000Z" } }), DIR);
  assert.equal(approved.openingApproved, true);
  for (const patch of [{ openingApproved: true }, { approval: { approvalHash: HASH, approvedAt: "2026-09-06T00:10:00.000Z" } },
    { openingApproved: true, approval: { approvalHash: HASH, approvedAt: "2026-09-06T00:01:00.000Z" } },
    { openingApproved: true, approval: { approvalHash: "x", approvedAt: "2026-09-06T00:10:00.000Z" } },
    { openingApproved: true, approval: { approvalHash: HASH, approvedAt: "2026-09-06T00:10:00.000Z", extra: 1 } },
    { journal: { token: "", sha256: HASH } }, { journal: { token: "guided-job" } }, { deliveryApproved: true }]) {
    assert.throws(() => parseGuidedOpeningStatus(ready(patch), DIR), `accepted ${JSON.stringify(patch)}`);
  }
  const { journal: _journal, ...withoutJournal } = ready(); void _journal;
  assert.throws(() => parseGuidedOpeningStatus(withoutJournal, DIR));
  assert.throws(() => parseGuidedOpeningStatus({ ...ready(), state: "failed", openingApproved: true }, DIR));
});

test("approval results bind the exact selection and never claim body or delivery", () => {
  const value = { ok: true, replayed: false, approvalHash: HASH, approvedAt: "2026-09-06T00:10:00.000Z", selectionHash: SELECTION,
    openingApproved: true, bodyGenerated: false, deliveryApproved: false };
  assert.equal(parseGuidedOpeningApprovalResult(value, SELECTION).approvalHash, HASH);
  for (const patch of [{ selectionHash: HASH }, { bodyGenerated: true }, { deliveryApproved: true }, { openingApproved: false }, { approvedAt: "soon" }, { extra: 1 }]) {
    assert.throws(() => parseGuidedOpeningApprovalResult({ ...value, ...patch }, SELECTION), `accepted ${JSON.stringify(patch)}`);
  }
});
