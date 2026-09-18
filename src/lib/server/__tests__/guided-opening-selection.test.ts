import assert from "node:assert/strict";
import { test } from "node:test";
import { parseGuidedHandoffPointerV2 } from "@/lib/producer/contracts/guided-workflow-v2";
import { openingMediaDescriptors, openingMediaUrl, selectedOpeningRow } from "../guided-opening-selection";
import { readGuidedOpeningStatus, guidedOpeningStatusReads } from "../guided-opening-status";

const HASH = "a".repeat(64), ROOT = "/private/tmp/TEST-ONLY/media-output";
function record(overrides: Record<string, unknown> = {}) {
  const row = (name: string, end: number, samples: number) => ({ path: `${ROOT}/${name}.mp4`, sha256: HASH, sizeBytes: 1234,
    startFrame: 0, endFrameExclusive: end, startSample: 0, endSampleExclusive: samples, ...overrides });
  return { authority: { frameRate: "30000/1001", totalFrames: 3000, target: { width: 1920, height: 1080 },
    core: { startFrame: 0, endFrameExclusive: 1800 }, review: { startFrame: 0, endFrameExclusive: 2100 } },
    media: { core: row("core", 1800, 2882880), review: row("review", 2100, 3363360) } };
}

test("an identical opening/context range legitimately shares core.mp4; any divergence in row or span still rejects it", () => {
  const same = { startFrame: 0, endFrameExclusive: 1800 };
  const shared = record(); shared.authority.review = same; shared.media.review = { ...shared.media.core };
  const review = selectedOpeningRow(shared, "review", ROOT);
  assert.equal(review.path, `${ROOT}/core.mp4`); assert.equal(review.videoFrames, 1800);
  assert.equal(selectedOpeningRow(shared, "core", ROOT).mediaSha256, review.mediaSha256);
  const spanDiffers = record(); spanDiffers.media.review = { ...spanDiffers.media.core, endFrameExclusive: 2100, endSampleExclusive: 3363360 };
  assert.throws(() => selectedOpeningRow(spanDiffers, "review", ROOT), /fixed private range artifact/);
  const bytesDiffer = record(); bytesDiffer.authority.review = same; bytesDiffer.media.review = { ...bytesDiffer.media.core, sha256: "b".repeat(64) };
  assert.throws(() => selectedOpeningRow(bytesDiffer, "review", ROOT), /fixed private range artifact/);
  const coreNamedReview = record(); coreNamedReview.media.core = { ...coreNamedReview.media.core, path: `${ROOT}/review.mp4` };
  assert.throws(() => selectedOpeningRow(coreNamedReview, "core", ROOT), /fixed private range artifact/);
});

test("selected rows are derived only from the held record with fixed private roles and exact ties-even sample clocks", () => {
  const core = selectedOpeningRow(record(), "core", ROOT), review = selectedOpeningRow(record(), "review", ROOT);
  assert.equal(core.videoFrames, 1800); assert.equal(core.audioSamples, 2882880); assert.equal(review.videoFrames, 2100);
  assert.equal(core.frameRate, "30000/1001"); assert.equal(core.width, 1920); assert.equal(core.path, `${ROOT}/core.mp4`);
  assert.throws(() => selectedOpeningRow(record(), "core", "/private/tmp/OTHER"), /fixed private range artifact/);
  assert.throws(() => selectedOpeningRow(record({ path: `${ROOT}/other.mp4` }), "core", ROOT), /fixed private range artifact/);
  assert.throws(() => selectedOpeningRow(record({ startFrame: 1 }), "core", ROOT), /differs from its authority/);
  assert.throws(() => selectedOpeningRow(record({ endFrameExclusive: 1799 }), "core", ROOT), /differs from its authority/);
  assert.throws(() => selectedOpeningRow(record({ sha256: "zz" }), "core", ROOT));
});

test("descriptors carry only guarded local URLs bound to the exact selection and pass the browser contract", () => {
  const rows = { core: selectedOpeningRow(record(), "core", ROOT), review: selectedOpeningRow(record(), "review", ROOT) };
  const media = openingMediaDescriptors("/Users/TEST/producer", "b".repeat(64), rows);
  assert.equal(media.core.url, openingMediaUrl({ dir: "/Users/TEST/producer", selectionHash: "b".repeat(64), mediaSha256: HASH, range: "core" }));
  assert.equal("path" in media.core, false); assert.equal(media.review.videoFrames, 2100);
  assert.match(media.core.url, /^\/api\/producer\/guided-opening\/media\?/);
  const bad = { ...rows, review: { ...rows.review, audioSamples: rows.review.audioSamples + 1 } };
  assert.throws(() => openingMediaDescriptors("/Users/TEST/producer", "b".repeat(64), bad), /inconsistent/);
});

