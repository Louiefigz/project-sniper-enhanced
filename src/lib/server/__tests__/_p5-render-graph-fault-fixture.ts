import fs from "node:fs";
import path from "node:path";
import { planObjectContentHash } from "../auto-edit-authority";
import {
  canonicalJson,
  canonicalJsonSha256,
  fileSha256,
} from "../auto-edit-hash";
import { candidatePromotionTransactionId } from
  "../auto-edit-candidate-promotion";
import type { ApprovalRecord } from "../auto-edit-quality-artifacts";
import type { PromotionCrashBoundary } from
  "../candidate-promotion-transaction";
import { initializeAutoEditProducerAuthoritySync } from
  "../producer-auto-edit-genesis";
import { autoEditGenesisFixture } from
  "./_producer-auto-edit-genesis-fixture";
import {
  currentRenderToolchainHash,
} from "./_p2-cut-repair-rendered-promotion-fixture";
import { EMPTY_SOURCE_SET_DIGEST } from
  "./_producer-auto-edit-render-graph-fixture";
import { writeApprovalFixture } from
  "../../producer/__tests__/auto-edit-approval-fixture";

export type P5FaultKind =
  "cancellation" | "disk-sync" | "stale-parent" | "bad-cache";
export type P5FaultBoundary = PromotionCrashBoundary;

interface StoredGeneration {
  graphHash: string;
  receiptHash: string;
  mediaHash: string;
}

export interface P5FaultFixture {
  root: string;
  producer: string;
  planPath: string;
  manifestPath: string;
  candidate: string;
  candidateHash: string;
  childGraphHash: string;
  childCachePath: string;
  parent: StoredGeneration;
  foreign: StoredGeneration;
  record: ApprovalRecord;
  reconciliationPath: string;
  terminalPath: string;
}

