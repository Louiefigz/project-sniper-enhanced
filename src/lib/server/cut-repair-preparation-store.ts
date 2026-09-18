import {
  existsSync,
  lstatSync,
  mkdirSync,
} from "node:fs";
import path from "node:path";
import {
  parseCutRepairPreparationPackageV1,
  type CutRepairPreparationPackageV1,
} from "@/lib/producer/contracts/cut-repair-preparation";
import {
  assertCutRepairPicturePlanParent,
  bindCutRepairPicturePlanAuthority,
} from
  "@/lib/producer/contracts/cut-repair-picture-plan-authority";
import { parseProjectRevision } from
  "@/lib/producer/contracts/project-revision";
import {
  objectValue,
  sha256,
  uuid,
} from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { planObjectContentHash } from "./auto-edit-authority";
import {
  receiptMediaPath,
  restorePreparedMediaSync,
  storePreparedMediaSync,
} from "./cut-repair-preparation-media";
import { verifyCutRepairPreparedRenderSync } from
  "./cut-repair-prepared-render-authority";
import { verifyCutRepairRenderedCandidateSync } from
  "./cut-repair-rendered-candidate-store";
import { verifyCutRepairPreparationReviewGraphSync } from
  "./cut-repair-surgical-preparation-reopen";
import {
  assertObjectHashSync,
  authorityKey,
  producerAuthorityPaths,
  publishImmutableAuthorityJsonSync,
  readAuthorityJsonSync,
  writeAuthorityObjectSync,
} from "./producer-authority-files";

interface PreparationPointer {
  schemaVersion: 1;
  kind: "cut-repair-preparation-pointer";
  idempotencyKey: string;
  targetDirectiveHash: string;
  packageHash: string;
}

export interface StoredCutRepairPreparation {
  packageHash: string;
  package: CutRepairPreparationPackageV1;
}

function ensureDirectory(directory: string): void {
  try {
    mkdirSync(directory, { mode: 0o700 });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
  }
  const stat = lstatSync(directory);
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error("cut repair preparation path must be a real directory");
  }
}

function recordPath(producerDir: string, idempotencyKey: string): string {
  const paths = producerAuthorityPaths(producerDir);
  const root = path.join(paths.sagas, "cut-repair-preparation");
  const records = path.join(root, "records");
  [root, records].forEach(ensureDirectory);
  return path.join(records, `${authorityKey(idempotencyKey)}.json`);
}

function pointer(value: unknown): PreparationPointer {
  const row = objectValue(value, "cut repair preparation pointer");
  const keys = [
    "schemaVersion", "kind", "idempotencyKey",
    "targetDirectiveHash", "packageHash",
  ];
  if (Object.keys(row).length !== keys.length
      || keys.some((key) => !(key in row))
      || row.schemaVersion !== 1
      || row.kind !== "cut-repair-preparation-pointer") {
    throw new Error("cut repair preparation pointer is malformed");
  }
  return {
    schemaVersion: 1,
    kind: "cut-repair-preparation-pointer",
    idempotencyKey: uuid(
      row.idempotencyKey, "preparation pointer idempotency key"),
    targetDirectiveHash: sha256(
      row.targetDirectiveHash, "preparation pointer target"),
    packageHash: sha256(row.packageHash, "preparation pointer package"),
  };
}

function verifyAnalysis(
  packageValue: CutRepairPreparationPackageV1,
  analysis: unknown,
): void {
  const row = objectValue(analysis, "stored cut repair analysis");
  const selected = objectValue(
    row.recommendedCandidate, "stored recommended candidate");
  if (row.status !== "eligible"
      || row.parentRevisionHash !== packageValue.parentRevisionHash
      || row.contextAuthorityHash !== packageValue.contextAuthorityHash
      || selected.operationHash
        !== packageValue.proposedReviewAction.operationHash
      || selected.selectionPolicyHash
        !== packageValue.proposedReviewAction.selectionPolicyHash) {
    throw new Error("stored cut repair analysis does not bind preparation");
  }
}

function verifyDependencies(
  producerDir: string,
  packageValue: CutRepairPreparationPackageV1,
): void {
  const paths = producerAuthorityPaths(producerDir);
  const parent = parseProjectRevision(assertObjectHashSync(
    paths.objects.revisions, packageValue.parentRevisionHash));
  const context = objectValue(assertObjectHashSync(
    paths.objects.cutRepairs, packageValue.contextObjectHash),
  "stored cut repair context");
  const analysis = assertObjectHashSync(
    paths.objects.cutRepairs, packageValue.analysisObjectHash);
  const projection = objectValue(assertObjectHashSync(
    paths.objects.cutRepairs, packageValue.reviewProjectionHash),
  "stored cut repair projection");
  const action = packageValue.proposedReviewAction;
  if (parent.workflowState !== "PICTURE_LOCKED"
      || context.authorityHash !== packageValue.contextAuthorityHash
      || action.expectedParentRevisionHash !== packageValue.parentRevisionHash
      || projection.approvedCutPlanHash !== action.reviewPlanObjectHash
      || projection.timelineMapHash !== action.reviewTimelineMapHash) {
    throw new Error("cut repair preparation authority is stale");
  }
  verifyAnalysis(packageValue, analysis);
  const plan = objectValue(assertObjectHashSync(
    paths.objects.plans, action.reviewPlanObjectHash),
  "stored cut repair review plan");
  if (planObjectContentHash(plan) !== action.reviewPlanContentHash) {
    throw new Error("cut repair preparation plan identities disagree");
  }
  const pictureAuthority = bindCutRepairPicturePlanAuthority(
    plan, action.operation, action.reviewTimelineMapHash);
  assertCutRepairPicturePlanParent(
    pictureAuthority, action.operation, parent);
  assertObjectHashSync(
    paths.objects.cutRepairs, packageValue.reviewProjectionHash);
  verifyCutRepairPreparationReviewGraphSync({
    producerDir,
    parent,
    graph: assertObjectHashSync(
      paths.objects.graphs, action.reviewRenderGraphHash),
    plan,
    packageValue,
    pictureAuthority,
  });
}

