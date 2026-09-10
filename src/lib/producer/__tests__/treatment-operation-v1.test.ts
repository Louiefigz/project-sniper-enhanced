import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { parseEditBatchV1 } from "../contracts/edit-batch";
import { parseEditReceiptV1 } from "../contracts/edit-receipt";
import {
  parseTreatmentOperationV1,
  TREATMENT_OPERATION_NAMES,
} from "../contracts/treatment-operation";
import {
  fireSparklesScene,
  fixtureHash,
  treatmentEnvelope,
} from "./_scene-package-v1-fixture";

const base = (operation: string) => ({ schemaVersion: 1, operation });
const actions = [
  { ...base("scene.add"), scene: fireSparklesScene() },
  {
    ...base("scene.setVariable"),
    sceneId: "scene-045",
    elementId: "left-blue-card",
    variable: "leftColor",
    value: "#0011AA",
    expectedValue: "#0B5FFF",
    expectedSceneVersion: 1,
  },
  {
    ...base("scene.move"),
    sceneId: "scene-045",
    startFrame: 1500,
    endFrameExclusive: 1680,
    timelineMapHash: fixtureHash("d"),
    expectedSceneVersion: 1,
  },
  {
    ...base("scene.remove"),
    sceneId: "scene-045",
    expectedSceneVersion: 1,
  },
  {
    ...base("title.setText"),
    sceneId: "scene-045",
    elementId: "right-copy",
    variable: "rightTitle",
    text: "Repaired copy",
    expectedText: "Change only this card",
    expectedSceneVersion: 1,
  },
  {
    ...base("transition.set"),
    transitionId: "seam-hook",
    expectedValue: {
      id: "seam-hook",
      outFrame: 300,
      kind: "white-flash",
      sfx: false,
    },
    value: {
      id: "seam-hook",
      outFrame: 600,
      kind: "light-leak",
      sfx: false,
    },
  },
  {
    ...base("sfx.set"),
    transitionId: "seam-hook",
    expectedSfx: false,
    sfx: "soft-whoosh",
  },
  {
    ...base("grade.set"),
    expectedGrade: "none",
    grade: "warm",
  },
] as const;

function everyReleasedActionPassesTheBatchBoundary(): void {
  const parsed = actions.map(parseTreatmentOperationV1);
  assert.deepEqual(
    parsed.map((action) => action.operation),
    [...TREATMENT_OPERATION_NAMES],
  );
  for (const action of actions) {
    const batch = parseEditBatchV1(treatmentEnvelope(action));
    assert.equal(batch.stage, "treatment");
    assert.equal(batch.operations[0].action.operation, action.operation);
  }
}

function unknownAndMalformedActionsFailClosed(): void {
  assert.throws(
    () => parseTreatmentOperationV1({
      schemaVersion: 1,
      operation: "scene.executeJavascript",
      code: "process.exit()",
    }),
    /must be one of/,
  );
  assert.throws(
    () => parseTreatmentOperationV1({ ...actions[4], surprise: true }),
    /unsupported fields/,
  );
  assert.throws(
    () => parseTreatmentOperationV1({ ...actions[4], text: " \n " }),
    /nonblank/,
  );
  assert.throws(
    () => parseTreatmentOperationV1({
      ...actions[1],
      value: Number.NaN,
    }),
    /finite scalar/,
  );
  assert.throws(
    () => parseTreatmentOperationV1({
      ...actions[5],
      value: { ...actions[5].value, id: "other-seam" },
    }),
    /IDs differ/,
  );
  assert.throws(
    () => parseTreatmentOperationV1({
      ...actions[2],
      endFrameExclusive: 1500,
    }),
    /range must be nonempty/,
  );
  assert.throws(
    () => parseEditBatchV1({
      ...treatmentEnvelope(actions[0]),
      stage: "cut",
    }),
    /another stage/,
  );
}

function editReceiptsCarryTheClosedActionNames(): void {
  const receipt = {
    schemaVersion: 1,
    receiptId: "60000000-0000-4000-8000-000000000001",
    requestId: "20000000-0000-4000-8000-000000000001",
    batchId: "40000000-0000-4000-8000-000000000001",
    idempotencyKey: "30000000-0000-4000-8000-000000000001",
    parentRevisionHash: fixtureHash("a"),
    childRevisionHash: fixtureHash("b"),
    status: "candidate-proved",
    recordedAt: "2026-07-29T12:00:00.000Z",
    operations: [{
      operationId: "50000000-0000-4000-8000-000000000001",
      clauseId: "10000000-0000-4000-8000-000000000001",
      operation: "title.setText",
      executionState: "candidate-executed",
      beforeHash: fixtureHash("c"),
      afterHash: fixtureHash("d"),
      dirtyNodeIds: ["scene-unit-right"],
      explanation: "right copy rendered without touching the left unit",
    }],
    dirtyWindows: [{ startFrame: 1350, endFrameExclusive: 1530 }],
    invariantProofHash: fixtureHash("e"),
  };
  assert.equal(
    parseEditReceiptV1(receipt).operations[0].operation,
    "title.setText",
  );
  assert.throws(
    () => parseEditReceiptV1({
      ...receipt,
      operations: [{ ...receipt.operations[0], operation: "shell.exec" }],
    }),
    /operation is unsupported/,
  );
}

function pythonSchemasAcceptOnlyTheClosedDocuments(): void {
  const root = process.cwd();
  const cases: Array<{ schema: string; document: unknown }> = actions.flatMap((action) => [
    { schema: "treatment-operation-v1.schema.json", document: action },
    {
      schema: "treatment-operation-v1.schema.json",
      document: { ...action, crossLanguageSurprise: true },
    },
  ]);
  cases.push({
    schema: "edit-batch-v1.schema.json",
    document: treatmentEnvelope(actions[4]),
  });
  const python = spawnSync(
    path.join(root, ".venv", "bin", "python3"),
    [path.join(
      root,
      "scripts/producer/contracts/schema_validator.py",
    ), "--batch"],
    { cwd: root, input: JSON.stringify(cases), encoding: "utf8" },
  );
  assert.equal(python.status, 0, python.stderr);
  const results = JSON.parse(python.stdout) as Array<{
    valid: boolean;
    error?: string;
  }>;
  for (let index = 0; index < actions.length * 2; index += 2) {
    assert.equal(results[index].valid, true, results[index].error);
    assert.equal(results[index + 1].valid, false);
  }
  assert.equal(results.at(-1)?.valid, true, results.at(-1)?.error);
}

everyReleasedActionPassesTheBatchBoundary();
unknownAndMalformedActionsFailClosed();
editReceiptsCarryTheClosedActionNames();
pythonSchemasAcceptOnlyTheClosedDocuments();
console.log("treatment-operation-v1 tests passed");
