import type {
  PalmierSagaCandidateProofV1,
} from "@/lib/producer/contracts/palmier-saga-bridge";
import {
  palmierCandidateReservationValue,
} from "@/lib/producer/contracts/palmier-saga-bridge";
import {
  parseProjectRevision,
  type ProjectRevisionV2,
} from "@/lib/producer/contracts/project-revision";
import { parseRenderGraphV1 } from
  "@/lib/producer/contracts/render-graph";
import type { PalmierCommitSagaV1 } from
  "@/lib/producer/contracts/palmier-commit-saga";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { planObjectContentHash } from "./auto-edit-authority";
import {
  assertObjectHashSync,
  producerAuthorityPaths,
  writeAuthorityObjectSync,
  type ProducerAuthorityPaths,
} from "./producer-authority-files";
import {
  initializeProducerAuthoritySync,
  publishProducerAdvanceSync,
  resolveProducerAuthorityHeadSync,
} from "./producer-revision-head";
import {
  assertRevisionPlanObjectSync,
  revisionV2WriteFrom,
  writeProjectRevisionV2Sync,
} from "./producer-plan-authority";
import { parseProducerAdvanceRecordV1 } from
  "./producer-revision-store-model";
import { unresolvedProducerIntentsSync } from
  "./producer-revision-recovery";

export interface ReservedPalmierRevisionV1 {
  expectedParentHash: string;
  childHash: string;
  reservationHash: string;
}

function bindingPlan(
  proof: PalmierSagaCandidateProofV1,
  timelineId: string,
  timelineHash: string,
): Record<string, unknown> {
  return {
    schemaVersion: 1,
    kind: "palmier-native-timeline-binding",
    projectId: proof.projectId,
    timelineId,
    timelineHash,
  };
}

function graph(
  proof: PalmierSagaCandidateProofV1,
  timelineId: string,
  timelineHash: string,
) {
  return parseRenderGraphV1({
    schemaVersion: 1,
    graphId: `palmier-${timelineId}`,
    toolchainHash: canonicalJsonSha256({
      adapter: "palmier-native-revision-binding",
      version: 1,
    }),
    rootNodeId: "node-final",
    nodes: [
      {
        nodeId: "node-palmier-parent",
        kind: "source-snapshot",
        dependencies: [],
        inputDigests: { "palmier.project": proof.inputAuthorityDigest },
        outputArtifactHash: timelineHash,
        frameRange: null,
      },
      {
        nodeId: "node-final",
        kind: "preview",
        dependencies: ["node-palmier-parent"],
        inputDigests: { "palmier.timeline": timelineHash },
        outputArtifactHash: timelineHash,
        frameRange: null,
      },
    ],
  });
}

function revisionAt(
  paths: ProducerAuthorityPaths,
  hash: string,
): ProjectRevisionV2 {
  const revision = parseProjectRevision(assertObjectHashSync(
    paths.objects.revisions, hash));
  if (revision.schemaVersion !== 2) {
    throw new Error("Palmier saga local authority requires ProjectRevisionV2");
  }
  assertRevisionPlanObjectSync(paths, revision);
  return revision;
}

function ensureGenesis(
  producerDir: string,
  paths: ProducerAuthorityPaths,
  proof: PalmierSagaCandidateProofV1,
): string {
  try {
    return resolveProducerAuthorityHeadSync(producerDir);
  } catch (error) {
    if (!String(error).includes("uninitialized")) throw error;
  }
  const plan = bindingPlan(
    proof, proof.expectedParentId, proof.expectedParentTimelineHash);
  const ledger = writeAuthorityObjectSync(paths.objects.requests, {
    schemaVersion: 1,
    kind: "palmier-native-genesis-ledger",
    inputAuthorityDigest: proof.inputAuthorityDigest,
  });
  const storedGraph = writeAuthorityObjectSync(
    paths.objects.graphs,
    graph(proof, proof.expectedParentId, proof.expectedParentTimelineHash),
  );
  const initialized = initializeProducerAuthoritySync(producerDir, {
    schemaVersion: 1,
    parentRevisionHash: null,
    planContentHash: planObjectContentHash(plan),
    manifestHash: proof.manifestHash,
    sourceSnapshotSetHash: proof.inputAuthorityDigest,
    transcriptTimingHash: proof.transcriptTimingHash,
    timelineMapHash: proof.expectedParentTimelineHash,
    canvasProfileHash: proof.canvasProfileHash,
    destinationProfileHashes: [proof.canvasProfileHash],
    pictureLockHash: null,
    workflowState: "TREATMENT_REVIEW",
    requestLedgerHash: ledger.hash,
    renderGraphHash: storedGraph.hash,
    projectionReceiptHash: null,
    authoritativeSidecars: {
      palmierNativeInputAuthorityV1: proof.inputAuthorityDigest,
    },
  }, plan);
  return initialized.revisionHash;
}

