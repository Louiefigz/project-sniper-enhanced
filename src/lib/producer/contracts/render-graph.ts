import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import {
  enumValue,
  exactKeys,
  hashRecord,
  objectValue,
  sha256,
  stableId,
  uniqueStrings,
} from "./validation";

export const RENDER_NODE_KINDS = [
  "source-snapshot",
  "timeline-map",
  "base-segment",
  "dialogue-stem",
  "scene-unit",
  "caption-shard",
  "composite-window",
  "preview",
  "final-export",
] as const;

export type RenderNodeKindV1 = typeof RENDER_NODE_KINDS[number];

export interface FrameRangeV1 {
  startFrame: number;
  endFrameExclusive: number;
}

export interface RenderNodeV1 {
  nodeId: string;
  kind: RenderNodeKindV1;
  dependencies: string[];
  inputDigests: Record<string, string>;
  outputArtifactHash: string | null;
  frameRange: FrameRangeV1 | null;
}

export interface RenderGraphV1 {
  schemaVersion: 1;
  graphId: string;
  toolchainHash: string;
  rootNodeId: string;
  nodes: RenderNodeV1[];
}

export interface InvalidationReceiptV1 {
  schemaVersion: 1;
  graphBeforeHash: string;
  graphAfterHash: string;
  changedInputKeys: string[];
  dirtyNodeIds: string[];
  cleanNodeIds: string[];
  dirtyWindows: FrameRangeV1[];
}

const INVALIDATION_KEYS = [
  "schemaVersion", "graphBeforeHash", "graphAfterHash", "changedInputKeys",
  "dirtyNodeIds", "cleanNodeIds", "dirtyWindows",
] as const;

const GRAPH_KEYS = ["schemaVersion", "graphId", "toolchainHash", "rootNodeId", "nodes"];
const NODE_KEYS = [
  "nodeId", "kind", "dependencies", "inputDigests",
  "outputArtifactHash", "frameRange",
];

function frameRange(value: unknown, label: string): FrameRangeV1 | null {
  if (value === null) return null;
  const range = objectValue(value, label);
  exactKeys(
    range,
    ["startFrame", "endFrameExclusive"],
    ["startFrame", "endFrameExclusive"],
    label,
  );
  if (!Number.isSafeInteger(range.startFrame)
      || !Number.isSafeInteger(range.endFrameExclusive)
      || Number(range.startFrame) < 0
      || Number(range.endFrameExclusive) <= Number(range.startFrame)) {
    throw new Error(`${label} must be a positive half-open integer frame range`);
  }
  return {
    startFrame: Number(range.startFrame),
    endFrameExclusive: Number(range.endFrameExclusive),
  };
}

function parseNode(value: unknown, index: number): RenderNodeV1 {
  const node = objectValue(value, `RenderGraphV1.nodes[${index}]`);
  exactKeys(node, NODE_KEYS, NODE_KEYS, `RenderGraphV1.nodes[${index}]`);
  return {
    nodeId: stableId(node.nodeId, `nodes[${index}].nodeId`),
    kind: enumValue(node.kind, RENDER_NODE_KINDS, `nodes[${index}].kind`),
    dependencies: uniqueStrings(node.dependencies, `nodes[${index}].dependencies`),
    inputDigests: hashRecord(node.inputDigests, `nodes[${index}].inputDigests`),
    outputArtifactHash: node.outputArtifactHash === null
      ? null : sha256(node.outputArtifactHash, `nodes[${index}].outputArtifactHash`),
    frameRange: frameRange(node.frameRange, `nodes[${index}].frameRange`),
  };
}

function assertDag(graph: RenderGraphV1): void {
  const nodes = new Map(graph.nodes.map((node) => [node.nodeId, node]));
  if (nodes.size !== graph.nodes.length || !nodes.has(graph.rootNodeId)) {
    throw new Error("RenderGraphV1 has duplicate nodes or a missing root");
  }
  for (const node of graph.nodes) {
    if (node.dependencies.includes(node.nodeId)) throw new Error("render node depends on itself");
    const missing = node.dependencies.find((dependency) => !nodes.has(dependency));
    if (missing) throw new Error(`unknown render dependency ${missing}`);
  }
  const visiting = new Set<string>();
  const visited = new Set<string>();
  const visit = (nodeId: string): void => {
    if (visiting.has(nodeId)) throw new Error("RenderGraphV1 contains a cycle");
    if (visited.has(nodeId)) return;
    visiting.add(nodeId);
    nodes.get(nodeId)!.dependencies.forEach(visit);
    visiting.delete(nodeId);
    visited.add(nodeId);
  };
  graph.nodes.forEach((node) => visit(node.nodeId));
}

export function parseRenderGraphV1(value: unknown): RenderGraphV1 {
  const graph = objectValue(value, "RenderGraphV1");
  exactKeys(graph, GRAPH_KEYS, GRAPH_KEYS, "RenderGraphV1");
  if (graph.schemaVersion !== 1 || !Array.isArray(graph.nodes) || !graph.nodes.length) {
    throw new Error("RenderGraphV1 version or nodes are invalid");
  }
  const parsed: RenderGraphV1 = {
    schemaVersion: 1,
    graphId: stableId(graph.graphId, "RenderGraphV1.graphId"),
    toolchainHash: sha256(graph.toolchainHash, "RenderGraphV1.toolchainHash"),
    rootNodeId: stableId(graph.rootNodeId, "RenderGraphV1.rootNodeId"),
    nodes: graph.nodes.map(parseNode),
  };
  assertDag(parsed);
  return parsed;
}

