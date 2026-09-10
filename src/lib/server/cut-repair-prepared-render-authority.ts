import { statSync } from "node:fs";
import path from "node:path";
import type { CutRepairPreparationPackageV1 } from
  "@/lib/producer/contracts/cut-repair-preparation";
import { parseRenderGraphV1 } from
  "@/lib/producer/contracts/render-graph";
import {
  exactKeys,
  objectValue,
} from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256, fileSha256 } from "./auto-edit-hash";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
  readAuthorityJsonSync,
  writeAuthorityObjectSync,
} from "./producer-authority-files";
import {
  preparedStagingPath,
  restorePreparedMediaSync,
  storePreparedMediaSync,
} from "./cut-repair-preparation-media";

const POINTER_KEYS = [
  "schemaVersion", "kind", "candidatePath", "candidateSha256",
  "graphHash", "receiptHash", "previousGraphHash", "previousReceiptHash",
] as const;
const RECEIPT_KEYS = [
  "schemaVersion", "kind", "graphHash", "executionMode",
  "previousGraphHash", "dirtyNodeIds", "reusedNodeIds", "artifacts",
] as const;

export interface CutRepairPreparedRender {
  candidatePath: string;
  candidateSha256: string;
  graphHash: string;
  graphReceiptHash: string;
  candidatePointerHash: string;
  previousGraphHash: string | null;
  previousGraphReceiptHash: string | null;
}

interface RenderRecords {
  graph: unknown;
  receipt: unknown;
  pointer: unknown;
}

interface RenderBinding {
  graphHash: string;
  receiptHash: string;
  pointerHash: string;
  candidatePath: string;
  candidateHash: string;
  previousGraphHash: string | null;
  previousReceiptHash: string | null;
  planContentHash?: string;
}

function generationRoot(producerDir: string, graphHash: string): string {
  return path.join(
    producerDir, ".render-graph-v1", "generations", graphHash);
}

function candidatePointerPath(
  producerDir: string,
  candidatePath: string,
): string {
  const key = canonicalJsonSha256({
    kind: "current-render-candidate-path",
    path: candidatePath,
  });
  return path.join(
    producerDir, ".render-graph-v1", "candidates", `${key}.json`);
}

function liveRecords(
  producerDir: string,
  render: CutRepairPreparedRender,
): RenderRecords {
  const generation = generationRoot(producerDir, render.graphHash);
  return {
    graph: readAuthorityJsonSync(path.join(generation, "graph.json")),
    receipt: readAuthorityJsonSync(path.join(
      generation, "receipts", `${render.graphReceiptHash}.json`)),
    pointer: readAuthorityJsonSync(candidatePointerPath(
      producerDir, render.candidatePath)),
  };
}

function exactRecord(value: unknown, expected: string, label: string): void {
  if (canonicalJsonSha256(value) !== expected) {
    throw new Error(`cut repair prepared ${label} changed identity`);
  }
}

function assertPointer(value: unknown, binding: RenderBinding): void {
  const pointer = objectValue(value, "cut repair render candidate pointer");
  exactKeys(pointer, POINTER_KEYS, POINTER_KEYS, "render candidate pointer");
  if (pointer.schemaVersion !== 1
      || pointer.kind !== "current-render-graph-candidate"
      || pointer.candidatePath !== binding.candidatePath
      || pointer.candidateSha256 !== binding.candidateHash
      || pointer.graphHash !== binding.graphHash
      || pointer.receiptHash !== binding.receiptHash
      || pointer.previousGraphHash !== binding.previousGraphHash
      || pointer.previousReceiptHash !== binding.previousReceiptHash) {
    throw new Error("cut repair prepared candidate pointer is stale");
  }
}

function assertReceipt(
  value: unknown,
  rootNodeId: string,
  binding: RenderBinding,
): void {
  const receipt = objectValue(value, "cut repair render receipt");
  exactKeys(receipt, RECEIPT_KEYS, RECEIPT_KEYS, "render receipt");
  if (receipt.schemaVersion !== 1
      || receipt.kind !== "current-render-graph-execution"
      || receipt.graphHash !== binding.graphHash
      || receipt.previousGraphHash !== binding.previousGraphHash
      || !Array.isArray(receipt.artifacts)) {
    throw new Error("cut repair prepared render receipt is stale");
  }
  const roots = receipt.artifacts.map((item) =>
    objectValue(item, "cut repair render artifact")).filter(
    (artifact) => artifact.nodeId === rootNodeId);
  const size = statSync(binding.candidatePath).size;
  if (roots.length !== 1
      || roots[0].path !== binding.candidatePath
      || roots[0].sha256 !== binding.candidateHash
      || roots[0].sizeBytes !== size) {
    throw new Error("cut repair render receipt does not bind candidate bytes");
  }
}