function verifyMedia(
  producerDir: string,
  packageValue: CutRepairPreparationPackageV1,
): void {
  restorePreparedMediaSync({
    producerDir,
    hash: packageValue.fragmentMediaSha256,
    path: receiptMediaPath(producerDir, packageValue.fragmentReceipt),
    extension: ".mov",
  });
  restorePreparedMediaSync({
    producerDir,
    hash: packageValue.compositeMediaSha256,
    path: receiptMediaPath(producerDir, packageValue.compositeReceipt),
    extension: ".mov",
  });
  verifyCutRepairPreparedRenderSync(producerDir, packageValue);
  verifyCutRepairRenderedCandidateSync(producerDir, packageValue);
}

function loadByPointer(
  producerDir: string,
  observed: PreparationPointer,
): StoredCutRepairPreparation {
  const paths = producerAuthorityPaths(producerDir);
  const packageValue = parseCutRepairPreparationPackageV1(
    assertObjectHashSync(paths.objects.cutRepairs, observed.packageHash));
  if (packageValue.idempotencyKey !== observed.idempotencyKey
      || packageValue.targetDirectiveHash !== observed.targetDirectiveHash) {
    throw new Error("cut repair preparation pointer changed identity");
  }
  verifyDependencies(producerDir, packageValue);
  verifyMedia(producerDir, packageValue);
  return { packageHash: observed.packageHash, package: packageValue };
}

/** Reopen one durable private review preparation and restore its media. */
export function loadCutRepairPreparationSync(
  producerDir: string,
  idempotencyKey: string,
  targetDirectiveHash: string,
): StoredCutRepairPreparation | null {
  const filePath = recordPath(producerDir, idempotencyKey);
  if (!existsSync(filePath)) return null;
  const observed = pointer(readAuthorityJsonSync(filePath));
  if (observed.idempotencyKey !== idempotencyKey
      || observed.targetDirectiveHash !== targetDirectiveHash) {
    throw new Error("preparation idempotency key is bound to another target");
  }
  return loadByPointer(producerDir, observed);
}

/** Reopen a preparation by content identity for review/promotion stages. */
export function loadCutRepairPreparationByHashSync(
  producerDir: string,
  packageHash: string,
): StoredCutRepairPreparation {
  const hash = sha256(packageHash, "cut repair preparation package hash");
  const paths = producerAuthorityPaths(producerDir);
  const packageValue = parseCutRepairPreparationPackageV1(
    assertObjectHashSync(paths.objects.cutRepairs, hash));
  verifyDependencies(producerDir, packageValue);
  verifyMedia(producerDir, packageValue);
  return { packageHash: hash, package: packageValue };
}

/** Content-address real media first, then publish one immutable recovery key. */
export function storeCutRepairPreparationSync(
  producerDir: string,
  value: unknown,
): StoredCutRepairPreparation {
  const packageValue = parseCutRepairPreparationPackageV1(value);
  const paths = producerAuthorityPaths(producerDir);
  storePreparedMediaSync({
    producerDir,
    path: receiptMediaPath(producerDir, packageValue.fragmentReceipt),
    hash: packageValue.fragmentMediaSha256,
    extension: ".mov",
  });
  storePreparedMediaSync({
    producerDir,
    path: receiptMediaPath(producerDir, packageValue.compositeReceipt),
    hash: packageValue.compositeMediaSha256,
    extension: ".mov",
  });
  storePreparedMediaSync({
    producerDir,
    path: packageValue.reviewCandidatePath,
    hash: packageValue.reviewCandidateMediaSha256,
    extension: ".mp4",
  });
  verifyDependencies(producerDir, packageValue);
  const stored = writeAuthorityObjectSync(
    paths.objects.cutRepairs, packageValue);
  const proposed: PreparationPointer = {
    schemaVersion: 1,
    kind: "cut-repair-preparation-pointer",
    idempotencyKey: packageValue.idempotencyKey,
    targetDirectiveHash: packageValue.targetDirectiveHash,
    packageHash: stored.hash,
  };
  const filePath = recordPath(producerDir, packageValue.idempotencyKey);
  publishImmutableAuthorityJsonSync(filePath, proposed);
  const observed = pointer(readAuthorityJsonSync(filePath));
  if (canonicalJsonSha256(observed) !== canonicalJsonSha256(proposed)) {
    throw new Error("preparation idempotency key is bound to another package");
  }
  return loadByPointer(producerDir, observed);
}
