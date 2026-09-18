import path from "node:path";
import type { CutRepairPicturePlanAuthorityV1 } from
  "@/lib/producer/contracts/cut-repair-picture-plan-authority";
import {
  exactKeys,
  objectValue,
  sha256,
} from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import { readAuthorityJsonSync } from
  "@/lib/server/producer-authority-files";
import type { PreparedMediaResult } from "./cut-repair-preparation-plan";

const TERMINAL_KEYS = [
  "schemaVersion", "kind", "operationHash", "reviewPlanObjectHash",
  "reviewPlanContentHash", "reviewTimelineMapHash",
  "picturePlanAuthorityHash", "parentPlanObjectHash",
  "parentRenderAuthority", "parentRenderAuthorityHash",
  "mappingProofHash", "reversionHash", "selectionPolicyHash", "fragmentReceiptHash",
  "compositeReceiptHash", "sourceSelection", "dependencyPartition",
  "dependencyPartitionHash", "dirtyFrameRange", "outsideDirtyOracle",
  "candidate", "deliveryDisposition", "contractHash",
] as const;
const DISPOSITION = {
  candidateConstruction: "proved-composite-exact-byte-copy",
  planReconstruction: "surgical-terminal-not-plan-only-reconstructable",
  palmier: "reference-media-only-no-native-editability",
};

export interface PrivatePictureTerminalInput {
  artifactDir: string;
  candidatePath: string;
  planObjectHash: string;
  planContentHash: string;
  prepared: PreparedMediaResult;
  pictureAuthority: CutRepairPicturePlanAuthorityV1;
}

export interface PrivatePictureTerminalEvent {
  terminalReceiptHash: string;
  terminalReceiptPath: string;
  candidateSha256: string;
  previousGraphHash: string;
  previousReceiptHash: string;
  parentMediaSha256: string;
}

function same(value: unknown, expected: unknown): boolean {
  return canonicalJsonSha256(value) === canonicalJsonSha256(expected);
}

function assertIdentity(
  row: Record<string, unknown>,
  input: PrivatePictureTerminalInput,
  event: PrivatePictureTerminalEvent,
): void {
  const prepared = input.prepared;
  const picture = input.pictureAuthority;
  const expected = [
    [row.operationHash, prepared.operationHash],
    [row.reviewPlanObjectHash, input.planObjectHash],
    [row.reviewPlanContentHash, input.planContentHash],
    [row.reviewTimelineMapHash, prepared.reviewTimelineMapHash],
    [row.picturePlanAuthorityHash, picture.authorityHash],
    [row.parentPlanObjectHash, picture.parentPlanObjectHash],
    [row.mappingProofHash, picture.mappingProofHash],
    [row.reversionHash, canonicalJsonSha256(picture.reversion)],
    [row.selectionPolicyHash, prepared.selectionPolicyHash],
    [row.fragmentReceiptHash,
      canonicalJsonSha256(prepared.fragmentReceipt)],
    [row.compositeReceiptHash,
      canonicalJsonSha256(prepared.compositeReceipt)],
  ];
  if (row.schemaVersion !== 1
      || row.kind !== "cut-repair-surgical-terminal"
      || expected.some(([actual, wanted]) => actual !== wanted)
      || !same(row.dirtyFrameRange, picture.dirtyFrameRange)
      || canonicalJsonSha256(row) !== event.terminalReceiptHash) {
    throw new Error("surgical terminal receipt identity is stale");
  }
  sha256(row.contractHash, "surgical terminal contract");
}

function assertPartition(
  row: Record<string, unknown>,
  input: PrivatePictureTerminalInput,
): void {
  const partition = objectValue(
    row.dependencyPartition, "surgical dependency partition");
  const keys = ["revalidatedDependentIds", "unchangedDependentIds"] as const;
  exactKeys(partition, keys, keys, "surgical dependency partition");
  const expected = {
    revalidatedDependentIds: input.prepared.operation.revalidatedDependentIds,
    unchangedDependentIds: input.prepared.operation.unchangedDependentIds,
  };
  if (!same(partition, expected)
      || row.dependencyPartitionHash !== canonicalJsonSha256(expected)) {
    throw new Error("surgical dependency partition is stale");
  }
}

