import fs from "node:fs";
import path from "node:path";
import type { CutRepairRenderExecutor } from
  "@/app/api/producer/ai-edit/cut-repair-private-render";
import {
  canonicalJsonSha256,
  fileSha256,
} from "../auto-edit-hash";
import { planObjectContentHash } from "../auto-edit-authority";
import {
  pictureTerminal,
  writeTestJson,
  type PrivatePictureFixture,
} from "./_p2-cut-repair-private-picture-input-fixture";

interface ArtifactPaths {
  source: string;
  timeline: string;
}

function baseInputs(
  item: PrivatePictureFixture,
  terminal: Record<string, unknown>,
) {
  const prepared = item.prepared;
  const picture = prepared.picturePlanAuthority!;
  return {
    "base.plan": "3".repeat(64),
    "base.stageRoot": "4".repeat(64),
    "base.manifestStageRoot": "5".repeat(64),
    "surgical.operation": prepared.operationHash,
    "surgical.pictureAuthority": picture.authorityHash,
    "surgical.fragmentReceipt": canonicalJsonSha256(prepared.fragmentReceipt),
    "surgical.compositeReceipt": canonicalJsonSha256(prepared.compositeReceipt),
    "surgical.dependencyPartition": canonicalJsonSha256({
      revalidatedDependentIds: prepared.operation.revalidatedDependentIds,
      unchangedDependentIds: prepared.operation.unchangedDependentIds,
    }),
    "surgical.parentRenderAuthority": terminal.parentRenderAuthorityHash,
    "surgical.contract": terminal.contractHash,
  };
}

function sourceNodes(
  item: PrivatePictureFixture,
  artifacts: ArtifactPaths,
) {
  return [
    {
      nodeId: "node-source", kind: "source-snapshot", dependencies: [],
      inputDigests: {
        "source.manifest": "7".repeat(64),
        "source.set": "8".repeat(64),
        "source.stageRoot": "9".repeat(64),
        "source.0000": "a".repeat(64),
      },
      outputArtifactHash: fileSha256(artifacts.source), frameRange: null,
    },
    {
      nodeId: "node-timeline", kind: "timeline-map",
      dependencies: ["node-source"],
      inputDigests: {
        "timeline.plan": "3".repeat(64),
        "timeline.stageRoot": "a".repeat(64),
        "surgical.childTimeline": item.prepared.reviewTimelineMapHash,
      },
      outputArtifactHash: fileSha256(artifacts.timeline), frameRange: null,
    },
  ];
}

function outputNodes(
  item: PrivatePictureFixture,
  candidate: string,
  terminal: Record<string, unknown>,
) {
  const prepared = item.prepared;
  const dirty = prepared.picturePlanAuthority!.dirtyFrameRange;
  const candidateHash = fileSha256(candidate);
  const terminalHash = canonicalJsonSha256(terminal);
  return [
    {
      nodeId: "node-base", kind: "base-segment",
      dependencies: ["node-source", "node-timeline"],
      inputDigests: baseInputs(item, terminal),
      outputArtifactHash: candidateHash, frameRange: dirty,
    },
    {
      nodeId: "node-composite", kind: "composite-window",
      dependencies: ["node-base"],
      inputDigests: {
        "composite.plan": canonicalJsonSha256({
          graphicsTrack: [], captionsTrack: null,
        }),
        "composite.stageRoot": "b".repeat(64),
        "surgical.terminalReceipt": terminalHash,
        "surgical.outsideDirtyOracle": canonicalJsonSha256(
          prepared.compositeReceipt.outsideDirtyOracle),
      },
      outputArtifactHash: candidateHash, frameRange: dirty,
    },
    {
      nodeId: "node-final", kind: "final-export",
      dependencies: ["node-composite"],
      inputDigests: {
        "final.plan": planObjectContentHash(prepared.reviewPlan),
        "final.stageRoot": "c".repeat(64),
        "final.manifestStageRoot": "d".repeat(64),
        "surgical.terminalReceipt": terminalHash,
        "surgical.deliveryDisposition": canonicalJsonSha256(
          terminal.deliveryDisposition),
      },
      outputArtifactHash: candidateHash, frameRange: null,
    },
  ];
}

