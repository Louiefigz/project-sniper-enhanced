import assert from "node:assert/strict";
import {
  assertForcedFullOracleV1,
  invalidateRenderGraphV1,
  parseRenderGraphV1,
  type RenderGraphV1,
} from "../contracts/render-graph";

const hash = (value: string): string => value.repeat(64);

function graph(withSceneEdge = true): RenderGraphV1 {
  return parseRenderGraphV1({
    schemaVersion: 1,
    graphId: "graph-minimum-v1",
    toolchainHash: hash("a"),
    rootNodeId: "node-final",
    nodes: [
      {
        nodeId: "node-source",
        kind: "source-snapshot",
        dependencies: [],
        inputDigests: { "source.bytes": hash("b") },
        outputArtifactHash: hash("c"),
        frameRange: null,
      },
      {
        nodeId: "node-scene-right",
        kind: "scene-unit",
        dependencies: ["node-source"],
        inputDigests: { "scene.right.copy": hash("d") },
        outputArtifactHash: hash("e"),
        frameRange: { startFrame: 100, endFrameExclusive: 200 },
      },
      {
        nodeId: "node-composite",
        kind: "composite-window",
        dependencies: withSceneEdge
          ? ["node-source", "node-scene-right"] : ["node-source"],
        inputDigests: {},
        outputArtifactHash: hash("f"),
        frameRange: { startFrame: 100, endFrameExclusive: 200 },
      },
      {
        nodeId: "node-final",
        kind: "final-export",
        dependencies: ["node-composite"],
        inputDigests: {},
        outputArtifactHash: hash("1"),
        frameRange: null,
      },
    ],
  });
}

const invalidated = invalidateRenderGraphV1(graph(), {
  "scene.right.copy": hash("2"),
});
assert.deepEqual(invalidated.receipt.dirtyNodeIds, [
  "node-scene-right",
  "node-composite",
  "node-final",
]);
assert.deepEqual(invalidated.receipt.cleanNodeIds, ["node-source"]);
assert.deepEqual(invalidated.receipt.dirtyWindows, [{
  startFrame: 100,
  endFrameExclusive: 200,
}]);
assert.equal(
  invalidated.graph.nodes.find((node) => node.nodeId === "node-source")
    ?.outputArtifactHash,
  hash("c"),
);
assert.equal(
  invalidated.graph.nodes.find((node) => node.nodeId === "node-final")
    ?.outputArtifactHash,
  null,
);
assert.throws(
  () => invalidateRenderGraphV1(graph(), { "unbound.render.input": hash("2") }),
  /not bound to the graph/,
);

const equivalent = {
  finalArtifactHash: hash("3"),
  nodeArtifactHashes: {
    "node-source": hash("c"),
    "node-scene-right": hash("4"),
    "node-composite": hash("5"),
    "node-final": hash("3"),
  },
};
assert.doesNotThrow(() => assertForcedFullOracleV1(equivalent, equivalent));

const missingEdge = invalidateRenderGraphV1(graph(false), {
  "scene.right.copy": hash("2"),
});
assert.deepEqual(missingEdge.receipt.dirtyNodeIds, ["node-scene-right"]);
assert.throws(
  () => assertForcedFullOracleV1({
    finalArtifactHash: hash("1"),
    nodeArtifactHashes: {
      "node-source": hash("c"),
      "node-scene-right": hash("4"),
      "node-composite": hash("f"),
      "node-final": hash("1"),
    },
  }, equivalent),
  /forced-full oracle/,
);

const cyclic = structuredClone(graph()) as unknown as Record<string, unknown>;
const cyclicNodes = cyclic.nodes as Array<Record<string, unknown>>;
cyclicNodes[0].dependencies = ["node-final"];
assert.throws(() => parseRenderGraphV1(cyclic), /cycle/);

const unknown = structuredClone(graph()) as unknown as Record<string, unknown>;
(unknown.nodes as Array<Record<string, unknown>>)[1].surprise = true;
assert.throws(() => parseRenderGraphV1(unknown), /unsupported fields/);

console.log("render-graph-v1 tests passed");
