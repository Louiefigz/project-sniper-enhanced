import {
  existsSync,
  lstatSync,
  mkdirSync,
} from "node:fs";
import path from "node:path";
import {
  parseCutRepairPromotionActionV1,
  type CutRepairPromotionActionV1,
} from "@/lib/producer/contracts/cut-repair-promotion-transition";
import {
  parseCutRepairReviewActionV1,
  type CutRepairReviewActionV1,
} from "@/lib/producer/contracts/cut-repair-review-transition";
import {
  exactKeys,
  objectValue,
  sha256,
  uuid,
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
import { validateCutRepairPromotionEvidence } from
  "./producer-cut-repair-promotion-evidence";

export interface CutRepairExecutionPackageV1 {
  schemaVersion: 1;
  kind: "cut-repair-execution-package";
  targetDirectiveHash: string;
  contextAuthorityHash: string;
  parentRevisionHash: string;
  reviewAction: CutRepairReviewActionV1;
  promotionAction: CutRepairPromotionActionV1;
  candidate: Record<string, unknown>;
  promotionEvidence: Record<string, unknown>;
}

interface ExecutionPackagePointerV1 {
  schemaVersion: 1;
  kind: "cut-repair-execution-package-pointer";
  idempotencyKey: string;
  preparationHash: string;
  promotionActionHash: string;
  packageHash: string;
}

interface StoreInput {
  producerDir: string;
  preparationHash: string;
  value: unknown;
}

export interface StoredCutRepairExecutionPackage {
  packageHash: string;
  promotionActionHash: string;
  package: CutRepairExecutionPackageV1;
  replayed: boolean;
}

const PACKAGE_KEYS = [
  "schemaVersion", "kind", "targetDirectiveHash", "contextAuthorityHash",
  "parentRevisionHash", "reviewAction", "promotionAction", "candidate",
  "promotionEvidence",
] as const;
const POINTER_KEYS = [
  "schemaVersion", "kind", "idempotencyKey", "preparationHash",
  "promotionActionHash", "packageHash",
] as const;

function ensureDirectory(directory: string): void {
  try {
    mkdirSync(directory, { mode: 0o700 });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
  }
  const stat = lstatSync(directory);
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error("cut repair execution package path must be a real directory");
  }
}

function pointerPath(producerDir: string, idempotencyKey: string): string {
  const paths = producerAuthorityPaths(producerDir);
  const root = path.join(paths.sagas, "cut-repair-approval");
  const records = path.join(root, "records");
  [root, records].forEach(ensureDirectory);
  return path.join(records, `${authorityKey(idempotencyKey)}.json`);
}

function terminalHash(candidate: Record<string, unknown>): string {
  const terminal = candidate.schemaVersion === 2
    ? objectValue(candidate.renderedCandidate, "rendered candidate")
    : objectValue(
      objectValue(candidate.compositeReceipt, "composite receipt").output,
      "composite output",
    );
  return sha256(
    candidate.schemaVersion === 2
      ? terminal.candidateSha256 : terminal.sha256,
    "execution package terminal media",
  );
}

/** Parse a closed package and recompute every embedded phase hash. */
export function parseCutRepairExecutionPackageV1(
  value: unknown,
): CutRepairExecutionPackageV1 {
  const row = objectValue(value, "cut repair execution package");
  const extras = Object.keys(row).filter((key) => !PACKAGE_KEYS.includes(
    key as typeof PACKAGE_KEYS[number]));
  const missing = PACKAGE_KEYS.filter((key) => !(key in row));
  if (extras.length || missing.length) {
    throw new Error("cut repair execution package is not closed");
  }
  exactKeys(row, PACKAGE_KEYS, PACKAGE_KEYS, "cut repair execution package");
  if (row.schemaVersion !== 1
      || row.kind !== "cut-repair-execution-package") {
    throw new Error("cut repair execution package is not closed");
  }
  const reviewAction = parseCutRepairReviewActionV1(row.reviewAction);
  const promotionAction = parseCutRepairPromotionActionV1(row.promotionAction);
  const candidate = objectValue(row.candidate, "package candidate");
  const promotionEvidence = objectValue(
    row.promotionEvidence, "package promotion evidence");
  const parentRevisionHash = sha256(
    row.parentRevisionHash, "package parent revision");
  if (reviewAction.expectedParentRevisionHash !== parentRevisionHash
      || promotionAction.reviewActionHash
        !== canonicalJsonSha256(reviewAction)
      || promotionAction.operationHash !== reviewAction.operationHash
      || promotionAction.selectionPolicyHash
        !== reviewAction.selectionPolicyHash
      || promotionAction.candidateHash !== canonicalJsonSha256(candidate)
      || promotionAction.promotionEvidenceHash
        !== canonicalJsonSha256(promotionEvidence)) {
    throw new Error("cut repair execution package contains stale phase bindings");
  }
  validateCutRepairPromotionEvidence(
    promotionEvidence, reviewAction.operation, terminalHash(candidate));
  return {
    schemaVersion: 1,
    kind: "cut-repair-execution-package",
    targetDirectiveHash: sha256(
      row.targetDirectiveHash, "package target directive hash"),
    contextAuthorityHash: sha256(
      row.contextAuthorityHash, "package context authority hash"),
    parentRevisionHash,
    reviewAction,
    promotionAction,
    candidate,
    promotionEvidence,
  };
}

