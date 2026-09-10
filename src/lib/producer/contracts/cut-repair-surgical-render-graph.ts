import type { CutRepairPicturePlanAuthorityV1 } from
  "./cut-repair-picture-plan-authority";
import type { CutRestoreSpeechV1, FrameRangeV1 } from
  "./cut-restore-speech-v1";
import {
  parseRenderGraphV1,
  type RenderGraphV1,
  type RenderNodeV1,
} from "./render-graph";
import { exactKeys, objectValue, sha256 } from "./validation";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";

const NODE_IDS = [
  "node-source", "node-timeline", "node-base",
  "node-composite", "node-final",
] as const;
const SUPPORTED_PLAN_KEYS = new Set([
  "planVersion", "target", "cutTrack", "cutDecisions",
  "cutRepairPicturePlanAuthority",
]);
const DELIVERY_DISPOSITION = {
  candidateConstruction: "proved-composite-exact-byte-copy",
  planReconstruction: "surgical-terminal-not-plan-only-reconstructable",
  palmier: "reference-media-only-no-native-editability",
} as const;

const NODE_EXPECTATIONS = {
  "node-source": {
    kind: "source-snapshot", dependencies: [], digestKeys: null,
  },
  "node-timeline": {
    kind: "timeline-map", dependencies: ["node-source"],
    digestKeys: [
      "timeline.plan", "timeline.stageRoot", "surgical.childTimeline",
    ],
  },
  "node-base": {
    kind: "base-segment", dependencies: ["node-source", "node-timeline"],
    digestKeys: [
      "base.plan", "base.stageRoot", "base.manifestStageRoot",
      "surgical.operation", "surgical.pictureAuthority",
      "surgical.fragmentReceipt", "surgical.compositeReceipt",
      "surgical.dependencyPartition", "surgical.parentRenderAuthority",
      "surgical.contract",
    ],
  },
  "node-composite": {
    kind: "composite-window", dependencies: ["node-base"],
    digestKeys: [
      "composite.plan", "composite.stageRoot",
      "surgical.terminalReceipt", "surgical.outsideDirtyOracle",
    ],
  },
  "node-final": {
    kind: "final-export", dependencies: ["node-composite"],
    digestKeys: [
      "final.plan", "final.stageRoot", "final.manifestStageRoot",
      "surgical.terminalReceipt", "surgical.deliveryDisposition",
    ],
  },
} as const;

export interface CutRepairSurgicalGraphBinding {
  graph: unknown;
  plan: Record<string, unknown>;
  planContentHash: string;
  operation: CutRestoreSpeechV1;
  operationHash: string;
  pictureAuthority: CutRepairPicturePlanAuthorityV1;
  childTimelineMapHash: string;
  fragmentReceipt: Record<string, unknown>;
  compositeReceipt: Record<string, unknown>;
  candidateHash: string;
  parentRenderAuthorityHash: string;
  terminalReceiptHash?: string;
}

function same(value: unknown, expected: unknown): boolean {
  return canonicalJsonSha256(value) === canonicalJsonSha256(expected);
}

function assertSourceInputs(node: RenderNodeV1): void {
  const keys = Object.keys(node.inputDigests);
  const sources = keys.filter((key) => /^source\.\d{4}$/u.test(key));
  const required = ["source.manifest", "source.set", "source.stageRoot"];
  if (!sources.length
      || keys.length !== required.length + sources.length
      || required.some((key) => !(key in node.inputDigests))
      || sources.some((key, index) =>
        key !== `source.${String(index).padStart(4, "0")}`)) {
    throw new Error("picture repair surgical source closure is malformed");
  }
}

function assertNodeShape(
  node: RenderNodeV1,
  nodeId: typeof NODE_IDS[number],
): void {
  const expected = NODE_EXPECTATIONS[nodeId];
  if (node.kind !== expected.kind
      || !same(node.dependencies, expected.dependencies)) {
    throw new Error(`picture repair surgical ${nodeId} shape is malformed`);
  }
  if (expected.digestKeys === null) {
    assertSourceInputs(node);
    return;
  }
  exactKeys(
    node.inputDigests, expected.digestKeys, expected.digestKeys,
    `picture repair surgical ${nodeId} inputs`);
}