function assertBindings(records: RenderRecords, binding: RenderBinding): void {
  exactRecord(records.graph, binding.graphHash, "graph");
  exactRecord(records.receipt, binding.receiptHash, "graph receipt");
  exactRecord(records.pointer, binding.pointerHash, "candidate pointer");
  if (fileSha256(binding.candidatePath) !== binding.candidateHash) {
    throw new Error("cut repair prepared candidate bytes changed");
  }
  const graph = parseRenderGraphV1(records.graph);
  const root = graph.nodes.find((node) => node.nodeId === graph.rootNodeId);
  if (root?.outputArtifactHash !== binding.candidateHash
      || (binding.planContentHash !== undefined
        && root.inputDigests["final.plan"] !== binding.planContentHash)) {
    throw new Error("cut repair prepared graph is not the review-plan render");
  }
  assertPointer(records.pointer, binding);
  assertReceipt(records.receipt, graph.rootNodeId, binding);
}

function captureBinding(
  producerDir: string,
  render: CutRepairPreparedRender,
): RenderBinding {
  return {
    graphHash: render.graphHash,
    receiptHash: render.graphReceiptHash,
    pointerHash: render.candidatePointerHash,
    candidatePath: preparedStagingPath(
      producerDir, render.candidatePath, "cut repair review candidate"),
    candidateHash: render.candidateSha256,
    previousGraphHash: render.previousGraphHash,
    previousReceiptHash: render.previousGraphReceiptHash,
  };
}

/** Preserve the already-strictly-observed staged generation for replay. */
export function captureCutRepairPreparedRenderSync(
  producerDir: string,
  render: CutRepairPreparedRender,
): void {
  const binding = captureBinding(producerDir, render);
  const records = liveRecords(producerDir, render);
  assertBindings(records, binding);
  const paths = producerAuthorityPaths(producerDir);
  const graph = writeAuthorityObjectSync(paths.objects.graphs, records.graph);
  const receipt = writeAuthorityObjectSync(
    paths.objects.receipts, records.receipt);
  const pointer = writeAuthorityObjectSync(
    paths.objects.receipts, records.pointer);
  if (graph.hash !== binding.graphHash
      || receipt.hash !== binding.receiptHash
      || pointer.hash !== binding.pointerHash) {
    throw new Error("cut repair prepared render storage changed identity");
  }
  storePreparedMediaSync({
    producerDir,
    path: binding.candidatePath,
    hash: binding.candidateHash,
    extension: ".mp4",
  });
}

function packageBinding(
  producerDir: string,
  value: CutRepairPreparationPackageV1,
): RenderBinding {
  return {
    graphHash: value.proposedReviewAction.reviewRenderGraphHash,
    receiptHash: value.reviewRenderGraphReceiptHash,
    pointerHash: value.reviewRenderGraphCandidatePointerHash,
    candidatePath: preparedStagingPath(
      producerDir, value.reviewCandidatePath, "cut repair review candidate"),
    candidateHash: value.reviewCandidateMediaSha256,
    previousGraphHash: value.previousRenderGraphHash,
    previousReceiptHash: value.previousRenderGraphReceiptHash,
    planContentHash: value.proposedReviewAction.reviewPlanContentHash,
  };
}

/** Reopen durable records and restore only the private review candidate. */
export function verifyCutRepairPreparedRenderSync(
  producerDir: string,
  value: CutRepairPreparationPackageV1,
): void {
  const binding = packageBinding(producerDir, value);
  restorePreparedMediaSync({
    producerDir,
    path: binding.candidatePath,
    hash: binding.candidateHash,
    extension: ".mp4",
  });
  const paths = producerAuthorityPaths(producerDir);
  const records = {
    graph: assertObjectHashSync(paths.objects.graphs, binding.graphHash),
    receipt: assertObjectHashSync(
      paths.objects.receipts, binding.receiptHash),
    pointer: assertObjectHashSync(
      paths.objects.receipts, binding.pointerHash),
  };
  assertBindings(records, binding);
}
