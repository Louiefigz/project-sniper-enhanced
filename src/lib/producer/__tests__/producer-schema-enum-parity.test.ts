import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { CLAUSE_STATES } from "../contracts/clause-state";
import { COMMIT_INTENT_STATES } from "../contracts/commit-intent";
import { EDIT_RECEIPT_STATUSES } from "../contracts/edit-receipt";
import { WORKFLOW_STATES } from "../contracts/project-revision";
import { RENDER_NODE_KINDS } from "../contracts/render-graph";
import { TREATMENT_OPERATION_NAMES } from "../contracts/treatment-operation";

const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../..",
);
const schemaDir = path.join(root, "schemas", "producer");
const schema = (name: string): Record<string, unknown> =>
  JSON.parse(fs.readFileSync(path.join(schemaDir, name), "utf8"));

assert.deepEqual(
  (schema("clause-state-v1.schema.json").properties as Record<string, {
    enum: string[];
  }>).state.enum,
  [...CLAUSE_STATES],
);
assert.deepEqual(
  (schema("project-revision-v1.schema.json").properties as Record<string, {
    enum: string[];
  }>).workflowState.enum,
  [...WORKFLOW_STATES],
);
assert.deepEqual(
  (schema("project-revision-v2.schema.json").properties as Record<string, {
    enum: string[];
  }>).workflowState.enum,
  [...WORKFLOW_STATES],
);
assert.deepEqual(
  ((schema("render-graph-v1.schema.json").properties as {
    nodes: { items: { properties: { kind: { enum: string[] } } } };
  }).nodes.items.properties.kind.enum),
  [...RENDER_NODE_KINDS],
);
assert.deepEqual(
  (schema("edit-receipt-v1.schema.json").properties as Record<string, {
    enum: string[];
  }>).status.enum,
  [...EDIT_RECEIPT_STATUSES],
);
assert.deepEqual(
  (schema("palmier-commit-saga-v1.schema.json").properties as Record<string, {
    enum: string[];
  }>).state.enum,
  [...COMMIT_INTENT_STATES],
);
const receiptOperations = (
  (schema("edit-receipt-v1.schema.json").properties as {
    operations: { items: { properties: { operation: { enum: string[] } } } };
  }).operations.items.properties.operation.enum
);
assert.deepEqual(
  receiptOperations,
  ["SetGraphicTextV1", "cut.restoreSpeech", ...TREATMENT_OPERATION_NAMES],
);

console.log("producer-schema-enum-parity tests passed");
