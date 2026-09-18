import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { parsePreparedMediaResult, type PreparedMediaResult } from
  "@/app/api/producer/ai-edit/cut-repair-preparation-plan";
import {
  pictureFixture,
  picturePreparedMedia,
  type PictureFixture,
} from "@/lib/producer/__tests__/_p2-cut-repair-picture-fixture";
import {
  canonicalJsonSha256,
  fileSha256,
} from "../auto-edit-hash";
import { planObjectContentHash } from "../auto-edit-authority";

export interface PrivatePictureFixture {
  root: string;
  producer: string;
  staging: string;
  manifest: string;
  picture: PictureFixture;
  prepared: PreparedMediaResult;
  composite: string;
  parentGraphHash: string;
  parentReceiptHash: string;
  parentMediaHash: string;
}

export function writeTestJson(filePath: string, value: unknown): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`);
}

export function privatePictureFixture(): PrivatePictureFixture {
  const root = fs.realpathSync(
    fs.mkdtempSync(path.join(os.tmpdir(), "sniper-picture-render-")));
  const producer = path.join(root, "producer");
  const staging = path.join(producer, ".sniper-cut-repair-staging", "attempt");
  const manifest = path.join(root, "asset_manifest.json");
  fs.mkdirSync(staging, { recursive: true });
  writeTestJson(manifest, {});
  const picture = pictureFixture();
  const raw = picturePreparedMedia(picture);
  const fragment = raw.fragmentReceipt as Record<string, unknown>;
  const compositeReceipt = raw.compositeReceipt as Record<string, unknown>;
  const fragmentPath = path.join(staging, "fragment.mov");
  const composite = path.join(staging, "candidate.mov");
  fs.writeFileSync(fragmentPath, "fragment bytes\n");
  fs.writeFileSync(composite, "surgical composite bytes\n");
  fragment.output = {
    path: fragmentPath, sha256: fileSha256(fragmentPath),
  };
  fragment.inputs = { source: { sha256: "a".repeat(64) } };
  compositeReceipt.output = {
    path: composite, sha256: fileSha256(composite),
  };
  compositeReceipt.inputs = {
    parentSha256: "b".repeat(64),
    fragmentSha256: fileSha256(fragmentPath),
  };
  compositeReceipt.outsideDirtyOracle = {
    pictureScope: "outside-dirty",
    parentPictureSha256: "c".repeat(64),
    outputPictureSha256: "c".repeat(64),
    parentPcmSha256: "d".repeat(64),
    outputPcmSha256: "d".repeat(64),
    pictureMatches: true,
    pcmMatches: true,
  };
  return {
    root, producer, staging, manifest, picture,
    prepared: parsePreparedMediaResult(raw),
    composite,
    parentGraphHash: "e".repeat(64),
    parentReceiptHash: "f".repeat(64),
    parentMediaHash: "b".repeat(64),
  };
}

function parentAuthority(item: PrivatePictureFixture) {
  return {
    graphHash: item.parentGraphHash,
    receiptHash: item.parentReceiptHash,
    rootNodeId: "node-final",
    rootArtifactPath: path.join(item.producer, "final.mp4"),
    rootMediaSha256: item.parentMediaHash,
    rootPlanContentHash: "1".repeat(64),
  };
}

export function pictureTerminal(
  item: PrivatePictureFixture,
  candidate: string,
) {
  const prepared = item.prepared;
  const picture = prepared.picturePlanAuthority!;
  const partition = {
    revalidatedDependentIds: prepared.operation.revalidatedDependentIds,
    unchangedDependentIds: prepared.operation.unchangedDependentIds,
  };
  const parent = parentAuthority(item);
  return {
    schemaVersion: 1, kind: "cut-repair-surgical-terminal",
    operationHash: prepared.operationHash,
    reviewPlanObjectHash: prepared.reviewPlanHash,
    reviewPlanContentHash: planObjectContentHash(prepared.reviewPlan),
    reviewTimelineMapHash: prepared.reviewTimelineMapHash,
    picturePlanAuthorityHash: picture.authorityHash,
    parentPlanObjectHash: picture.parentPlanObjectHash,
    parentRenderAuthority: parent,
    parentRenderAuthorityHash: canonicalJsonSha256(parent),
    mappingProofHash: picture.mappingProofHash,
    reversionHash: canonicalJsonSha256(picture.reversion),
    selectionPolicyHash: prepared.selectionPolicyHash,
    fragmentReceiptHash: canonicalJsonSha256(prepared.fragmentReceipt),
    compositeReceiptHash: canonicalJsonSha256(prepared.compositeReceipt),
    sourceSelection: {
      sourceId: prepared.operation.target.sourceId,
      sourceMediaSha256: "a".repeat(64),
      sourceExtension: prepared.operation.sourceExtension,
      sourceFrameRange: prepared.operation.sourceVideoFrameRange,
    },
    dependencyPartition: partition,
    dependencyPartitionHash: canonicalJsonSha256(partition),
    dirtyFrameRange: picture.dirtyFrameRange,
    outsideDirtyOracle: prepared.compositeReceipt.outsideDirtyOracle,
    candidate: {
      path: candidate, sha256: fileSha256(candidate),
      sourceCompositePath: item.composite,
      sourceCompositeSha256: fileSha256(item.composite),
    },
    deliveryDisposition: {
      candidateConstruction: "proved-composite-exact-byte-copy",
      planReconstruction: "surgical-terminal-not-plan-only-reconstructable",
      palmier: "reference-media-only-no-native-editability",
    },
    contractHash: "2".repeat(64),
  };
}

export function privatePictureInput(item: PrivatePictureFixture) {
  return {
    producerDir: item.producer,
    stagingDir: item.staging,
    manifestPath: item.manifest,
    reviewPlan: item.prepared.reviewPlan,
    planObjectHash: item.prepared.reviewPlanHash,
    planContentHash: planObjectContentHash(item.prepared.reviewPlan)!,
    prepared: item.prepared,
  };
}

export function addUnsupportedPictureLane(
  item: PrivatePictureFixture,
): void {
  const raw = structuredClone(item.prepared.preparedMedia);
  const plan = raw.reviewPlan as Record<string, unknown>;
  const projection = raw.reviewProjection as Record<string, unknown>;
  plan.captions = true;
  const planHash = canonicalJsonSha256(plan);
  raw.reviewPlanHash = planHash;
  projection.approvedCutPlanHash = planHash;
  item.prepared = parsePreparedMediaResult(raw);
}
