import {
  lstatSync,
  realpathSync,
  statSync,
} from "node:fs";
import path from "node:path";
import {
  parseRenderGraphV1,
  type RenderGraphV1,
} from "@/lib/producer/contracts/render-graph";
import {
  exactKeys,
  objectValue,
  sha256,
} from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256, fileSha256 } from "./auto-edit-hash";
import { assertCurrentRenderGraphSemanticsV1 } from
  "./current-render-graph-semantics";
import { readAuthorityJsonSync } from "./producer-authority-files";

const RECEIPT_KEYS = [
  "schemaVersion", "kind", "graphHash", "executionMode",
  "previousGraphHash", "dirtyNodeIds", "reusedNodeIds", "artifacts",
] as const;
const ARTIFACT_KEYS = [
  "nodeId", "path", "sha256", "sizeBytes",
] as const;

interface ParsedArtifact {
  nodeId: string;
  path: string;
  sha256: string;
  sizeBytes: number;
}

export interface RenderGraphGenerationExpectation {
  producerDir: string;
  graphHash: string;
  receiptHash: string;
  expectedMediaPath: string;
  expectedMediaHash: string;
}

export interface RenderGraphGenerationAuthority {
  graphHash: string;
  receiptHash: string;
  mediaHash: string;
}

export function canonicalProducerDirectorySync(producerDir: string): string {
  const resolved = path.resolve(producerDir);
  const stat = lstatSync(resolved);
  if (!stat.isDirectory() || stat.isSymbolicLink()
      || realpathSync(resolved) !== resolved) {
    throw new Error("producer path is not a canonical directory");
  }
  return resolved;
}

export function assertAuthorityFileSync(
  filePath: string,
  root: string,
  label: string,
): void {
  const resolved = path.resolve(filePath);
  const relative = path.relative(root, resolved);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error(`${label} escaped render-graph authority`);
  }
  let cursor = root;
  for (const part of relative.split(path.sep)) {
    cursor = path.join(cursor, part);
    if (lstatSync(cursor).isSymbolicLink()) {
      throw new Error(`${label} contains a symlink`);
    }
  }
  const stat = lstatSync(resolved);
  if (!stat.isFile() || realpathSync(resolved) !== resolved) {
    throw new Error(`${label} is not a canonical regular file`);
  }
}

function stringIds(value: unknown, label: string): string[] {
  if (!Array.isArray(value)
      || value.some((item) => typeof item !== "string")
      || new Set(value).size !== value.length) {
    throw new Error(`${label} is not a unique string list`);
  }
  return value as string[];
}

function artifact(value: unknown): ParsedArtifact {
  const row = objectValue(value, "render graph artifact");
  exactKeys(row, ARTIFACT_KEYS, ARTIFACT_KEYS, "render graph artifact");
  if (typeof row.nodeId !== "string"
      || typeof row.path !== "string"
      || !path.isAbsolute(row.path)
      || !Number.isSafeInteger(row.sizeBytes)
      || Number(row.sizeBytes) < 0) {
    throw new Error("render graph artifact identity is malformed");
  }
  return {
    nodeId: row.nodeId,
    path: row.path,
    sha256: sha256(row.sha256, "render graph artifact hash"),
    sizeBytes: Number(row.sizeBytes),
  };
}

function receiptArtifacts(
  value: unknown,
  graph: RenderGraphV1,
  graphHash: string,
): ParsedArtifact[] {
  const receipt = objectValue(value, "render graph receipt");
  exactKeys(receipt, RECEIPT_KEYS, RECEIPT_KEYS, "render graph receipt");
  if (receipt.schemaVersion !== 1
      || receipt.kind !== "current-render-graph-execution"
      || receipt.graphHash !== graphHash
      || !["incremental", "forced-full"].includes(
        String(receipt.executionMode))) {
    throw new Error("render graph receipt binding is malformed");
  }
  if (receipt.previousGraphHash !== null) {
    sha256(receipt.previousGraphHash, "previous render graph hash");
  }
  const dirty = stringIds(receipt.dirtyNodeIds, "dirty render nodes");
  const reused = stringIds(receipt.reusedNodeIds, "reused render nodes");
  const nodeIds = new Set(graph.nodes.map((node) => node.nodeId));
  if (dirty.some((id) => !nodeIds.has(id))
      || reused.some((id) => !nodeIds.has(id))
      || dirty.some((id) => reused.includes(id))
      || new Set([...dirty, ...reused]).size !== nodeIds.size) {
    throw new Error("render graph node classification is stale");
  }
  if (!Array.isArray(receipt.artifacts)) {
    throw new Error("render graph artifacts are malformed");
  }
  const artifacts = receipt.artifacts.map(artifact);
  const outputs = new Map(graph.nodes
    .filter((node) => node.outputArtifactHash !== null)
    .map((node) => [node.nodeId, node.outputArtifactHash]));
  if (artifacts.length !== outputs.size
      || new Set(artifacts.map((row) => row.nodeId)).size !== outputs.size
      || artifacts.some((row) => outputs.get(row.nodeId) !== row.sha256)) {
    throw new Error("render graph artifacts do not bind every output");
  }
  return artifacts;
}