function writeJson(filePath: string, value: unknown): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${canonicalJson(value)}\n`);
}

function candidatePointerPath(producer: string, candidate: string): string {
  const key = canonicalJsonSha256({
    kind: "current-render-candidate-path", path: candidate,
  });
  return path.join(
    producer, ".render-graph-v1", "candidates", `${key}.json`);
}

function generationRoot(producer: string, graphHash: string): string {
  return path.join(
    producer, ".render-graph-v1", "generations", graphHash);
}

function readChild(item: ReturnType<typeof autoEditGenesisFixture>) {
  const pointerPath = candidatePointerPath(
    item.producer, item.candidatePath);
  const pointer = JSON.parse(
    fs.readFileSync(pointerPath, "utf8")) as Record<string, unknown>;
  const graphHash = String(pointer.graphHash);
  const receiptHash = String(pointer.receiptHash);
  const root = generationRoot(item.producer, graphHash);
  return {
    pointerPath,
    pointer,
    graph: JSON.parse(fs.readFileSync(
      path.join(root, "graph.json"), "utf8")) as Record<string, unknown>,
    receipt: JSON.parse(fs.readFileSync(path.join(
      root, "receipts", `${receiptHash}.json`), "utf8",
    )) as Record<string, unknown>,
  };
}

function replaceArtifact(
  receipt: Record<string, unknown>,
  nodeId: string,
  artifactPath: string,
): void {
  const rows = receipt.artifacts as Array<Record<string, unknown>>;
  receipt.artifacts = rows.map((row) => row.nodeId === nodeId ? {
    ...row,
    path: artifactPath,
    sha256: fileSha256(artifactPath),
    sizeBytes: fs.statSync(artifactPath).size,
  } : row);
}

function replaceNodeHash(
  graph: Record<string, unknown>,
  nodeId: string,
  artifactPath: string,
): void {
  const nodes = graph.nodes as Array<Record<string, unknown>>;
  graph.nodes = nodes.map((row) => row.nodeId === nodeId ? {
    ...row, outputArtifactHash: fileSha256(artifactPath),
  } : row);
}

function storeSibling(
  producer: string,
  child: ReturnType<typeof readChild>,
  name: string,
  mediaText: string,
): StoredGeneration {
  const mediaPath = path.join(producer, "final.mp4");
  const stagedMedia = path.join(producer, `.fixture-${name}.mp4`);
  const timeline = path.join(producer, `.fixture-${name}-timeline.json`);
  fs.writeFileSync(stagedMedia, mediaText);
  fs.writeFileSync(timeline, `${name}-timeline`);
  const graph = structuredClone(child.graph);
  graph.graphId = `p5-fault-${name}`;
  replaceNodeHash(graph, "node-timeline", timeline);
  replaceNodeHash(graph, "node-final", stagedMedia);
  const mediaHash = fileSha256(stagedMedia)!;
  const graphHash = canonicalJsonSha256(graph);
  const receipt = structuredClone(child.receipt);
  receipt.graphHash = graphHash;
  receipt.previousGraphHash = null;
  replaceArtifact(receipt, "node-timeline", timeline);
  const artifacts = receipt.artifacts as Array<Record<string, unknown>>;
  receipt.artifacts = artifacts.map((row) =>
    row.nodeId === "node-final" ? {
      ...row,
      path: mediaPath,
      sha256: mediaHash,
      sizeBytes: fs.statSync(stagedMedia).size,
    } : row);
  const receiptHash = canonicalJsonSha256(receipt);
  const root = generationRoot(producer, graphHash);
  writeJson(path.join(root, "graph.json"), graph);
  writeJson(
    path.join(root, "receipts", `${receiptHash}.json`), receipt);
  return { graphHash, receiptHash, mediaHash };
}

function bindParent(
  item: ReturnType<typeof autoEditGenesisFixture>,
  child: ReturnType<typeof readChild>,
  parent: StoredGeneration,
): string {
  const receipt = structuredClone(child.receipt);
  receipt.previousGraphHash = parent.graphHash;
  const receiptHash = canonicalJsonSha256(receipt);
  const root = generationRoot(item.producer, String(child.pointer.graphHash));
  writeJson(
    path.join(root, "receipts", `${receiptHash}.json`), receipt);
  writeJson(child.pointerPath, {
    ...child.pointer,
    receiptHash,
    previousGraphHash: parent.graphHash,
    previousReceiptHash: parent.receiptHash,
  });
  return String(child.pointer.graphHash);
}

function selectGeneration(
  fixture: Pick<P5FaultFixture, "producer">,
  generation: StoredGeneration,
  mediaText: string,
): void {
  fs.writeFileSync(path.join(fixture.producer, "final.mp4"), mediaText);
  writeJson(path.join(
    fixture.producer, ".render-graph-v1", "ACTIVE.json"), {
    schemaVersion: 1,
    graphHash: generation.graphHash,
    receiptHash: generation.receiptHash,
  });
}

function createApproval(
  item: ReturnType<typeof autoEditGenesisFixture>,
  token: string,
): ApprovalRecord {
  return writeApprovalFixture({
    ctx: {
      dir: item.producer,
      scope: "light",
      planPath: item.planPath,
      manifestPath: item.manifestPath,
      transcriptsDir: path.dirname(item.manifestPath),
      intent: { mode: "short", lanes: {} },
    },
    token,
    candidate: item.candidatePath,
  });
}

export function p5FaultFixture(name: string): P5FaultFixture {
  const item = autoEditGenesisFixture(name, {
    sourceSetHash: EMPTY_SOURCE_SET_DIGEST,
    toolchainHash: currentRenderToolchainHash(),
  });
  const child = readChild(item);
  const parent = storeSibling(item.producer, child, "parent", "parent-media");
  const foreign = storeSibling(
    item.producer, child, "foreign", "foreign-media");
  const childGraphHash = bindParent(item, child, parent);
  selectGeneration({ producer: item.producer }, parent, "parent-media");
  fs.writeFileSync(
    `${item.candidatePath}.assembled.json`,
    JSON.stringify({
      planHash: planObjectContentHash(item.plan),
      authorityHash: fileSha256(item.candidatePath),
    }),
  );
  initializeAutoEditProducerAuthoritySync(item.input);
  const record = createApproval(item, name);
  const transactionId = candidatePromotionTransactionId(
    item.candidatePath, item.producer, record);
  const childTimeline = (child.receipt.artifacts as
    Array<Record<string, unknown>>).find(
    (row) => row.nodeId === "node-timeline")!;
  return {
    root: item.root,
    producer: item.producer,
    planPath: item.planPath,
    manifestPath: item.manifestPath,
    candidate: item.candidatePath,
    candidateHash: fileSha256(item.candidatePath)!,
    childGraphHash,
    childCachePath: String(childTimeline.path),
    parent,
    foreign,
    record,
    reconciliationPath: path.join(
      item.producer, ".sniper-qc-promotion-reconciliation.json"),
    terminalPath: path.join(
      item.producer, ".sniper-qc", "promotion-commits",
      `committed-${transactionId}.json`),
  };
}

export function selectForeign(fixture: P5FaultFixture): void {
  selectGeneration(fixture, fixture.foreign, "foreign-media");
}

export function corruptChildCache(fixture: P5FaultFixture): void {
  fs.writeFileSync(fixture.childCachePath, "corrupt-child-cache");
}
