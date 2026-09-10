import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  executeRenderGraphV1,
  executeWithForcedFullOracleV1,
  type RenderGraphExecutorV1,
} from "../contracts/render-graph-executor";
import { parseRenderGraphV1 } from "../contracts/render-graph";

const digest = (bytes: Buffer): string =>
  createHash("sha256").update(bytes).digest("hex");
const source = Buffer.from("immutable-source");
const copy = Buffer.from("right-card-copy-v2");
const sourceOutput = Buffer.from(JSON.stringify({
  kind: "source-snapshot",
  dependencies: {},
  inputs: { "source.bytes": digest(source) },
}));

function graph(withSceneEdge = true) {
  return parseRenderGraphV1({
    schemaVersion: 1,
    graphId: "graph-executor-fixture",
    toolchainHash: "a".repeat(64),
    rootNodeId: "node-final",
    nodes: [
      {
        nodeId: "node-source",
        kind: "source-snapshot",
        dependencies: [],
        inputDigests: { "source.bytes": digest(source) },
        outputArtifactHash: digest(sourceOutput),
        frameRange: null,
      },
      {
        nodeId: "node-right-card",
        kind: "scene-unit",
        dependencies: ["node-source"],
        inputDigests: { "scene.right.copy": digest(copy) },
        outputArtifactHash: null,
        frameRange: { startFrame: 1_350, endFrameExclusive: 1_530 },
      },
      {
        nodeId: "node-composite",
        kind: "composite-window",
        dependencies: withSceneEdge
          ? ["node-source", "node-right-card"] : ["node-source"],
        inputDigests: {},
        outputArtifactHash: null,
        frameRange: { startFrame: 1_350, endFrameExclusive: 1_530 },
      },
      {
        nodeId: "node-final",
        kind: "final-export",
        dependencies: ["node-composite"],
        inputDigests: {},
        outputArtifactHash: null,
        frameRange: null,
      },
    ],
  });
}

const executor: RenderGraphExecutorV1 = {
  requiredDependencyIds: (node) =>
    node.nodeId === "node-composite" ? ["node-right-card"] : [],
  render: ({ node, dependencyArtifacts, inputArtifacts }) => Buffer.from(
    JSON.stringify({
      kind: node.kind,
      dependencies: Object.fromEntries(
        [...dependencyArtifacts].map(([id, bytes]) => [id, digest(bytes)]),
      ),
      inputs: Object.fromEntries(
        [...inputArtifacts].map(([key, bytes]) => [key, digest(bytes)]),
      ),
    }),
  ),
};

const proved = executeWithForcedFullOracleV1({
  incremental: {
    graph: graph(),
    inputArtifacts: {
      "source.bytes": source,
      "scene.right.copy": copy,
    },
    cachedArtifacts: new Map([[digest(sourceOutput), sourceOutput]]),
  },
  executor,
});
assert.deepEqual(proved.incremental.reusedNodeIds, ["node-source"]);
assert.deepEqual(proved.incremental.renderedNodeIds, [
  "node-right-card", "node-composite", "node-final",
]);
assert.equal(
  proved.incremental.snapshot.finalArtifactHash,
  proved.forcedFull.snapshot.finalArtifactHash,
);
assert.throws(
  () => executeRenderGraphV1({
    graph: graph(false),
    inputArtifacts: {
      "source.bytes": source,
      "scene.right.copy": copy,
    },
    cachedArtifacts: new Map([[digest(sourceOutput), sourceOutput]]),
  }, executor),
  /outside root closure|missing required dependencies/,
);
assert.throws(
  () => executeRenderGraphV1({
    graph: graph(),
    inputArtifacts: {
      "source.bytes": Buffer.from("mutated"),
      "scene.right.copy": copy,
    },
    cachedArtifacts: new Map([[digest(sourceOutput), sourceOutput]]),
  }, executor),
  /missing or does not match/,
);
assert.throws(
  () => executeRenderGraphV1({
    graph: graph(),
    inputArtifacts: {
      "source.bytes": source,
      "scene.right.copy": copy,
    },
    cachedArtifacts: new Map([[digest(sourceOutput), Buffer.from("corrupt")]]),
  }, executor),
  /missing or corrupt/,
);

console.log("render-graph-executor-v1 tests passed");
