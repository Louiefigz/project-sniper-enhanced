import { createHash } from "node:crypto";
import {
  assertForcedFullOracleV1,
  parseRenderGraphV1,
  type RenderGraphV1,
  type RenderNodeV1,
  type RenderOracleSnapshotV1,
} from "./render-graph";

export interface RenderNodeExecutionV1 {
  node: RenderNodeV1;
  dependencyArtifacts: ReadonlyMap<string, Buffer>;
  inputArtifacts: ReadonlyMap<string, Buffer>;
}

export interface RenderGraphExecutorV1 {
  render: (execution: RenderNodeExecutionV1) => Buffer;
  requiredDependencyIds?: (
    node: RenderNodeV1,
    graph: RenderGraphV1,
  ) => readonly string[];
}

export interface RenderGraphExecutionOptionsV1 {
  graph: RenderGraphV1;
  inputArtifacts: Readonly<Record<string, Buffer>>;
  cachedArtifacts: ReadonlyMap<string, Buffer>;
  forceFull?: boolean;
}

export interface RenderGraphExecutionResultV1 {
  graph: RenderGraphV1;
  snapshot: RenderOracleSnapshotV1;
  renderedNodeIds: string[];
  reusedNodeIds: string[];
  artifactBytes: Map<string, Buffer>;
}

const sha256 = (bytes: Buffer): string =>
  createHash("sha256").update(bytes).digest("hex");

function nodeMap(graph: RenderGraphV1): Map<string, RenderNodeV1> {
  return new Map(graph.nodes.map((node) => [node.nodeId, node]));
}

function assertRootClosure(graph: RenderGraphV1): void {
  const nodes = nodeMap(graph);
  const reachable = new Set<string>();
  const visit = (nodeId: string): void => {
    if (reachable.has(nodeId)) return;
    reachable.add(nodeId);
    nodes.get(nodeId)!.dependencies.forEach(visit);
  };
  visit(graph.rootNodeId);
  const orphaned = graph.nodes
    .map((node) => node.nodeId)
    .filter((nodeId) => !reachable.has(nodeId));
  if (orphaned.length) {
    throw new Error(`render graph has nodes outside root closure: ${orphaned.join(", ")}`);
  }
}

function executionOrder(graph: RenderGraphV1): RenderNodeV1[] {
  const nodes = nodeMap(graph);
  const ordered: RenderNodeV1[] = [];
  const visited = new Set<string>();
  const visit = (nodeId: string): void => {
    if (visited.has(nodeId)) return;
    const node = nodes.get(nodeId)!;
    node.dependencies.forEach(visit);
    visited.add(nodeId);
    ordered.push(node);
  };
  visit(graph.rootNodeId);
  return ordered;
}

function assertRequiredEdges(
  graph: RenderGraphV1,
  executor: RenderGraphExecutorV1,
): void {
  if (!executor.requiredDependencyIds) return;
  for (const node of graph.nodes) {
    const missing = executor.requiredDependencyIds(node, graph)
      .filter((dependency) => !node.dependencies.includes(dependency));
    if (missing.length) {
      throw new Error(
        `render node ${node.nodeId} is missing required dependencies: ${missing.join(", ")}`,
      );
    }
  }
}

function inputBytes(
  node: RenderNodeV1,
  artifacts: Readonly<Record<string, Buffer>>,
): Map<string, Buffer> {
  const result = new Map<string, Buffer>();
  for (const [key, digest] of Object.entries(node.inputDigests)) {
    const bytes = artifacts[key];
    if (!bytes || sha256(bytes) !== digest) {
      throw new Error(`render input ${key} is missing or does not match ${digest}`);
    }
    result.set(key, bytes);
  }
  return result;
}

function dependencyBytes(
  node: RenderNodeV1,
  completed: ReadonlyMap<string, Buffer>,
): Map<string, Buffer> {
  const result = new Map<string, Buffer>();
  for (const dependency of node.dependencies) {
    const bytes = completed.get(dependency);
    if (!bytes) throw new Error(`render dependency ${dependency} has no proved bytes`);
    result.set(dependency, bytes);
  }
  return result;
}

function cachedNode(
  node: RenderNodeV1,
  cache: ReadonlyMap<string, Buffer>,
): Buffer | null {
  if (node.outputArtifactHash === null) return null;
  const bytes = cache.get(node.outputArtifactHash);
  if (!bytes || sha256(bytes) !== node.outputArtifactHash) {
    throw new Error(`cached render artifact for ${node.nodeId} is missing or corrupt`);
  }
  return bytes;
}

/** Execute one closed graph, proving every input, dependency, and cache byte. */
export function executeRenderGraphV1(
  options: RenderGraphExecutionOptionsV1,
  executor: RenderGraphExecutorV1,
): RenderGraphExecutionResultV1 {
  const graph = parseRenderGraphV1(options.graph);
  assertRootClosure(graph);
  assertRequiredEdges(graph, executor);
  const completed = new Map<string, Buffer>();
  const artifacts = new Map<string, Buffer>(options.cachedArtifacts);
  const hashes = new Map<string, string>();
  const renderedNodeIds: string[] = [];
  const reusedNodeIds: string[] = [];
  for (const node of executionOrder(graph)) {
    const dependencies = dependencyBytes(node, completed);
    const inputs = inputBytes(node, options.inputArtifacts);
    const cached = options.forceFull ? null : cachedNode(node, artifacts);
    const bytes = cached ?? executor.render({
      node,
      dependencyArtifacts: dependencies,
      inputArtifacts: inputs,
    });
    const digest = sha256(bytes);
    if (cached) reusedNodeIds.push(node.nodeId);
    else renderedNodeIds.push(node.nodeId);
    completed.set(node.nodeId, bytes);
    artifacts.set(digest, bytes);
    hashes.set(node.nodeId, digest);
  }
  const next = parseRenderGraphV1({
    ...graph,
    nodes: graph.nodes.map((node) => ({
      ...node,
      outputArtifactHash: hashes.get(node.nodeId)!,
    })),
  });
  return {
    graph: next,
    snapshot: {
      finalArtifactHash: hashes.get(graph.rootNodeId)!,
      nodeArtifactHashes: Object.fromEntries(hashes),
    },
    renderedNodeIds,
    reusedNodeIds,
    artifactBytes: artifacts,
  };
}

export interface RenderOracleExecutionOptionsV1 {
  incremental: RenderGraphExecutionOptionsV1;
  executor: RenderGraphExecutorV1;
}

/** Prove an incremental result equals an independent all-node execution. */
export function executeWithForcedFullOracleV1(
  options: RenderOracleExecutionOptionsV1,
): {
  incremental: RenderGraphExecutionResultV1;
  forcedFull: RenderGraphExecutionResultV1;
} {
  const incremental = executeRenderGraphV1(options.incremental, options.executor);
  const forcedFull = executeRenderGraphV1({
    ...options.incremental,
    cachedArtifacts: new Map(),
    forceFull: true,
  }, options.executor);
  assertForcedFullOracleV1(incremental.snapshot, forcedFull.snapshot);
  return { incremental, forcedFull };
}