function nodes(graph: RenderGraphV1): Record<string, RenderNodeV1> {
  const actual = graph.nodes.map((node) => node.nodeId).sort();
  if (graph.rootNodeId !== "node-final"
      || !same(actual, [...NODE_IDS].sort())) {
    throw new Error("picture repair graph is not the fixed surgical closure");
  }
  const result = Object.fromEntries(
    graph.nodes.map((node) => [node.nodeId, node]));
  NODE_IDS.forEach((nodeId) => assertNodeShape(result[nodeId], nodeId));
  return result;
}

function assertFrameRanges(
  value: Record<string, RenderNodeV1>,
  dirty: FrameRangeV1,
): void {
  const dirtyIds = new Set(["node-base", "node-composite"]);
  for (const nodeId of NODE_IDS) {
    const expected = dirtyIds.has(nodeId) ? dirty : null;
    if (!same(value[nodeId].frameRange, expected)) {
      throw new Error("picture repair surgical dirty range is malformed");
    }
  }
}

function partitionHash(operation: CutRestoreSpeechV1): string {
  return canonicalJsonSha256({
    revalidatedDependentIds: operation.revalidatedDependentIds,
    unchangedDependentIds: operation.unchangedDependentIds,
  });
}

function assertMediaDigests(
  value: Record<string, RenderNodeV1>,
  binding: CutRepairSurgicalGraphBinding,
): void {
  const base = value["node-base"].inputDigests;
  const composite = value["node-composite"].inputDigests;
  const final = value["node-final"].inputDigests;
  const outside = objectValue(
    binding.compositeReceipt.outsideDirtyOracle,
    "picture repair outside-dirty oracle");
  const expected = [
    [base["surgical.operation"], binding.operationHash],
    [base["surgical.pictureAuthority"],
      binding.pictureAuthority.authorityHash],
    [base["surgical.fragmentReceipt"],
      canonicalJsonSha256(binding.fragmentReceipt)],
    [base["surgical.compositeReceipt"],
      canonicalJsonSha256(binding.compositeReceipt)],
    [base["surgical.dependencyPartition"],
      partitionHash(binding.operation)],
    [base["surgical.parentRenderAuthority"],
      sha256(binding.parentRenderAuthorityHash, "surgical parent render")],
    [composite["surgical.outsideDirtyOracle"],
      canonicalJsonSha256(outside)],
    [final["final.plan"], binding.planContentHash],
    [final["surgical.deliveryDisposition"],
      canonicalJsonSha256(DELIVERY_DISPOSITION)],
  ];
  if (expected.some(([actual, wanted]) => actual !== wanted)
      || composite["surgical.terminalReceipt"]
        !== final["surgical.terminalReceipt"]
      || (binding.terminalReceiptHash !== undefined
        && final["surgical.terminalReceipt"]
          !== sha256(binding.terminalReceiptHash, "surgical terminal hash"))) {
    throw new Error("picture repair surgical graph digests are stale");
  }
}

/** Require the exact five-node picture-repair graph and all known digests. */
export function assertCutRepairSurgicalRenderGraph(
  binding: CutRepairSurgicalGraphBinding,
): RenderGraphV1 {
  const unsupported = Object.keys(binding.plan).filter(
    (key) => !SUPPORTED_PLAN_KEYS.has(key)).sort();
  if (unsupported.length) {
    throw new Error(
      `SURGICAL_TERMINAL_PLAN_LANE_UNSUPPORTED:${unsupported.join(",")}`);
  }
  const graph = parseRenderGraphV1(binding.graph);
  const value = nodes(graph);
  const timeline = value["node-timeline"].inputDigests;
  const base = value["node-base"].inputDigests;
  const composite = value["node-composite"].inputDigests;
  const dirty = binding.pictureAuthority.dirtyFrameRange;
  if (timeline["surgical.childTimeline"]
        !== sha256(binding.childTimelineMapHash, "surgical child timeline")
      || timeline["timeline.plan"] !== base["base.plan"]
      || composite["composite.plan"] !== canonicalJsonSha256({
        graphicsTrack: [], captionsTrack: null,
      })
      || !["node-base", "node-composite", "node-final"].every(
        (nodeId) => value[nodeId].outputArtifactHash
          === sha256(binding.candidateHash, "surgical candidate"))) {
    throw new Error("picture repair surgical graph authority is stale");
  }
  assertFrameRanges(value, dirty);
  assertMediaDigests(value, binding);
  return graph;
}
