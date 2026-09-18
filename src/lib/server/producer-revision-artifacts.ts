import { parseEditBatchV1 } from "@/lib/producer/contracts/edit-batch";
import { parseEditReceiptV1 } from "@/lib/producer/contracts/edit-receipt";
import { parseEditRequestV1 } from "@/lib/producer/contracts/edit-request";
import { parseProjectRevision } from "@/lib/producer/contracts/project-revision";
import { parseProjectionReceiptV1 } from "@/lib/producer/contracts/projection-receipt";
import { parseRenderGraphV1 } from "@/lib/producer/contracts/render-graph";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { verifyStoredCutRepairPromotionSync } from
  "./producer-cut-repair-artifact-verification";
import {
  assertObjectHashSync,
  writeAuthorityObjectSync,
  type ProducerAuthorityPaths,
} from "./producer-authority-files";
import type {
  ProducerIdempotencyRecordV1,
} from "./producer-revision-store-model";
import { assertRevisionPlanObjectSync } from "./producer-plan-authority";

interface ArtifactBindings {
  record: ProducerIdempotencyRecordV1;
  request: ReturnType<typeof parseEditRequestV1>;
  outcome: ReturnType<typeof parseEditRequestV1>;
  batch: ReturnType<typeof parseEditBatchV1>;
  revision: ReturnType<typeof parseProjectRevision>;
  receipt: ReturnType<typeof parseEditReceiptV1>;
  projection: ReturnType<typeof parseProjectionReceiptV1> | null;
}

function committedReceipt(
  draft: ReturnType<typeof parseEditReceiptV1>,
): ReturnType<typeof parseEditReceiptV1> {
  return parseEditReceiptV1({
    ...draft,
    status: "committed",
    operations: draft.operations.map((operation) => ({
      ...operation,
      executionState: "committed",
      explanation: "deterministic operation committed with the bound revision",
    })),
  });
}

function assertArtifactBindings(value: ArtifactBindings): void {
  const { record, request, outcome, batch, revision, receipt, projection } = value;
  const hashes = record.artifactHashes;
  const committedIds = new Set(batch.operations.map((row) => row.clauseId));
  const finalStates = new Map(outcome.clauses.map((row) => [row.clauseId, row.state]));
  if (hashes.revision !== record.childRevisionHash
      || revision.parentRevisionHash !== record.expectedParentRevisionHash
      || revision.requestLedgerHash !== hashes.requestOutcome
      || revision.renderGraphHash !== hashes.renderGraph
      || (revision.schemaVersion === 2
        && (revision.planObjectHash !== hashes.plan || !hashes.plan))
      || revision.projectionReceiptHash !== (hashes.projectionReceipt ?? null)
      || (projection !== null
        && projection.canonicalPlanHash !== revision.planContentHash)
      || receipt.status !== "candidate-proved"
      || receipt.childRevisionHash !== record.childRevisionHash
      || receipt.parentRevisionHash !== record.expectedParentRevisionHash
      || receipt.requestId !== request.requestId
      || receipt.batchId !== batch.batchId
      || receipt.idempotencyKey !== record.idempotencyKey
      || outcome.requestId !== request.requestId
      || outcome.idempotencyKey !== request.idempotencyKey
      || [...committedIds].some(
        (clauseId) => finalStates.get(clauseId) !== "committed",
      )) {
    throw new Error("materialized commit artifacts do not bind one exact transition");
  }
}

/** Reopen and cross-bind every immutable artifact before advancing authority. */
export function verifyProducerCommitArtifactsSync(
  paths: ProducerAuthorityPaths,
  record: ProducerIdempotencyRecordV1,
): void {
  const hashes = record.artifactHashes;
  const request = parseEditRequestV1(
    assertObjectHashSync(paths.objects.requests, hashes.requestInput),
  );
  const outcome = parseEditRequestV1(
    assertObjectHashSync(paths.objects.requests, hashes.requestOutcome),
  );
  const batch = parseEditBatchV1(
    assertObjectHashSync(paths.objects.batches, hashes.batch),
    request,
  );
  parseRenderGraphV1(
    assertObjectHashSync(paths.objects.graphs, hashes.renderGraph),
  );
  const revision = parseProjectRevision(
    assertObjectHashSync(paths.objects.revisions, hashes.revision),
  );
  assertRevisionPlanObjectSync(paths, revision);
  const receipt = parseEditReceiptV1(
    assertObjectHashSync(paths.objects.receipts, hashes.receiptDraft),
  );
  const projection = hashes.projectionReceipt
    ? parseProjectionReceiptV1(
      assertObjectHashSync(paths.objects.projections, hashes.projectionReceipt),
    ) : null;
  assertArtifactBindings({
    record, request, outcome, batch, revision, receipt, projection,
  });
  verifyStoredCutRepairPromotionSync(paths, record, batch, revision);
}

export function writeCommittedProducerReceiptSync(
  paths: ProducerAuthorityPaths,
  record: ProducerIdempotencyRecordV1,
): string {
  const draft = parseEditReceiptV1(
    assertObjectHashSync(paths.objects.receipts, record.artifactHashes.receiptDraft),
  );
  return writeAuthorityObjectSync(paths.objects.receipts, committedReceipt(draft)).hash;
}

export function verifyCommittedProducerReceiptSync(
  paths: ProducerAuthorityPaths,
  record: ProducerIdempotencyRecordV1,
  receiptHash: string,
): void {
  const draft = parseEditReceiptV1(
    assertObjectHashSync(paths.objects.receipts, record.artifactHashes.receiptDraft),
  );
  const committed = parseEditReceiptV1(
    assertObjectHashSync(paths.objects.receipts, receiptHash),
  );
  if (canonicalJsonSha256(committed) !== canonicalJsonSha256(
    committedReceipt(draft),
  )) {
    throw new Error("committed receipt does not match its proved candidate receipt");
  }
}