function assertArtifactBytes(row: ParsedArtifact): void {
  const before = lstatSync(row.path);
  if (!before.isFile() || before.isSymbolicLink()
      || realpathSync(row.path) !== row.path
      || statSync(row.path).size !== row.sizeBytes
      || fileSha256(row.path) !== row.sha256) {
    throw new Error(`render graph artifact bytes changed: ${row.nodeId}`);
  }
  const after = lstatSync(row.path);
  if (before.dev !== after.dev || before.ino !== after.ino
      || before.size !== after.size || before.mtimeMs !== after.mtimeMs
      || before.ctimeMs !== after.ctimeMs) {
    throw new Error(`render graph artifact changed while read: ${row.nodeId}`);
  }
}

function assertRootMedia(
  input: RenderGraphGenerationExpectation,
  graph: RenderGraphV1,
  artifacts: ParsedArtifact[],
): void {
  if (!path.isAbsolute(input.expectedMediaPath)) {
    throw new Error("render graph expected media path is not absolute");
  }
  const mediaPath = path.resolve(input.expectedMediaPath);
  assertAuthorityFileSync(
    mediaPath,
    canonicalProducerDirectorySync(input.producerDir),
    "render graph root media",
  );
  const root = graph.nodes.find((node) => node.nodeId === graph.rootNodeId);
  const matches = artifacts.filter((row) => row.nodeId === graph.rootNodeId);
  if (root?.outputArtifactHash !== input.expectedMediaHash
      || matches.length !== 1
      || matches[0].path !== mediaPath
      || matches[0].sha256 !== input.expectedMediaHash) {
    throw new Error("render graph root does not bind expected media");
  }
}

/** Reopen and rehash one content-addressed graph generation and every output. */
export function observeRenderGraphGenerationSync(
  input: RenderGraphGenerationExpectation,
): RenderGraphGenerationAuthority {
  const producer = canonicalProducerDirectorySync(input.producerDir);
  const graphHash = sha256(input.graphHash, "render graph hash");
  const receiptHash = sha256(input.receiptHash, "render graph receipt hash");
  const mediaHash = sha256(input.expectedMediaHash, "render graph media hash");
  const root = path.join(producer, ".render-graph-v1");
  const generation = path.join(root, "generations", graphHash);
  const graphPath = path.join(generation, "graph.json");
  const receiptPath = path.join(
    generation, "receipts", `${receiptHash}.json`);
  assertAuthorityFileSync(graphPath, root, "render graph generation");
  assertAuthorityFileSync(receiptPath, root, "render graph receipt");
  const graphValue = readAuthorityJsonSync(graphPath);
  const receiptValue = readAuthorityJsonSync(receiptPath);
  if (canonicalJsonSha256(graphValue) !== graphHash
      || canonicalJsonSha256(receiptValue) !== receiptHash) {
    throw new Error("render graph generation changed identity");
  }
  const graph = parseRenderGraphV1(graphValue);
  assertCurrentRenderGraphSemanticsV1(graph);
  const artifacts = receiptArtifacts(receiptValue, graph, graphHash);
  assertRootMedia({ ...input, expectedMediaHash: mediaHash }, graph, artifacts);
  artifacts.forEach(assertArtifactBytes);
  return { graphHash, receiptHash, mediaHash };
}
