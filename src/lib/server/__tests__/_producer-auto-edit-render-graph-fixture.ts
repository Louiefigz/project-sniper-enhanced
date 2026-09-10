import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import {
  canonicalJson,
  canonicalJsonSha256,
  fileSha256,
} from "../auto-edit-hash";

export interface AutoEditGraphFixtureInput {
  producer: string;
  candidatePath: string;
  planContentHash: string;
  manifestHash: string;
  sourceSetHash: string;
  toolchainHash?: string;
}

const hash = (value: string): string => createHash("sha256")
  .update(value).digest("hex");

const sourceEntries = `${canonicalJson([])}\n`;
export const EMPTY_SOURCE_SET_DIGEST = createHash("sha256")
  .update("sniper-producer-source-set-v1\0")
  .update(sourceEntries)
  .digest("hex");

function writeJson(filePath: string, value: unknown): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${canonicalJson(value)}\n`);
}

interface GraphArtifacts {
  source: string;
  timeline: string;
  candidateHash: string;
}

function sourceAuthority(producer: string): string {
  const external = path.join(producer, ".sniper-external-media");
  fs.mkdirSync(path.join(external, "receipts"), { recursive: true });
  const document = {
    schemaVersion: 1,
    policy: "sniper-producer-source-set-v1",
    entries: [],
    sourceSetDigest: EMPTY_SOURCE_SET_DIGEST,
  };
  const payload = `${canonicalJson(document)}\n`;
  const receiptHash = createHash("sha256").update(payload).digest("hex");
  const receipt = path.join(
    producer, ".sniper-source-sets", `${receiptHash}.json`);
  fs.mkdirSync(path.dirname(receipt), { recursive: true });
  fs.writeFileSync(receipt, payload);
  return receipt;
}

function prepareArtifacts(
  input: AutoEditGraphFixtureInput,
): GraphArtifacts {
  const source = sourceAuthority(input.producer);
  const timeline = path.join(input.producer, "timeline_map.json");
  fs.writeFileSync(timeline, "timeline-map");
  return {
    source,
    timeline,
    candidateHash: fileSha256(input.candidatePath)!,
  };
}

function graphValue(
  input: AutoEditGraphFixtureInput,
  artifacts: GraphArtifacts,
) {
  return {
    schemaVersion: 1,
    graphId: "auto-edit-genesis-fixture",
    toolchainHash: input.toolchainHash ?? hash("toolchain"),
    rootNodeId: "node-final",
    nodes: [
      {
        nodeId: "node-source",
        kind: "source-snapshot",
        dependencies: [],
        inputDigests: {
          "source.manifest": input.manifestHash,
          "source.set": input.sourceSetHash,
          "source.stageRoot": hash("source-stage-root"),
        },
        outputArtifactHash: fileSha256(artifacts.source),
        frameRange: null,
      },
      {
        nodeId: "node-timeline",
        kind: "timeline-map",
        dependencies: ["node-source"],
        inputDigests: { "timeline.plan": input.planContentHash },
        outputArtifactHash: fileSha256(artifacts.timeline),
        frameRange: null,
      },
      {
        nodeId: "node-final",
        kind: "final-export",
        dependencies: ["node-timeline"],
        inputDigests: { "final.plan": input.planContentHash },
        outputArtifactHash: artifacts.candidateHash,
        frameRange: null,
      },
    ],
  };
}

function receiptValue(
  input: AutoEditGraphFixtureInput,
  artifacts: GraphArtifacts,
  graphHash: string,
) {
  const rows = [
    ["node-source", artifacts.source],
    ["node-timeline", artifacts.timeline],
    ["node-final", input.candidatePath],
  ].map(([nodeId, artifactPath]) => ({
    nodeId,
    path: artifactPath,
    sha256: fileSha256(artifactPath),
    sizeBytes: fs.statSync(artifactPath).size,
  }));
  return {
    schemaVersion: 1,
    kind: "current-render-graph-execution",
    graphHash,
    executionMode: "incremental",
    previousGraphHash: null,
    dirtyNodeIds: ["node-source", "node-timeline", "node-final"],
    reusedNodeIds: [],
    artifacts: rows,
  };
}

function publishPointer(
  input: AutoEditGraphFixtureInput,
  artifacts: GraphArtifacts,
  graphHash: string,
  receiptHash: string,
): void {
  const key = canonicalJsonSha256({
    kind: "current-render-candidate-path",
    path: input.candidatePath,
  });
  writeJson(path.join(
    input.producer, ".render-graph-v1", "candidates", `${key}.json`), {
    schemaVersion: 1,
    kind: "current-render-graph-candidate",
    candidatePath: input.candidatePath,
    candidateSha256: artifacts.candidateHash,
    graphHash,
    receiptHash,
    previousGraphHash: null,
    previousReceiptHash: null,
  });
}

/** Publish one fully re-openable staged graph generation for authority tests. */
export function stageAutoEditGraphFixture(
  input: AutoEditGraphFixtureInput,
): string {
  const artifacts = prepareArtifacts(input);
  const graph = graphValue(input, artifacts);
  const graphHash = canonicalJsonSha256(graph);
  const receipt = receiptValue(input, artifacts, graphHash);
  const receiptHash = canonicalJsonSha256(receipt);
  const root = path.join(
    input.producer, ".render-graph-v1", "generations", graphHash);
  writeJson(path.join(root, "graph.json"), graph);
  writeJson(path.join(root, "receipts", `${receiptHash}.json`), receipt);
  publishPointer(input, artifacts, graphHash, receiptHash);
  return graphHash;
}
