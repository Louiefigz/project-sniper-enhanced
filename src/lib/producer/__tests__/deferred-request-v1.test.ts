import assert from "node:assert/strict";
import { mkdtempSync, realpathSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import {
  reresolveDeferredRequestV1,
  resolveTimingAnchorV1,
} from "../contracts/deferred-request";
import { parseEditRequestV1 } from "../contracts/edit-request";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
  writeAuthorityObjectSync,
} from "../../server/producer-authority-files";

const oldMap = "a".repeat(64);
const newMap = "b".repeat(64);
const cutClause = "10000000-0000-4000-8000-000000000001";
const treatmentClause = "20000000-0000-4000-8000-000000000001";
const request = parseEditRequestV1({
  schemaVersion: 1,
  requestId: "30000000-0000-4000-8000-000000000001",
  idempotencyKey: "40000000-0000-4000-8000-000000000001",
  parentRevisionHash: "c".repeat(64),
  workflow: "cut-first",
  rawIntent: "Trim the opening, then update the card at the same spoken phrase.",
  submittedAt: "2026-07-29T12:00:00.000Z",
  clauses: [
    {
      schemaVersion: 1,
      clauseId: cutClause,
      text: "Trim the opening.",
      state: "committed",
      disposition: "committed by compatibility cut authority",
      blockingClauseIds: [],
    },
    {
      schemaVersion: 1,
      clauseId: treatmentClause,
      text: "Update the card at the same spoken phrase.",
      state: "deferred",
      disposition: "wait for the exact child timeline map",
      blockingClauseIds: [cutClause],
    },
  ],
});

const migration = {
  oldTimelineMapHash: oldMap,
  newTimelineMapHash: newMap,
  successors: {
    "word-old-start": ["word-child-start"],
    "word-old-end": ["word-child-end"],
    "segment-old": ["segment-child"],
  },
  segmentVersions: { "segment-child": 2 },
  tombstones: [],
};
const transitioned = reresolveDeferredRequestV1(request, [{
  clauseId: treatmentClause,
  anchor: {
    type: "transcript-range",
    startWordId: "word-old-start",
    endWordId: "word-old-end",
    offsetFrames: 2,
  },
}], migration);
assert.equal(transitioned.request.clauses[0].state, "committed");
assert.equal(transitioned.request.clauses[1].state, "compiled");
assert.deepEqual(transitioned.receipt.rows[0].anchor, {
  type: "transcript-range",
  startWordId: "word-child-start",
  endWordId: "word-child-end",
  offsetFrames: 2,
});

const frame = resolveTimingAnchorV1({
  type: "timeline-frame",
  frame: 1_350,
  timelineMapHash: oldMap,
}, migration);
assert.equal(frame.status, "resolved");
if (frame.status === "resolved") {
  assert.equal(frame.anchor.type, "timeline-frame");
  assert.equal(frame.anchor.type === "timeline-frame" && frame.anchor.frame, 1_350);
  assert.equal(
    frame.anchor.type === "timeline-frame" && frame.anchor.timelineMapHash,
    newMap,
  );
}
const segment = resolveTimingAnchorV1({
  type: "cut-segment",
  segmentId: "segment-old",
  elementVersion: 1,
  basis: "output-frame",
  offsetFrames: 10,
  timelineMapHash: oldMap,
}, migration);
assert.equal(segment.status, "resolved");
if (segment.status === "resolved" && segment.anchor.type === "cut-segment") {
  assert.equal(segment.anchor.segmentId, "segment-child");
  assert.equal(segment.anchor.elementVersion, 2);
}
assert.equal(resolveTimingAnchorV1({
  type: "semantic-beat",
  beatId: "beat-removed",
}, { ...migration, tombstones: ["beat-removed"] }).status, "dangling");
const dangling = reresolveDeferredRequestV1(request, [{
  clauseId: treatmentClause,
  anchor: { type: "semantic-beat", beatId: "beat-removed" },
}], { ...migration, tombstones: ["beat-removed"] });
assert.equal(dangling.request.clauses[1].state, "ambiguous");
assert.equal(dangling.request.clauses[1].disposition, "beat-removed was removed");
assert.equal(dangling.receipt.rows[0].status, "dangling");
assert.equal(dangling.receipt.rows[0].anchor, undefined);
assert.deepEqual(parseEditRequestV1(JSON.parse(JSON.stringify(dangling.request))), dangling.request);
assert.equal(dangling.request.clauses[0].state, "committed");
assert.equal(resolveTimingAnchorV1({
  type: "section",
  sectionId: "section-split",
}, {
  ...migration,
  successors: {
    ...migration.successors,
    "section-split": ["section-a", "section-b"],
  },
}).status, "ambiguous");
assert.throws(
  () => reresolveDeferredRequestV1(request, [], migration),
  /exactly one anchor/,
);
assert.throws(
  () => reresolveDeferredRequestV1({
    ...request,
    clauses: request.clauses.map((clause) =>
      clause.clauseId === cutClause ? { ...clause, state: "pending" as const } : clause),
  }, [{
    clauseId: treatmentClause,
    anchor: { type: "source-time", sourceId: "source-a", sourceFrame: 10 },
  }], migration),
  /uncommitted blockers/,
);

const producerDir = realpathSync(
  mkdtempSync(path.join(os.tmpdir(), "sniper-deferred-request-")),
);
try {
  const paths = producerAuthorityPaths(producerDir);
  const requestObject = writeAuthorityObjectSync(
    paths.objects.requests,
    transitioned.request,
  );
  const receiptObject = writeAuthorityObjectSync(
    paths.objects.receipts,
    transitioned.receipt,
  );
  const reopenedRequest = parseEditRequestV1(
    assertObjectHashSync(paths.objects.requests, requestObject.hash),
  );
  const reopenedReceipt = assertObjectHashSync(
    paths.objects.receipts,
    receiptObject.hash,
  ) as typeof transitioned.receipt;
  assert.equal(reopenedRequest.clauses[1].state, "compiled");
  assert.deepEqual(reopenedReceipt, transitioned.receipt);
} finally {
  rmSync(producerDir, { recursive: true, force: true });
}

console.log("deferred-request-v1 tests passed");
