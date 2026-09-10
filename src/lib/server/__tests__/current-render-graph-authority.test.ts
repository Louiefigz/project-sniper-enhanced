import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { canonicalJsonSha256, fileSha256 } from "../auto-edit-hash";
import { observeCurrentRenderGraphAuthoritySync } from
  "../current-render-graph-authority";
import { observeStagedRenderGraphAuthoritySync } from
  "../staged-render-graph-authority";

interface GraphFixture {
  root: string;
  producer: string;
  candidate: string;
  graphPath: string;
  graphHash: string;
  receiptHash: string;
  mediaHash: string;
}

function writeJson(filePath: string, value: unknown): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(value)}\n`);
}

function graphFixture(name: string, missingSceneEdge = false): GraphFixture {
  const root = fs.realpathSync(
    fs.mkdtempSync(path.join(os.tmpdir(), `sniper-graph-${name}-`)));
  const producer = path.join(root, "producer");
  const candidate = path.join(producer, ".sniper-qc", name, "final.mp4");
  fs.mkdirSync(path.dirname(candidate), { recursive: true });
  fs.writeFileSync(candidate, `candidate-${name}`);
  const mediaHash = fileSha256(candidate)!;
  const simpleNodes = [{
    nodeId: "node-final",
    kind: "final-export",
    dependencies: [],
    inputDigests: { "final.plan": "b".repeat(64) },
    outputArtifactHash: mediaHash,
    frameRange: null,
  }];
  const semanticNodes = [
    {
      nodeId: "node-source", kind: "source-snapshot", dependencies: [],
      inputDigests: {}, outputArtifactHash: null, frameRange: null,
    },
    {
      nodeId: "node-timeline", kind: "timeline-map",
      dependencies: ["node-source"], inputDigests: {},
      outputArtifactHash: null, frameRange: null,
    },
    {
      nodeId: "node-base", kind: "base-segment",
      dependencies: ["node-source", "node-timeline"], inputDigests: {},
      outputArtifactHash: null, frameRange: null,
    },
    {
      nodeId: "node-scene", kind: "scene-unit",
      dependencies: ["node-timeline"], inputDigests: {},
      outputArtifactHash: null, frameRange: null,
    },
    {
      nodeId: "node-composite", kind: "composite-window",
      dependencies: missingSceneEdge
        ? ["node-base"] : ["node-base", "node-scene"],
      inputDigests: {}, outputArtifactHash: null, frameRange: null,
    },
    {
      nodeId: "node-final", kind: "final-export",
      dependencies: ["node-composite"],
      inputDigests: { "final.plan": "b".repeat(64) },
      outputArtifactHash: mediaHash, frameRange: null,
    },
  ];
  const nodes = missingSceneEdge ? semanticNodes : simpleNodes;
  const graph = {
    schemaVersion: 1,
    graphId: `graph-${name}`,
    toolchainHash: "a".repeat(64),
    rootNodeId: "node-final",
    nodes,
  };
  const graphHash = canonicalJsonSha256(graph);
  const receipt = {
    schemaVersion: 1,
    kind: "current-render-graph-execution",
    graphHash,
    executionMode: "incremental",
    previousGraphHash: null,
    dirtyNodeIds: nodes.map((node) => node.nodeId),
    reusedNodeIds: [],
    artifacts: [{
      nodeId: "node-final",
      path: candidate,
      sha256: mediaHash,
      sizeBytes: fs.statSync(candidate).size,
    }],
  };
  const receiptHash = canonicalJsonSha256(receipt);
  const generation = path.join(
    producer, ".render-graph-v1", "generations", graphHash);
  const graphPath = path.join(generation, "graph.json");
  writeJson(graphPath, graph);
  writeJson(
    path.join(generation, "receipts", `${receiptHash}.json`),
    receipt,
  );
  const key = canonicalJsonSha256({
    kind: "current-render-candidate-path",
    path: candidate,
  });
  writeJson(
    path.join(producer, ".render-graph-v1", "candidates", `${key}.json`),
    {
      schemaVersion: 1,
      kind: "current-render-graph-candidate",
      candidatePath: candidate,
      candidateSha256: mediaHash,
      graphHash,
      receiptHash,
      previousGraphHash: null,
      previousReceiptHash: null,
    },
  );
  return {
    root,
    producer,
    candidate,
    graphPath,
    graphHash,
    receiptHash,
    mediaHash,
  };
}

function observeStaged(item: GraphFixture): void {
  const observed = observeStagedRenderGraphAuthoritySync({
    producerDir: item.producer,
    candidatePath: item.candidate,
    expectedCandidateHash: item.mediaHash,
  });
  assert.equal(observed.graphHash, item.graphHash);
  assert.equal(observed.receiptHash, item.receiptHash);
  assert.equal(observed.candidateMediaHash, item.mediaHash);
}

function promote(item: GraphFixture): void {
  const finalPath = path.join(item.producer, "final.mp4");
  fs.renameSync(item.candidate, finalPath);
  const graphRoot = path.join(
    item.producer, ".render-graph-v1", "generations", item.graphHash);
  const staged = JSON.parse(fs.readFileSync(
    path.join(graphRoot, "receipts", `${item.receiptHash}.json`),
    "utf8",
  )) as Record<string, unknown>;
  const artifacts = staged.artifacts as Array<Record<string, unknown>>;
  artifacts[0] = { ...artifacts[0], path: finalPath };
  const receiptHash = canonicalJsonSha256(staged);
  writeJson(
    path.join(graphRoot, "receipts", `${receiptHash}.json`),
    staged,
  );
  writeJson(path.join(item.producer, ".render-graph-v1", "ACTIVE.json"), {
    schemaVersion: 1,
    graphHash: item.graphHash,
    receiptHash,
  });
  const observed = observeCurrentRenderGraphAuthoritySync({
    producerDir: item.producer,
    expectedGraphHash: item.graphHash,
    expectedFinalHash: item.mediaHash,
  });
  assert.equal(observed.receiptHash, receiptHash);
}

function stagedAndPromotedPass(): void {
  const item = graphFixture("pass");
  try {
    observeStaged(item);
    promote(item);
  } finally {
    fs.rmSync(item.root, { recursive: true, force: true });
  }
}

function missingAndTamperedGenerationFail(): void {
  const missing = graphFixture("missing");
  try {
    fs.rmSync(missing.graphPath);
    assert.throws(() => observeStaged(missing), /ENOENT/);
  } finally {
    fs.rmSync(missing.root, { recursive: true, force: true });
  }
  const tampered = graphFixture("tampered");
  try {
    const graph = JSON.parse(
      fs.readFileSync(tampered.graphPath, "utf8")) as Record<string, unknown>;
    graph.toolchainHash = "c".repeat(64);
    writeJson(tampered.graphPath, graph);
    assert.throws(() => observeStaged(tampered), /changed identity/);
  } finally {
    fs.rmSync(tampered.root, { recursive: true, force: true });
  }
  const changed = graphFixture("changed-candidate");
  try {
    fs.writeFileSync(changed.candidate, "changed-after-staging");
    assert.throws(() => observeStaged(changed), /artifact bytes changed/);
  } finally {
    fs.rmSync(changed.root, { recursive: true, force: true });
  }
  const missingEdge = graphFixture("missing-edge", true);
  try {
    assert.throws(
      () => observeStaged(missingEdge),
      /node-composite is missing required dependencies: node-scene/,
    );
  } finally {
    fs.rmSync(missingEdge.root, { recursive: true, force: true });
  }
}

function foreignActiveAndChangedFinalFail(): void {
  const foreign = graphFixture("foreign");
  try {
    promote(foreign);
    writeJson(path.join(
      foreign.producer, ".render-graph-v1", "ACTIVE.json"), {
      schemaVersion: 1,
      graphHash: "d".repeat(64),
      receiptHash: foreign.receiptHash,
    });
    assert.throws(
      () => observeCurrentRenderGraphAuthoritySync({
        producerDir: foreign.producer,
        expectedGraphHash: foreign.graphHash,
        expectedFinalHash: foreign.mediaHash,
      }),
      /foreign render graph/,
    );
  } finally {
    fs.rmSync(foreign.root, { recursive: true, force: true });
  }
  const changed = graphFixture("changed-final");
  try {
    promote(changed);
    fs.writeFileSync(path.join(changed.producer, "final.mp4"), "changed");
    assert.throws(
      () => observeCurrentRenderGraphAuthoritySync({
        producerDir: changed.producer,
        expectedGraphHash: changed.graphHash,
        expectedFinalHash: changed.mediaHash,
      }),
      /artifact bytes changed/,
    );
  } finally {
    fs.rmSync(changed.root, { recursive: true, force: true });
  }
}

stagedAndPromotedPass();
missingAndTamperedGenerationFail();
foreignActiveAndChangedFinalFail();
console.log("current render graph authority tests passed");
