import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseClauseStateV1 } from "../contracts/clause-state";
import { parseEditBatchV1 } from "../contracts/edit-batch";
import { parseEditRequestV1 } from "../contracts/edit-request";
import { parseProjectRevisionV1 } from "../contracts/project-revision";
import { parsePositiveRationalV1 } from "../contracts/positive-rational";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../..");
const schemaDir = path.join(root, "schemas", "producer");
const requiredSchemas = [
  "asset-record-v1.schema.json",
  "auto-edit-delivery-receipt-v1.schema.json",
  "clause-state-v1.schema.json",
  "commit-intent-v1.schema.json",
  "caption-repair-revalidation-v1.schema.json",
  "channel-normalization-receipt-v1.schema.json",
  "cut-repair-dialogue-caption-authority-v1.schema.json",
  "cut-repair-candidate-v2.schema.json",
  "cut-repair-composite-receipt-v1.schema.json",
  "cut-repair-automated-qc-bundle-v1.schema.json",
  "cut-repair-alternate-take-selection-v1.schema.json",
  "cut-repair-fragment-receipt-v1.schema.json",
  "cut-repair-media-activation-v1.schema.json",
  "cut-repair-preparation-package-v1.schema.json",
  "cut-repair-rendered-candidate-v1.schema.json",
  "cut-repair-qc-tool-manifest-v1.schema.json",
  "cut-repair-review-action-v1.schema.json",
  "cut-restore-speech-v1.schema.json",
  "current-system-inventory-v1.schema.json",
  "dialogue-map-v1.schema.json",
  "dialogue-program-receipt-v1.schema.json",
  "dialogue-program-request-v1.schema.json",
  "dialogue-stem-receipt-v1.schema.json",
  "dialogue-track-v1.schema.json",
  "edit-batch-v1.schema.json",
  "edit-receipt-v1.schema.json",
  "edit-request-v1.schema.json",
  "external-ingress-registry-v1.schema.json",
  "fps-support-matrix-v1.schema.json",
  "hyperframes-rate-matrix-v1.schema.json",
  "legacy-regression-gates-v1.schema.json",
  "palmier-commit-saga-v1.schema.json",
  "palmier-cut-repair-disposition-v1.schema.json",
  "positive-rational-v1.schema.json",
  "program-audio-mix-registry-v1.schema.json",
  "product-capability-matrix-v1.schema.json",
  "project-revision-v1.schema.json",
  "project-revision-v2.schema.json",
  "projection-receipt-v1.schema.json",
  "render-effect-registry-v1.schema.json",
  "render-graph-v1.schema.json",
  "scene-bundle-v1.schema.json",
  "scene-authoring-packet-v1.schema.json",
  "scene-package-v1.schema.json",
  "scene-readability-receipt-v1.schema.json",
  "scene-spec-v1.schema.json",
  "set-graphic-text-v1.schema.json",
  "short-long-route-matrix-v1.schema.json",
  "timing-anchor-v1.schema.json",
  "treatment-operation-v1.schema.json",
];
for (const name of requiredSchemas) {
  const schema = JSON.parse(fs.readFileSync(path.join(schemaDir, name), "utf8")) as {
    additionalProperties?: boolean;
    unevaluatedProperties?: boolean;
    oneOf?: Array<{ additionalProperties?: boolean }>;
  };
  const closed = schema.additionalProperties === false
    || schema.unevaluatedProperties === false
    || schema.oneOf?.every((branch) => branch.additionalProperties === false);
  assert.equal(closed, true, `${name} must reject unknown fields`);
}

const hash = (value: string): string => value.repeat(64);
const clauseId = "10000000-0000-4000-8000-000000000001";
const request = parseEditRequestV1({
  schemaVersion: 1,
  requestId: "20000000-0000-4000-8000-000000000001",
  idempotencyKey: "30000000-0000-4000-8000-000000000001",
  parentRevisionHash: hash("a"),
  workflow: "cut-first",
  rawIntent: "Change only the right card copy.",
  submittedAt: "2026-07-29T12:00:00.000Z",
  clauses: [{
    schemaVersion: 1,
    clauseId,
    text: "Change only the right card copy.",
    state: "candidate-executed",
    disposition: "compiled to SetGraphicTextV1",
    blockingClauseIds: [],
  }],
});
assert.equal(request.clauses.length, 1);

const batch = parseEditBatchV1({
  schemaVersion: 1,
  batchId: "40000000-0000-4000-8000-000000000001",
  requestId: request.requestId,
  idempotencyKey: request.idempotencyKey,
  stage: "treatment",
  atomic: true,
  preserveUnrelated: true,
  base: {
    projectRevisionHash: request.parentRevisionHash,
    planContentHash: hash("b"),
    manifestHash: hash("c"),
    sourceSnapshotSetHash: hash("d"),
    timelineMapHash: hash("e"),
    canvasProfileHash: hash("f"),
    destinationProfileHashes: [hash("1")],
    pictureLockHash: hash("2"),
  },
  operations: [{
    schemaVersion: 1,
    operationId: "50000000-0000-4000-8000-000000000001",
    clauseId,
    action: {
      schemaVersion: 1,
      operation: "SetGraphicTextV1",
      target: { lane: "graphicsTrack", id: "g-00000001" },
      text: "New copy",
      expectedCurrentText: "Old copy",
    },
  }],
}, request);
assert.equal(batch.operations[0].action.operation, "SetGraphicTextV1");
assert.deepEqual(
  parsePositiveRationalV1({ numerator: "30000", denominator: "1001" }),
  { numerator: "30000", denominator: "1001" },
);
assert.throws(
  () => parsePositiveRationalV1({ numerator: "60", denominator: "2" }),
  /must be reduced/,
);
assert.throws(
  () => parsePositiveRationalV1({ numerator: "030", denominator: "1" }),
  /canonical positive integer/,
);

const inheritedClause = Object.create({ hidden: true }) as Record<string, unknown>;
Object.assign(inheritedClause, request.clauses[0]);
assert.doesNotThrow(() => parseClauseStateV1(inheritedClause));
assert.throws(
  () => parseClauseStateV1({ ...request.clauses[0], extra: true }),
  /unsupported fields/,
);
assert.throws(
  () => parseEditRequestV1({ ...request, workflow: "shortform" }),
  /cut-first, autopilot/,
);
assert.throws(
  () => parseProjectRevisionV1({
    schemaVersion: 1,
    parentRevisionHash: null,
    planContentHash: hash("a"),
    manifestHash: hash("b"),
    sourceSnapshotSetHash: hash("c"),
    transcriptTimingHash: hash("d"),
    timelineMapHash: hash("e"),
    canvasProfileHash: hash("f"),
    destinationProfileHashes: [],
    pictureLockHash: null,
    workflowState: "READY",
    requestLedgerHash: hash("1"),
    renderGraphHash: hash("2"),
    projectionReceiptHash: null,
    authoritativeSidecars: {},
  }),
  /workflowState/,
);

console.log("producer-contracts-v1 tests passed");