function parsePointer(value: unknown): ExecutionPackagePointerV1 {
  const row = objectValue(value, "cut repair execution package pointer");
  exactKeys(row, POINTER_KEYS, POINTER_KEYS, "execution package pointer");
  if (row.schemaVersion !== 1
      || row.kind !== "cut-repair-execution-package-pointer") {
    throw new Error("cut repair execution package pointer is malformed");
  }
  return {
    schemaVersion: 1,
    kind: "cut-repair-execution-package-pointer",
    idempotencyKey: uuid(row.idempotencyKey, "approval idempotency key"),
    preparationHash: sha256(row.preparationHash, "approval preparation"),
    promotionActionHash: sha256(
      row.promotionActionHash, "approval promotion action"),
    packageHash: sha256(row.packageHash, "approval execution package"),
  };
}

/** Load one package directly by its immutable content identity. */
export function loadCutRepairExecutionPackageSync(
  producerDir: string,
  packageHash: string,
): CutRepairExecutionPackageV1 {
  const paths = producerAuthorityPaths(producerDir);
  return parseCutRepairExecutionPackageV1(assertObjectHashSync(
    paths.objects.cutRepairs, packageHash));
}

function verifyPointer(
  producerDir: string,
  pointer: ExecutionPackagePointerV1,
  expected: ExecutionPackagePointerV1,
): CutRepairExecutionPackageV1 {
  if (canonicalJsonSha256(pointer) !== canonicalJsonSha256(expected)) {
    throw new Error("approval idempotency key is bound to another package");
  }
  const paths = producerAuthorityPaths(producerDir);
  const value = loadCutRepairExecutionPackageSync(
    producerDir, pointer.packageHash);
  const storedAction = parseCutRepairPromotionActionV1(assertObjectHashSync(
    paths.objects.cutRepairs, pointer.promotionActionHash));
  if (canonicalJsonSha256(storedAction) !== pointer.promotionActionHash
      || canonicalJsonSha256(value.promotionAction)
        !== pointer.promotionActionHash) {
    throw new Error("execution package lost its separate promotion action");
  }
  return value;
}

/** Store the action and package separately, then seal one replay identity. */
export function storeCutRepairExecutionPackageSync(
  input: StoreInput,
): StoredCutRepairExecutionPackage {
  const value = parseCutRepairExecutionPackageV1(input.value);
  const paths = producerAuthorityPaths(input.producerDir);
  const action = writeAuthorityObjectSync(
    paths.objects.cutRepairs, value.promotionAction);
  const stored = writeAuthorityObjectSync(paths.objects.cutRepairs, value);
  const proposed: ExecutionPackagePointerV1 = {
    schemaVersion: 1,
    kind: "cut-repair-execution-package-pointer",
    idempotencyKey: value.promotionAction.idempotencyKey,
    preparationHash: sha256(input.preparationHash, "approval preparation"),
    promotionActionHash: action.hash,
    packageHash: stored.hash,
  };
  const filePath = pointerPath(
    input.producerDir, value.promotionAction.idempotencyKey);
  const replayed = existsSync(filePath);
  publishImmutableAuthorityJsonSync(filePath, proposed);
  const observed = parsePointer(readAuthorityJsonSync(filePath));
  return {
    packageHash: observed.packageHash,
    promotionActionHash: observed.promotionActionHash,
    package: verifyPointer(input.producerDir, observed, proposed),
    replayed,
  };
}
