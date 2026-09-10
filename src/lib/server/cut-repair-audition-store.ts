import {
  existsSync,
  lstatSync,
  mkdirSync,
} from "node:fs";
import path from "node:path";
import {
  exactKeys,
  isoDate,
  objectValue,
  sha256,
} from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import {
  assertObjectHashSync,
  authorityKey,
  producerAuthorityPaths,
  publishImmutableAuthorityJsonSync,
  readAuthorityJsonSync,
  writeAuthorityObjectSync,
} from "./producer-authority-files";

export interface OperatorAuditionAttestation {
  preparationHash: string;
  candidateDescriptorHash: string;
  candidateSha256: string;
  operatorReceiptId: string;
  reviewedAt: string;
  decision: "approved" | "rejected";
  reportedDamageResolved: boolean;
}

interface StoreInput {
  producerDir: string;
  operationHash: string;
  expected: {
    preparationHash: string;
    candidateDescriptorHash: string;
    candidateSha256: string;
  };
  attestation: OperatorAuditionAttestation;
}

export interface CutRepairAuditionEvidenceItem {
  status: "operator-approved-candidate";
  receiptHash: string;
  candidateCompositeSha256: string;
  receipt: Record<string, unknown>;
}

export interface StoredCutRepairAudition {
  approvalPolicyHash: string;
  receiptHash: string;
  item: CutRepairAuditionEvidenceItem;
  replayed: boolean;
}

const APPROVAL_POLICY = {
  schemaVersion: 1,
  kind: "cut-repair-operator-audition-policy",
  candidateScope: "exact-full-plan-render",
  decisionRequirement: "explicit-approved",
  damageResolutionRequirement: "operator-confirmed",
} as const;

const RECEIPT_KEYS = [
  "schemaVersion", "kind", "status", "operationHash",
  "candidateCompositeSha256", "operatorReceiptId", "approvalPolicyHash",
  "reviewedAt", "decision", "reportedDamageResolved",
] as const;
const POINTER_KEYS = [
  "schemaVersion", "kind", "operatorReceiptId", "preparationHash",
  "candidateDescriptorHash", "candidateSha256", "receiptHash",
] as const;

function ensureDirectory(directory: string): void {
  try {
    mkdirSync(directory, { mode: 0o700 });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
  }
  const stat = lstatSync(directory);
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error("cut repair audition path must be a real directory");
  }
}

function pointerPath(producerDir: string, receiptId: string): string {
  const paths = producerAuthorityPaths(producerDir);
  const root = path.join(paths.sagas, "cut-repair-audition");
  const records = path.join(root, "records");
  [root, records].forEach(ensureDirectory);
  return path.join(records, `${authorityKey(receiptId)}.json`);
}

function assertAttestation(input: StoreInput): void {
  const { expected, attestation } = input;
  if (attestation.preparationHash !== expected.preparationHash
      || attestation.candidateDescriptorHash
        !== expected.candidateDescriptorHash
      || attestation.candidateSha256 !== expected.candidateSha256) {
    throw new Error("operator audition targets another full-plan candidate");
  }
  if (attestation.decision !== "approved"
      || attestation.reportedDamageResolved !== true) {
    throw new Error("operator rejected the cut repair candidate");
  }
  isoDate(attestation.reviewedAt, "operator audition reviewedAt");
  if (!attestation.operatorReceiptId) {
    throw new Error("operator audition receipt identity is absent");
  }
}

function receipt(input: StoreInput, policyHash: string) {
  return {
    schemaVersion: 1,
    kind: "cut-repair-audition-qc",
    status: "operator-approved-candidate",
    operationHash: sha256(input.operationHash, "audition operation"),
    candidateCompositeSha256: sha256(
      input.expected.candidateSha256, "audition full-plan candidate"),
    operatorReceiptId: input.attestation.operatorReceiptId,
    approvalPolicyHash: policyHash,
    reviewedAt: input.attestation.reviewedAt,
    decision: "approved",
    reportedDamageResolved: true,
  } as const;
}

