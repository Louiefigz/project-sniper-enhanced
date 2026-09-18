import { existsSync } from "node:fs";
import path from "node:path";
import { parseCommitIntentV1, type CommitIntentV1 } from
  "@/lib/producer/contracts/commit-intent";
import { parseEditBatchV1, type EditBatchV1 } from "@/lib/producer/contracts/edit-batch";
import { buildEditReceiptV1 } from "@/lib/producer/contracts/edit-receipt";
import {
  committedRequest,
  parseEditRequestV1,
  type EditRequestV1,
} from "@/lib/producer/contracts/edit-request";
import { type ProjectRevisionDraftV2, type ProjectRevisionV2 } from
  "@/lib/producer/contracts/project-revision";
import {
  parseProjectionReceiptV1,
  type ProjectionReceiptV1,
} from "@/lib/producer/contracts/projection-receipt";
import {
  parseInvalidationReceiptV1,
  parseRenderGraphV1,
  type InvalidationReceiptV1,
  type RenderGraphV1,
} from "@/lib/producer/contracts/render-graph";
import { objectValue, sha256 } from "@/lib/producer/contracts/validation";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { assertCutInvalidation, assertStageRevisionBindings } from
  "./producer-cut-repair-bindings";
import { storeCutRepairPromotionSync, type CutRepairPromotionInput } from
  "./producer-cut-repair-artifacts";
import {
  authorityKey,
  producerAuthorityPaths,
  publishImmutableAuthorityJsonSync,
  readAuthorityJsonSync,
  writeAuthorityObjectSync,
  writeMutableAuthorityJsonSync,
  type ProducerAuthorityPaths,
} from "./producer-authority-files";
import {
  parseProducerIdempotencyRecordV1,
  type ProducerIdempotencyRecordV1,
} from "./producer-revision-store-model";
import { writeProjectRevisionV2Sync } from "./producer-plan-authority";
export interface ProducerRevisionCommitInput {
  producerDir: string;
  request: EditRequestV1;
  batch: EditBatchV1;
  revision: ProjectRevisionDraftV2;
  planObject: unknown;
  renderGraph: RenderGraphV1;
  projectionReceipt: ProjectionReceiptV1 | null;
  invalidationReceipt: InvalidationReceiptV1;
  invariantProofHash: string;
  cutRepairProof?: CutRepairPromotionInput;
}
export interface MaterializedProducerCommit {
  paths: ProducerAuthorityPaths;
  record: ProducerIdempotencyRecordV1;
  intent: CommitIntentV1;
  replayed: boolean;
}

interface ParsedCommit {
  request: EditRequestV1;
  batch: EditBatchV1;
  graph: RenderGraphV1;
  projection: ProjectionReceiptV1 | null;
  invalidation: InvalidationReceiptV1;
  invariantProofHash: string;
  requestDigest: string;
  legacyRequestDigest: string;
  planObject: Record<string, unknown>;
}

interface StoredDependencies {
  requestInputHash: string;
  requestOutcomeHash: string;
  batchHash: string;
  graphHash: string;
  projectionHash: string | null;
}

function receiptUuid(requestDigest: string): string {
  const hex = requestDigest.slice(0, 32);
  return [hex.slice(0, 8), hex.slice(8, 12), `5${hex.slice(13, 16)}`,
    `a${hex.slice(17, 20)}`, hex.slice(20, 32)].join("-");
}

