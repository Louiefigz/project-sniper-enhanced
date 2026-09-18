import type {
  RenderGraphV1,
  RenderNodeKindV1,
} from "@/lib/producer/contracts/render-graph";

type NodesByKind = Map<RenderNodeKindV1, Set<string>>;

function nodeIdsByKind(graph: RenderGraphV1): NodesByKind {
  const result: NodesByKind = new Map();
  for (const node of graph.nodes) {
    const ids = result.get(node.kind) ?? new Set<string>();
    ids.add(node.nodeId);
    result.set(node.kind, ids);
  }
  return result;
}

function union(
  byKind: NodesByKind,
  kinds: RenderNodeKindV1[],
): Set<string> {
  return new Set(kinds.flatMap((kind) => [...(byKind.get(kind) ?? [])]));
}

function requiredDependencies(
  kind: RenderNodeKindV1,
  byKind: NodesByKind,
): Set<string> {
  if (kind === "timeline-map") return union(byKind, ["source-snapshot"]);
  if (kind === "base-segment" || kind === "dialogue-stem") {
    return union(byKind, ["source-snapshot", "timeline-map"]);
  }
  if (kind === "scene-unit") return union(byKind, ["timeline-map"]);
  if (kind === "caption-shard") {
    return union(byKind, ["source-snapshot", "timeline-map"]);
  }
  if (kind === "composite-window") {
    return union(byKind, [
      "base-segment", "dialogue-stem", "scene-unit", "caption-shard",
    ]);
  }
  if (kind === "final-export") return union(byKind, ["composite-window"]);
  return new Set();
}

/** Match the current Python renderer's required cross-stage dependency edges. */
export function assertCurrentRenderGraphSemanticsV1(
  graph: RenderGraphV1,
): void {
  const byKind = nodeIdsByKind(graph);
  for (const node of graph.nodes) {
    const actual = new Set(node.dependencies);
    const missing = [...requiredDependencies(node.kind, byKind)]
      .filter((dependency) => !actual.has(dependency))
      .sort();
    if (missing.length) {
      throw new Error(
        `render node ${node.nodeId} is missing required dependencies: `
        + missing.join(", "),
      );
    }
  }
}
