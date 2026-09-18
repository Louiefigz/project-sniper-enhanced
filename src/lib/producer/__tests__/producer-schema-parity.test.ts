import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { fireSparklesScene } from "./_scene-package-v1-fixture";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../..");
const hash = (value: string): string => value.repeat(64);
const uuid = (value: string): string =>
  `${value}0000000-0000-4000-8000-000000000001`;

const clause = {
  schemaVersion: 1,
  clauseId: uuid("1"),
  text: "Change the right card copy.",
  state: "candidate-executed",
  disposition: "compiled to SetGraphicTextV1",
  blockingClauseIds: [],
};
const request = {
  schemaVersion: 1,
  requestId: uuid("2"),
  idempotencyKey: uuid("3"),
  parentRevisionHash: hash("a"),
  workflow: "cut-first",
  rawIntent: clause.text,
  submittedAt: "2026-07-29T12:00:00.000Z",
  clauses: [clause],
};
const operation = {
  schemaVersion: 1,
  operationId: uuid("4"),
  clauseId: clause.clauseId,
  action: {
    schemaVersion: 1,
    operation: "SetGraphicTextV1",
    target: { lane: "graphicsTrack", id: "g-00000001" },
    text: "New copy",
    expectedCurrentText: "Old copy",
  },
};
const base = {
  projectRevisionHash: hash("a"),
  planContentHash: hash("b"),
  manifestHash: hash("c"),
  sourceSnapshotSetHash: hash("d"),
  timelineMapHash: hash("e"),
  canvasProfileHash: hash("f"),
  destinationProfileHashes: [hash("1")],
  pictureLockHash: hash("2"),
};
const batch = {
  schemaVersion: 1,
  batchId: uuid("5"),
  requestId: request.requestId,
  idempotencyKey: request.idempotencyKey,
  stage: "treatment",
  atomic: true,
  preserveUnrelated: true,
  base,
  operations: [operation],
};
const graph = {
  schemaVersion: 1,
  graphId: "graph-schema-parity",
  toolchainHash: hash("3"),
  rootNodeId: "node-final",
  nodes: [{
    nodeId: "node-final",
    kind: "final-export",
    dependencies: [],
    inputDigests: { plan: hash("b") },
    outputArtifactHash: hash("4"),
    frameRange: null,
  }],
};
const revision = {
  schemaVersion: 1,
  parentRevisionHash: hash("a"),
  planContentHash: hash("b"),
  manifestHash: hash("c"),
  sourceSnapshotSetHash: hash("d"),
  transcriptTimingHash: hash("5"),
  timelineMapHash: hash("e"),
  canvasProfileHash: hash("f"),
  destinationProfileHashes: [hash("1")],
  pictureLockHash: hash("2"),
  workflowState: "TREATMENT_DRAFT",
  requestLedgerHash: hash("6"),
  renderGraphHash: hash("7"),
  projectionReceiptHash: null,
  authoritativeSidecars: { compatibilityLock: hash("2") },
};
const revisionV2 = {
  ...revision,
  schemaVersion: 2,
  planObjectHash: hash("9"),
};
const receipt = {
  schemaVersion: 1,
  receiptId: uuid("6"),
  requestId: request.requestId,
  batchId: batch.batchId,
  idempotencyKey: request.idempotencyKey,
  parentRevisionHash: hash("a"),
  childRevisionHash: hash("8"),
  status: "candidate-proved",
  recordedAt: request.submittedAt,
  operations: [{
    operationId: operation.operationId,
    clauseId: clause.clauseId,
    operation: "SetGraphicTextV1",
    executionState: "candidate-executed",
    beforeHash: hash("b"),
    afterHash: hash("9"),
    dirtyNodeIds: ["node-final"],
    explanation: "proved",
  }],
  dirtyWindows: [{ startFrame: 1_350, endFrameExclusive: 1_530 }],
  invariantProofHash: hash("0"),
};
const projection = {
  schemaVersion: 1,
  canonicalPlanHash: hash("b"),
  manifestHash: hash("c"),
  sourceSnapshotSetHash: hash("d"),
  compilerHash: hash("3"),
  timelineMapHash: hash("e"),
  projectionHash: hash("4"),
  generationPath: "compiled/parity/edit_plan.render.json",
};
const scene = fireSparklesScene(hash("b"));
const bundle = JSON.parse(fs.readFileSync(path.join(
  root,
  "scripts/producer/tests/fixtures/fire-sparkles-bundle/bundle.json",
), "utf8")) as Record<string, unknown>;
const treatmentOperation = {
  schemaVersion: 1,
  operation: "title.setText",
  sceneId: "scene-045",
  elementId: "right-copy",
  variable: "rightTitle",
  text: "Repaired copy",
  expectedText: "Change only this card",
  expectedSceneVersion: 1,
};
const readability = {
  schemaVersion: 1,
  passed: true,
  method: "actual-footage-box-worst-pixel-v1",
  sourceSha256: hash("9"),
  sourceFps: { numerator: "30", denominator: "1" },
  frameRange: { startFrame: 1350, endFrameExclusive: 1530 },
  sampleFrames: [1350, 1440, 1529],
  samplePixelCount: 192,
  textBoxPixels: [100, 100, 800, 400],
  textColor: "#FFFFFF",
  backing: {
    color: "#000000",
    opacity: 0.8,
    assetProofSha256: hash("8"),
  },
  minimumContrast: 7.2,
  requiredContrast: 4.5,
  ffmpegSha256: hash("7"),
};
const assetRecord = {
  schemaVersion: 1,
  assetId: "approved-fire-texture",
  sha256: hash("d"),
  sizeBytes: 123,
  mime: "image/png",
  origin: "approved-library",
  acquiredAt: "2026-07-29T12:00:00Z",
  rights: {
    license: "internal-library-v1",
    allowedUses: ["commercial"],
    allowedPlatforms: ["youtube"],
    consent: "not-applicable",
    attributionRequired: false,
  },
  media: { width: 32, height: 32, hasAlpha: true },
  provenance: { source: "library/fire-texture.png" },
  publicationDisposition: "approved",
};
const scenePackage = {
  schemaVersion: 1,
  scene,
  publicationContext: {
    use: "commercial",
    platform: "youtube",
    evaluatedAt: "2026-07-29T12:00:00Z",
  },
  assets: [],
  readability: {
    required: true,
    sourceSha256: hash("9"),
    receipt: readability,
  },
};
const authoringPacket = {
  schemaVersion: 1,
  attemptId: "attempt-scene-045",
  brief: "Blue fire card left; sparkling title card right.",
  sceneAuthority: {
    sceneId: "scene-045",
    timing: scene.timing,
    durationFrames: 180,
    canvas: scene.canvas,
    renderMode: scene.renderMode,
    captionPolicy: scene.captionPolicy,
    provenance: scene.provenance,
  },
  brandTokens: { accent: "#054BC9", cornerRadius: 28 },
  approvedAssets: [],
  examples: [{
    bundleId: "fire-sparkles-cards",
    bundleHash: hash("b"),
  }],
  constraints: {
    hyperframesVersion: "0.7.33",
    declaredVariables: true,
    pausedSeekableTimeline: true,
    rootDuration: true,
    deterministicSeed: true,
    vendoredRuntimeOnly: true,
    renderTimeNetwork: false,
  },
};
const documents = [
  ["asset-record-v1.schema.json", assetRecord],
  ["clause-state-v1.schema.json", clause],
  ["edit-request-v1.schema.json", request],
  ["edit-batch-v1.schema.json", batch],
  ["render-graph-v1.schema.json", graph],
  ["project-revision-v1.schema.json", revision],
  ["project-revision-v2.schema.json", revisionV2],
  ["edit-receipt-v1.schema.json", receipt],
  ["projection-receipt-v1.schema.json", projection],
  ["scene-spec-v1.schema.json", scene],
  ["scene-bundle-v1.schema.json", bundle],
  ["scene-authoring-packet-v1.schema.json", authoringPacket],
  ["scene-package-v1.schema.json", scenePackage],
  ["treatment-operation-v1.schema.json", treatmentOperation],
  ["scene-readability-receipt-v1.schema.json", readability],
  ["timing-anchor-v1.schema.json", {
    type: "transcript-range",
    startWordId: "word-0001",
    endWordId: "word-0002",
    offsetFrames: -1,
  }],
  ["palmier-commit-saga-v1.schema.json", {
    schemaVersion: 1,
    sagaId: uuid("7"),
    idempotencyKey: uuid("8"),
    state: "PREPARING",
    expectedLocalParentHash: hash("a"),
    reservedLocalChildHash: hash("b"),
    expectedPalmierParentId: "palmier-parent",
    reservedPalmierCandidateId: "palmier-candidate",
    reservedPalmierCandidateHash: hash("c"),
    reservedPalmierTimelineHash: hash("d"),
    activationReadback: null,
    updatedAt: "2026-07-29T12:00:00.000Z",
  }],
] as const;
const cases = documents.flatMap(([name, document]) => [
  { schema: name, document },
  { schema: name, document: { ...document, crossLanguageSurprise: true } },
]);
const python = spawnSync(
  path.join(root, ".venv", "bin", "python3"),
  [path.join(root, "scripts", "producer", "contracts", "schema_validator.py"),
    "--batch"],
  { cwd: root, input: JSON.stringify(cases), encoding: "utf8" },
);
assert.equal(python.status, 0, python.stderr);
const results = JSON.parse(python.stdout) as Array<{ valid: boolean; error?: string }>;
assert.equal(results.length, cases.length);
for (let index = 0; index < results.length; index += 2) {
  assert.equal(results[index].valid, true, results[index].error);
  assert.equal(results[index + 1].valid, false);
  assert.match(results[index + 1].error ?? "", /unsupported field|oneOf branch/);
}

console.log("producer-schema-parity tests passed");