function parseCommit(input: ProducerRevisionCommitInput): ParsedCommit {
  const request = parseEditRequestV1(input.request);
  const batch = parseEditBatchV1(input.batch, request);
  const graph = parseRenderGraphV1(input.renderGraph);
  const projection = input.projectionReceipt
    ? parseProjectionReceiptV1(input.projectionReceipt) : null;
  const invalidation = parseInvalidationReceiptV1(input.invalidationReceipt);
  const planObject = objectValue(input.planObject, "canonical plan object");
  if (canonicalJsonSha256(graph) !== invalidation.graphAfterHash) {
    throw new Error("render graph does not match its invalidation receipt");
  }
  assertCutInvalidation(batch, invalidation, graph);
  const invariantProofHash = sha256(input.invariantProofHash, "invariantProofHash");
  const legacyAuthority = {
    request,
    batch,
    revision: input.revision,
    graph,
    projection,
    invalidation,
    invariantProofHash,
  };
  return {
    request,
    batch,
    graph,
    projection,
    invalidation,
    invariantProofHash,
    requestDigest: canonicalJsonSha256({
      ...legacyAuthority,
      planObject,
    }),
    legacyRequestDigest: canonicalJsonSha256(legacyAuthority),
    planObject,
  };
}
function idempotencyPath(
  paths: ProducerAuthorityPaths,
  key: string,
): string {
  return path.join(paths.idempotency, `${authorityKey(key)}.json`);
}
function existingRecord(
  paths: ProducerAuthorityPaths,
  parsed: ParsedCommit,
): ProducerIdempotencyRecordV1 | null {
  const destination = idempotencyPath(paths, parsed.request.idempotencyKey);
  if (!existsSync(destination)) return null;
  const record = parseProducerIdempotencyRecordV1(readAuthorityJsonSync(destination));
  if (record.idempotencyKey !== parsed.request.idempotencyKey
      || ![parsed.requestDigest, parsed.legacyRequestDigest]
        .includes(record.requestDigest)) {
    throw new Error("idempotency key is bound to a different exact request");
  }
  return record;
}
function storeDependencies(
  paths: ProducerAuthorityPaths,
  parsed: ParsedCommit,
): StoredDependencies {
  const clauseIds = new Set(parsed.batch.operations.map((row) => row.clauseId));
  const requestInput = writeAuthorityObjectSync(paths.objects.requests, parsed.request);
  const requestOutcome = writeAuthorityObjectSync(
    paths.objects.requests,
    committedRequest(parsed.request, clauseIds),
  );
  const batch = writeAuthorityObjectSync(paths.objects.batches, parsed.batch);
  const graph = writeAuthorityObjectSync(paths.objects.graphs, parsed.graph);
  const projection = parsed.projection
    ? writeAuthorityObjectSync(paths.objects.projections, parsed.projection) : null;
  return {
    requestInputHash: requestInput.hash,
    requestOutcomeHash: requestOutcome.hash,
    batchHash: batch.hash,
    graphHash: graph.hash,
    projectionHash: projection?.hash ?? null,
  };
}
function writeObjects(
  paths: ProducerAuthorityPaths,
  input: ProducerRevisionCommitInput,
  parsed: ParsedCommit,
): ProducerIdempotencyRecordV1 {
  const stored = storeDependencies(paths, parsed);
  const storedRevision = writeProjectRevisionV2Sync({
    paths,
    planObject: parsed.planObject,
    revision: {
      ...input.revision,
      parentRevisionHash: parsed.request.parentRevisionHash,
      requestLedgerHash: stored.requestOutcomeHash,
      renderGraphHash: stored.graphHash,
      projectionReceiptHash: stored.projectionHash,
    },
  });
  const revision = storedRevision.revision;
  assertRevisionBindings(revision, parsed);
  const cutRepair = storeCutRepairPromotionSync({
    paths, producerDir: input.producerDir,
    input: input.cutRepairProof,
    batch: parsed.batch, revision,
    invariantProofHash: parsed.invariantProofHash,
  });
  const receipt = storeReceiptDraft(
    paths, parsed, revision, storedRevision.revisionHash);
  return {
    schemaVersion: 1,
    idempotencyKey: parsed.request.idempotencyKey,
    requestDigest: parsed.requestDigest,
    expectedParentRevisionHash: parsed.request.parentRevisionHash,
    childRevisionHash: storedRevision.revisionHash,
    artifactHashes: {
      requestInput: stored.requestInputHash,
      requestOutcome: stored.requestOutcomeHash,
      batch: stored.batchHash,
      renderGraph: stored.graphHash,
      ...(stored.projectionHash
        ? { projectionReceipt: stored.projectionHash } : {}),
      plan: storedRevision.planObjectHash,
      revision: storedRevision.revisionHash,
      receiptDraft: receipt.receiptHash,
      ...cutRepair,
    },
    receiptId: receipt.receiptId,
    recordedAt: receipt.recordedAt,
    invariantProofHash: parsed.invariantProofHash,
  };
}
function storeReceiptDraft(
  paths: ProducerAuthorityPaths,
  parsed: ParsedCommit,
  revision: ProjectRevisionV2,
  revisionHash: string,
): { receiptHash: string; receiptId: string; recordedAt: string } {
  const receiptId = receiptUuid(parsed.requestDigest);
  const recordedAt = parsed.request.submittedAt;
  const receipt = buildEditReceiptV1({
    batch: parsed.batch,
    childRevisionHash: revisionHash,
    afterPlanHash: revision.planContentHash,
    receiptId,
    recordedAt,
    invalidation: parsed.invalidation,
    invariantProofHash: parsed.invariantProofHash,
    committed: false,
  });
  const receiptObject = writeAuthorityObjectSync(paths.objects.receipts, receipt);
  return {
    receiptHash: receiptObject.hash,
    receiptId,
    recordedAt,
  };
}
function assertRevisionBindings(
  revision: ProjectRevisionV2,
  parsed: ParsedCommit,
): void {
  const base = parsed.batch.base;
  if (revision.parentRevisionHash !== base.projectRevisionHash
      || revision.manifestHash !== base.manifestHash
      || revision.sourceSnapshotSetHash !== base.sourceSnapshotSetHash
      || revision.canvasProfileHash !== base.canvasProfileHash
      || JSON.stringify(revision.destinationProfileHashes)
        !== JSON.stringify(base.destinationProfileHashes)) {
    throw new Error("child revision does not preserve the batch base authority");
  }
  assertStageRevisionBindings(
    revision, parsed.batch, parsed.invariantProofHash);
  if (parsed.projection && (
    parsed.projection.canonicalPlanHash !== revision.planContentHash
    || parsed.projection.manifestHash !== revision.manifestHash
    || parsed.projection.sourceSnapshotSetHash !== revision.sourceSnapshotSetHash
    || parsed.projection.timelineMapHash !== revision.timelineMapHash
  )) {
    throw new Error("projection receipt does not bind the child revision");
  }
}
function preparedIntent(record: ProducerIdempotencyRecordV1): CommitIntentV1 {
  return parseCommitIntentV1({
    schemaVersion: 1,
    idempotencyKey: record.idempotencyKey,
    requestDigest: record.requestDigest,
    expectedParentRevisionHash: record.expectedParentRevisionHash,
    childRevisionHash: record.childRevisionHash,
    state: "PREPARING",
    artifactHashes: record.artifactHashes,
    receiptHash: null,
    recordedAt: record.recordedAt,
    updatedAt: record.recordedAt,
  });
}
export function materializeProducerCommitSync(
  input: ProducerRevisionCommitInput,
): MaterializedProducerCommit {
  const parsed = parseCommit(input);
  const paths = producerAuthorityPaths(input.producerDir);
  const prior = existingRecord(paths, parsed);
  const record = prior ?? writeObjects(paths, input, parsed);
  if (!prior) {
    publishImmutableAuthorityJsonSync(
      idempotencyPath(paths, record.idempotencyKey),
      record,
    );
  }
  const intentPath = path.join(paths.intents, `${authorityKey(record.idempotencyKey)}.json`);
  const intent = existsSync(intentPath)
    ? parseCommitIntentV1(readAuthorityJsonSync(intentPath))
    : preparedIntent(record);
  if (!existsSync(intentPath)) writeMutableAuthorityJsonSync(intentPath, intent);
  return { paths, record, intent, replayed: prior !== null };
}