function reservationValue(
  proof: PalmierSagaCandidateProofV1,
  expectedParentHash: string,
): Record<string, unknown> {
  return {
    schemaVersion: 1,
    kind: "palmier-native-dual-commit-reservation",
    expectedLocalParentHash: expectedParentHash,
    candidateHash: proof.candidateHash,
    ...palmierCandidateReservationValue(proof),
  };
}

/** Materialize the immutable local child without publishing its parent advance. */
export function reservePalmierRevisionChildSync(
  producerDir: string,
  proof: PalmierSagaCandidateProofV1,
): ReservedPalmierRevisionV1 {
  const paths = producerAuthorityPaths(producerDir);
  if (unresolvedProducerIntentsSync(producerDir).length) {
    throw new Error("Palmier dual commit is blocked by an unresolved edit intent");
  }
  const expectedParentHash = ensureGenesis(producerDir, paths, proof);
  const parent = revisionAt(paths, expectedParentHash);
  const plan = assertRevisionPlanObjectSync(paths, parent);
  if (!plan) throw new Error("Palmier saga parent has no exact plan object");
  const reservation = writeAuthorityObjectSync(
    paths.objects.receipts,
    reservationValue(proof, expectedParentHash),
  );
  const storedGraph = writeAuthorityObjectSync(
    paths.objects.graphs,
    graph(proof, proof.candidateId, proof.timelineHash),
  );
  const child = writeProjectRevisionV2Sync({
    paths,
    planObject: plan,
    revision: {
      ...revisionV2WriteFrom(parent),
      parentRevisionHash: expectedParentHash,
      workflowState: "QC_APPROVED",
      timelineMapHash: proof.timelineHash,
      renderGraphHash: storedGraph.hash,
      authoritativeSidecars: {
        ...parent.authoritativeSidecars,
        palmierNativeDualCommitReservationV1: reservation.hash,
      },
    },
  });
  return {
    expectedParentHash,
    childHash: child.revisionHash,
    reservationHash: reservation.hash,
  };
}

/** Re-prove the exact child and its external reservation after restart. */
export function provePalmierRevisionChildSync(
  producerDir: string,
  proof: PalmierSagaCandidateProofV1,
  saga: PalmierCommitSagaV1,
): boolean {
  const paths = producerAuthorityPaths(producerDir);
  const reservation = writeAuthorityObjectSync(
    paths.objects.receipts,
    reservationValue(proof, saga.expectedLocalParentHash),
  );
  const child = revisionAt(paths, saga.reservedLocalChildHash);
  return child.parentRevisionHash === saga.expectedLocalParentHash
    && child.authoritativeSidecars.palmierNativeDualCommitReservationV1
      === reservation.hash
    && child.timelineMapHash === proof.timelineHash
    && child.workflowState === "QC_APPROVED";
}

export function publishPalmierRevisionChildSync(
  producerDir: string,
  saga: PalmierCommitSagaV1,
): void {
  const paths = producerAuthorityPaths(producerDir);
  const requestDigest = canonicalJsonSha256({
    kind: "palmier-native-dual-commit",
    candidateHash: saga.reservedPalmierCandidateHash,
    timelineHash: saga.reservedPalmierTimelineHash,
  });
  publishProducerAdvanceSync(paths, parseProducerAdvanceRecordV1({
    schemaVersion: 1,
    expectedParentRevisionHash: saga.expectedLocalParentHash,
    childRevisionHash: saga.reservedLocalChildHash,
    idempotencyKey: saga.idempotencyKey,
    requestDigest,
  }));
}