function graph(
  item: PrivatePictureFixture,
  candidate: string,
  terminal: Record<string, unknown>,
  artifacts: ArtifactPaths,
) {
  return {
    schemaVersion: 1,
    graphId: "picture-render-test",
    toolchainHash: "6".repeat(64),
    rootNodeId: "node-final",
    nodes: [
      ...sourceNodes(item, artifacts),
      ...outputNodes(item, candidate, terminal),
    ],
  };
}

function artifactRows(
  candidate: string,
  artifacts: ArtifactPaths,
) {
  const rows = [
    ["node-source", artifacts.source],
    ["node-timeline", artifacts.timeline],
    ["node-base", candidate],
    ["node-composite", candidate],
    ["node-final", candidate],
  ];
  return rows.map(([nodeId, artifactPath]) => ({
    nodeId, path: artifactPath, sha256: fileSha256(artifactPath)!,
    sizeBytes: fs.statSync(artifactPath).size,
  }));
}

function publishGraph(
  item: PrivatePictureFixture,
  candidate: string,
  terminal: Record<string, unknown>,
  artifacts: ArtifactPaths,
) {
  const graphValue = graph(item, candidate, terminal, artifacts);
  const graphHash = canonicalJsonSha256(graphValue);
  const receipt = {
    schemaVersion: 1, kind: "current-render-graph-execution",
    graphHash, executionMode: "incremental",
    previousGraphHash: item.parentGraphHash,
    dirtyNodeIds: [
      "node-source", "node-timeline", "node-base",
      "node-composite", "node-final",
    ],
    reusedNodeIds: [],
    artifacts: artifactRows(candidate, artifacts),
  };
  const receiptHash = canonicalJsonSha256(receipt);
  const generation = path.join(
    item.producer, ".render-graph-v1", "generations", graphHash);
  writeTestJson(path.join(generation, "graph.json"), graphValue);
  writeTestJson(
    path.join(generation, "receipts", `${receiptHash}.json`), receipt);
  const pointer = {
    schemaVersion: 1, kind: "current-render-graph-candidate",
    candidatePath: candidate, candidateSha256: fileSha256(candidate),
    graphHash, receiptHash, previousGraphHash: item.parentGraphHash,
    previousReceiptHash: item.parentReceiptHash,
  };
  const pointerKey = canonicalJsonSha256({
    kind: "current-render-candidate-path", path: candidate,
  });
  writeTestJson(path.join(
    item.producer, ".render-graph-v1", "candidates",
    `${pointerKey}.json`), pointer);
  return { graphHash, receiptHash, dirtyNodeIds: receipt.dirtyNodeIds };
}

function stage(item: PrivatePictureFixture, args: string[]) {
  const candidate = args[args.indexOf("--candidate") + 1];
  const artifactDir = args[args.indexOf("--artifact-dir") + 1];
  fs.copyFileSync(item.composite, candidate);
  const artifacts = {
    source: path.join(artifactDir, "source-receipt.json"),
    timeline: path.join(artifactDir, "timeline_map.json"),
  };
  writeTestJson(artifacts.source, { source: true });
  writeTestJson(artifacts.timeline, { timeline: true });
  const terminal = pictureTerminal(item, candidate);
  const terminalPath = path.join(
    artifactDir, "cut_repair_surgical_terminal_receipt.json");
  writeTestJson(terminalPath, terminal);
  const published = publishGraph(item, candidate, terminal, artifacts);
  return {
    status: "render_graph_candidate_staged",
    ...published,
    terminalReceiptHash: canonicalJsonSha256(terminal),
    terminalReceiptPath: terminalPath,
    candidateSha256: fileSha256(candidate), candidatePath: candidate,
    previousGraphHash: item.parentGraphHash,
    previousReceiptHash: item.parentReceiptHash,
    parentMediaSha256: item.parentMediaHash,
    reusedNodeIds: [],
  };
}

export function privatePictureExecutor(
  item: PrivatePictureFixture,
  calls: string[],
): CutRepairRenderExecutor {
  return async (script, args) => {
    calls.push(script);
    return {
      code: 0, stderr: "",
      stdout: `${JSON.stringify(stage(item, args))}\n`,
    };
  };
}