function directDirty(node: RenderNodeV1, changed: Record<string, string>): boolean {
  return Object.entries(changed).some(
    ([key, digest]) => node.inputDigests[key] !== undefined
      && node.inputDigests[key] !== digest,
  );
}

function dirtyClosure(graph: RenderGraphV1, changed: Record<string, string>): Set<string> {
  const dirty = new Set(
    graph.nodes.filter((node) => directDirty(node, changed)).map((node) => node.nodeId),
  );
  let grew = true;
  while (grew) {
    const added = graph.nodes.filter((node) => !dirty.has(node.nodeId)
      && node.dependencies.some((dependency) => dirty.has(dependency)));
    added.forEach((node) => dirty.add(node.nodeId));
    grew = added.length > 0;
  }
  return dirty;
}

function assertChangesBound(
  graph: RenderGraphV1,
  changed: Record<string, string>,
): void {
  const bound = new Set(graph.nodes.flatMap((node) => Object.keys(node.inputDigests)));
  const missing = Object.keys(changed).filter((key) => !bound.has(key));
  if (missing.length) {
    throw new Error(`render-affecting inputs are not bound to the graph: ${missing.join(", ")}`);
  }
}

function mergedWindows(nodes: RenderNodeV1[]): FrameRangeV1[] {
  const ranges = nodes.flatMap((node) => node.frameRange ? [node.frameRange] : [])
    .sort((left, right) => left.startFrame - right.startFrame);
  const merged: FrameRangeV1[] = [];
  for (const range of ranges) {
    const tail = merged.at(-1);
    if (!tail || range.startFrame > tail.endFrameExclusive) merged.push({ ...range });
    else tail.endFrameExclusive = Math.max(tail.endFrameExclusive, range.endFrameExclusive);
  }
  return merged;
}

export function invalidateRenderGraphV1(
  value: RenderGraphV1,
  changedInputs: Record<string, string>,
): { graph: RenderGraphV1; receipt: InvalidationReceiptV1 } {
  const graph = parseRenderGraphV1(value);
  const changes = hashRecord(changedInputs, "changedInputs");
  assertChangesBound(graph, changes);
  const dirty = dirtyClosure(graph, changes);
  const next = parseRenderGraphV1({
    ...graph,
    nodes: graph.nodes.map((node) => ({
      ...node,
      inputDigests: Object.fromEntries(Object.entries(node.inputDigests).map(
        ([key, digest]) => [key, changes[key] ?? digest],
      )),
      outputArtifactHash: dirty.has(node.nodeId) ? null : node.outputArtifactHash,
    })),
  });
  const dirtyNodes = next.nodes.filter((node) => dirty.has(node.nodeId));
  return {
    graph: next,
    receipt: {
      schemaVersion: 1,
      graphBeforeHash: canonicalJsonSha256(graph),
      graphAfterHash: canonicalJsonSha256(next),
      changedInputKeys: Object.keys(changes).sort(),
      dirtyNodeIds: dirtyNodes.map((node) => node.nodeId),
      cleanNodeIds: next.nodes.filter((node) => !dirty.has(node.nodeId))
        .map((node) => node.nodeId),
      dirtyWindows: mergedWindows(dirtyNodes),
    },
  };
}

export function parseInvalidationReceiptV1(
  value: unknown,
): InvalidationReceiptV1 {
  const receipt = objectValue(value, "InvalidationReceiptV1");
  exactKeys(
    receipt,
    INVALIDATION_KEYS,
    INVALIDATION_KEYS,
    "InvalidationReceiptV1",
  );
  if (receipt.schemaVersion !== 1) {
    throw new Error("InvalidationReceiptV1 version is unsupported");
  }
  if (!Array.isArray(receipt.dirtyWindows)) {
    throw new Error("InvalidationReceiptV1.dirtyWindows must be an array");
  }
  const dirtyWindows = receipt.dirtyWindows.map((item, index) => {
    const parsed = frameRange(item, `dirtyWindows[${index}]`);
    if (!parsed) throw new Error(`dirtyWindows[${index}] cannot be null`);
    return parsed;
  });
  const dirtyNodeIds = uniqueStrings(receipt.dirtyNodeIds, "dirtyNodeIds");
  const cleanNodeIds = uniqueStrings(receipt.cleanNodeIds, "cleanNodeIds");
  if (dirtyNodeIds.some((nodeId) => cleanNodeIds.includes(nodeId))) {
    throw new Error("dirty and clean render-node sets overlap");
  }
  return {
    schemaVersion: 1,
    graphBeforeHash: sha256(receipt.graphBeforeHash, "graphBeforeHash"),
    graphAfterHash: sha256(receipt.graphAfterHash, "graphAfterHash"),
    changedInputKeys: uniqueStrings(receipt.changedInputKeys, "changedInputKeys"),
    dirtyNodeIds,
    cleanNodeIds,
    dirtyWindows,
  };
}

export interface RenderOracleSnapshotV1 {
  finalArtifactHash: string;
  nodeArtifactHashes: Record<string, string>;
}

export function assertForcedFullOracleV1(
  incremental: RenderOracleSnapshotV1,
  forcedFull: RenderOracleSnapshotV1,
): void {
  const left = {
    finalArtifactHash: sha256(incremental.finalArtifactHash, "incremental final"),
    nodeArtifactHashes: hashRecord(incremental.nodeArtifactHashes, "incremental nodes"),
  };
  const right = {
    finalArtifactHash: sha256(forcedFull.finalArtifactHash, "forced-full final"),
    nodeArtifactHashes: hashRecord(forcedFull.nodeArtifactHashes, "forced-full nodes"),
  };
  if (canonicalJsonSha256(left) !== canonicalJsonSha256(right)) {
    throw new Error("incremental render does not match the forced-full oracle");
  }
}