test("selection pointer requires committed cleanup; a newer claim outranks it; an unverifiable selection is unavailable", () => {
  const base = { schemaVersion: 2, cutDecisionHash: HASH, cutActivationHash: HASH, pictureLockedRevisionHash: HASH, treatmentAdmissionHash: HASH,
    treatmentProposalHash: HASH, proposalReadinessHash: HASH, treatmentDraftRevisionHash: HASH };
  assert.throws(() => parseGuidedHandoffPointerV2({ ...base, openingMediaSelectionHash: HASH }), /committed resource cleanup/);
  parseGuidedHandoffPointerV2({ ...base, openingCleanupHash: HASH, openingMediaSelectionHash: HASH });
  const job = { sha256: HASH, job: { token: "guided-job", ctx: { workflowV2: { schemaVersion: 2, mode: "guided", afterCut: "treatment-then-intro", approvalPolicy: "explicit-human" } },
    guidedHandoffV2: { openingCleanupHash: HASH, openingMediaSelectionHash: "b".repeat(64) } } };
  const rows = { core: selectedOpeningRow(record(), "core", ROOT), review: selectedOpeningRow(record(), "review", ROOT) };
  const held = { claimHash: "c".repeat(64), claim: { requestId: "d".repeat(36), executionId: "e".repeat(36), generationStartedAt: "2026-09-06T12:00:00.000Z" } };
  const observed = { evidence: { stop: { receipt: { elapsedMs: 5000 } }, output: { elapsedMs: 300 } } };
  let selectionReads = 0;
  const reads = { job: () => job, claim: () => { throw new Error("no claim"); }, stopped: () => { throw new Error("no stop"); },
    cleanup: () => { throw new Error("cleanup must not be consulted when a selection exists"); },
    selection: () => { selectionReads += 1; return { selectionHash: "b".repeat(64), fact: { schemaVersion: 1 }, held, observed, rows, selectionQualifiedAt: "2026-09-06T12:30:00.000Z",
      receiptHash: HASH, receiptSha256: HASH, sourceFreshness: "not-rechecked-by-status" as const }; },
    approval: () => null } as unknown as typeof guidedOpeningStatusReads;
  const ready = readGuidedOpeningStatus("/Users/TEST/producer", reads);
  assert.equal(ready.state, "ready-for-review"); assert.equal(selectionReads, 1);
  if (ready.state !== "ready-for-review") throw new Error("unreachable");
  assert.equal(ready.selectionHash, "b".repeat(64)); assert.equal(ready.sourceFreshness, "not-rechecked-by-status");
  assert.equal(ready.media.core.videoFrames, 1800); assert.equal(ready.timing.engineElapsedMs, 5000); assert.equal(ready.openingApproved, false);
  assert.equal(ready.approval, null); assert.equal(ready.journal.token, "guided-job");
  const approved = readGuidedOpeningStatus("/Users/TEST/producer", { ...reads, approval: () => ({ approvalHash: "e".repeat(64), approvedAt: "2026-09-06T12:45:00.000Z", decisionHash: HASH }) } as unknown as typeof guidedOpeningStatusReads);
  assert.equal(approved.state, "ready-for-review"); assert.equal(approved.openingApproved, true);
  if (approved.state === "ready-for-review") assert.equal(approved.approval?.approvalHash, "e".repeat(64));
  const drifted = readGuidedOpeningStatus("/Users/TEST/producer", { ...reads, approval: () => { throw new Error("TEST approval drift"); } } as unknown as typeof guidedOpeningStatusReads);
  assert.equal(drifted.state, "unavailable"); assert.match(drifted.detail, /approval does not bind/);
  Object.assign(job.job.guidedHandoffV2, { openingExecutionClaimHash: "f".repeat(64) });
  const readsBeforeClaim = selectionReads;
  const newer = readGuidedOpeningStatus("/Users/TEST/producer", { ...reads, claim: () => ({ ...job, claimHash: "f".repeat(64), claim: held.claim }) } as unknown as typeof guidedOpeningStatusReads);
  assert.equal(newer.state, "pending-owned-execution"); assert.equal(selectionReads, readsBeforeClaim);
  delete (job.job.guidedHandoffV2 as Record<string, unknown>).openingExecutionClaimHash;
  const broken = readGuidedOpeningStatus("/Users/TEST/producer", { ...reads, selection: () => { throw new Error("TEST lineage drift"); } } as unknown as typeof guidedOpeningStatusReads);
  assert.equal(broken.state, "unavailable"); assert.match(broken.detail, /could not be verified/); assert.equal("media" in broken, false);
});