function assertCandidate(
  row: Record<string, unknown>,
  input: PrivatePictureTerminalInput,
  event: PrivatePictureTerminalEvent,
): void {
  const candidate = objectValue(row.candidate, "surgical candidate receipt");
  const keys = [
    "path", "sha256", "sourceCompositePath", "sourceCompositeSha256",
  ] as const;
  exactKeys(candidate, keys, keys, "surgical candidate receipt");
  const output = objectValue(
    input.prepared.compositeReceipt.output, "prepared composite output");
  if (candidate.path !== input.candidatePath
      || candidate.sha256 !== event.candidateSha256
      || candidate.sourceCompositePath !== output.path
      || candidate.sourceCompositeSha256 !== output.sha256
      || event.candidateSha256 !== output.sha256) {
    throw new Error("surgical candidate receipt is stale");
  }
}

function assertSourceSelection(
  row: Record<string, unknown>,
  input: PrivatePictureTerminalInput,
): void {
  const selection = objectValue(
    row.sourceSelection, "surgical source selection");
  const keys = [
    "sourceId", "sourceMediaSha256", "sourceExtension", "sourceFrameRange",
  ] as const;
  exactKeys(selection, keys, keys, "surgical source selection");
  const inputs = objectValue(
    input.prepared.fragmentReceipt.inputs, "prepared fragment inputs");
  const source = objectValue(inputs.source, "prepared fragment source");
  const operation = input.prepared.operation;
  if (selection.sourceId !== operation.target.sourceId
      || selection.sourceMediaSha256 !== source.sha256
      || !same(selection.sourceExtension, operation.sourceExtension)
      || !same(selection.sourceFrameRange, operation.sourceVideoFrameRange)) {
    throw new Error("surgical source selection is stale");
  }
}

function parentRenderAuthorityHash(
  row: Record<string, unknown>,
  input: PrivatePictureTerminalInput,
  event: PrivatePictureTerminalEvent,
): string {
  const parent = objectValue(
    row.parentRenderAuthority, "surgical parent render authority");
  const keys = [
    "graphHash", "receiptHash", "rootNodeId", "rootArtifactPath",
    "rootMediaSha256", "rootPlanContentHash",
  ] as const;
  exactKeys(parent, keys, keys, "surgical parent render authority");
  const inputs = objectValue(
    input.prepared.compositeReceipt.inputs, "prepared composite inputs");
  const authorityHash = sha256(
    row.parentRenderAuthorityHash, "surgical parent render authority");
  if (canonicalJsonSha256(parent) !== authorityHash
      || parent.graphHash !== event.previousGraphHash
      || parent.receiptHash !== event.previousReceiptHash
      || parent.rootMediaSha256 !== event.parentMediaSha256
      || parent.rootMediaSha256 !== inputs.parentSha256
      || typeof parent.rootNodeId !== "string" || !parent.rootNodeId
      || typeof parent.rootArtifactPath !== "string"
      || !path.isAbsolute(parent.rootArtifactPath)) {
    throw new Error("surgical parent render authority is stale");
  }
  sha256(parent.rootPlanContentHash, "surgical parent plan content");
  return authorityHash;
}

/** Reopen the separate terminal receipt before trusting its graph digest. */
export function verifyPrivatePictureTerminal(
  input: PrivatePictureTerminalInput,
  event: PrivatePictureTerminalEvent,
): string {
  const expectedPath = path.join(
    input.artifactDir, "cut_repair_surgical_terminal_receipt.json");
  if (event.terminalReceiptPath !== expectedPath) {
    throw new Error("surgical terminal receipt escaped private artifacts");
  }
  const row = objectValue(
    readAuthorityJsonSync(expectedPath), "surgical terminal receipt");
  exactKeys(row, TERMINAL_KEYS, TERMINAL_KEYS, "surgical terminal receipt");
  assertIdentity(row, input, event);
  assertPartition(row, input);
  assertCandidate(row, input, event);
  assertSourceSelection(row, input);
  const parentHash = parentRenderAuthorityHash(row, input, event);
  const outside = input.prepared.compositeReceipt.outsideDirtyOracle;
  if (!same(row.outsideDirtyOracle, outside)
      || !same(row.deliveryDisposition, DISPOSITION)) {
    throw new Error("surgical terminal lane disposition is stale");
  }
  return parentHash;
}