function parseReceipt(value: unknown): Record<string, unknown> {
  const row = objectValue(value, "cut repair audition receipt");
  exactKeys(row, RECEIPT_KEYS, RECEIPT_KEYS, "cut repair audition receipt");
  if (row.schemaVersion !== 1 || row.kind !== "cut-repair-audition-qc"
      || row.status !== "operator-approved-candidate"
      || row.decision !== "approved"
      || row.reportedDamageResolved !== true
      || typeof row.operatorReceiptId !== "string"
      || !row.operatorReceiptId) {
    throw new Error("cut repair audition receipt is malformed");
  }
  sha256(row.operationHash, "audition receipt operation");
  sha256(row.candidateCompositeSha256, "audition receipt candidate");
  sha256(row.approvalPolicyHash, "audition receipt policy");
  isoDate(row.reviewedAt, "audition receipt reviewedAt");
  return row;
}

function proposedPointer(input: StoreInput, receiptHash: string) {
  return {
    schemaVersion: 1,
    kind: "cut-repair-audition-pointer",
    operatorReceiptId: input.attestation.operatorReceiptId,
    preparationHash: input.expected.preparationHash,
    candidateDescriptorHash: input.expected.candidateDescriptorHash,
    candidateSha256: input.expected.candidateSha256,
    receiptHash,
  } as const;
}

function parsePointer(value: unknown): ReturnType<typeof proposedPointer> {
  const row = objectValue(value, "cut repair audition pointer");
  exactKeys(row, POINTER_KEYS, POINTER_KEYS, "cut repair audition pointer");
  if (row.schemaVersion !== 1 || row.kind !== "cut-repair-audition-pointer"
      || typeof row.operatorReceiptId !== "string"
      || !row.operatorReceiptId) {
    throw new Error("cut repair audition pointer is malformed");
  }
  return {
    schemaVersion: 1,
    kind: "cut-repair-audition-pointer",
    operatorReceiptId: row.operatorReceiptId,
    preparationHash: sha256(row.preparationHash, "audition preparation"),
    candidateDescriptorHash: sha256(
      row.candidateDescriptorHash, "audition descriptor"),
    candidateSha256: sha256(row.candidateSha256, "audition candidate"),
    receiptHash: sha256(row.receiptHash, "audition receipt"),
  };
}

/** Mint and persist the receipt hash; callers only supply an attestation. */
export function storeCutRepairAuditionReceiptSync(
  input: StoreInput,
): StoredCutRepairAudition {
  assertAttestation(input);
  const paths = producerAuthorityPaths(input.producerDir);
  const policy = writeAuthorityObjectSync(
    paths.objects.cutRepairs, APPROVAL_POLICY);
  const value = receipt(input, policy.hash);
  const stored = writeAuthorityObjectSync(paths.objects.receipts, value);
  const proposed = proposedPointer(input, stored.hash);
  const filePath = pointerPath(
    input.producerDir, input.attestation.operatorReceiptId);
  const replayed = existsSync(filePath);
  publishImmutableAuthorityJsonSync(filePath, proposed);
  const observed = parsePointer(readAuthorityJsonSync(filePath));
  if (canonicalJsonSha256(observed) !== canonicalJsonSha256(proposed)) {
    throw new Error("operator receipt identity is bound to another audition");
  }
  const reopened = parseReceipt(assertObjectHashSync(
    paths.objects.receipts, observed.receiptHash));
  if (canonicalJsonSha256(reopened) !== observed.receiptHash) {
    throw new Error("stored operator audition receipt changed identity");
  }
  return {
    approvalPolicyHash: policy.hash,
    receiptHash: stored.hash,
    replayed,
    item: {
      status: "operator-approved-candidate",
      receiptHash: stored.hash,
      candidateCompositeSha256: input.expected.candidateSha256,
      receipt: reopened,
    },
  };
}
