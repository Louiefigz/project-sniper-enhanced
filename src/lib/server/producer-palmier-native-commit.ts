import {
  existsSync,
  lstatSync,
  readFileSync,
  readdirSync,
} from "node:fs";
import path from "node:path";
import {
  parsePalmierCommitSagaV1,
  type PalmierCommitSagaV1,
} from "@/lib/producer/contracts/palmier-commit-saga";
import {
  palmierCandidateReservationValue,
  type PalmierSagaCandidateProofV1,
  type PalmierSagaObservationV1,
} from "@/lib/producer/contracts/palmier-saga-bridge";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import {
  authorityKey,
  producerAuthorityPaths,
} from "./producer-authority-files";
import {
  initializeProducerPalmierSagaSync,
  recoverProducerPalmierSagaSync,
  type PalmierSagaAdapterV1,
} from "./producer-palmier-saga";
import {
  provePalmierRevisionChildSync,
  publishPalmierRevisionChildSync,
  reservePalmierRevisionChildSync,
} from "./producer-palmier-revision-candidate";
import { resolveProducerAuthorityHeadSync } from "./producer-revision-head";

export interface PalmierNativeSagaBridgeV1 {
  proveCandidate: () => PalmierSagaCandidateProofV1;
  observeHead: () => PalmierSagaObservationV1;
  promoteCandidate: (expectedParentId: string, candidateId: string) => void;
}

export interface PalmierNativeDualCommitOutcomeV1 {
  status: "candidate-promoted";
  approvedHead: {
    projectId: string;
    timelineId: string;
    fingerprint: string;
  };
  localRevisionHash: string;
  sagaState: "COMMITTED";
}

export type PalmierNativeCommitBoundaryV1 =
  | "after-local-child-reserved"
  | "after-saga-initialized";

export interface PalmierNativeCommitHooksV1 {
  after?: (boundary: PalmierNativeCommitBoundaryV1) => void;
}

function deterministicUuid(label: string, value: unknown): string {
  const digest = canonicalJsonSha256({ label, value });
  return [
    digest.slice(0, 8),
    digest.slice(8, 12),
    `5${digest.slice(13, 16)}`,
    `a${digest.slice(17, 20)}`,
    digest.slice(20, 32),
  ].join("-");
}

function sameProof(
  left: PalmierSagaCandidateProofV1,
  right: PalmierSagaCandidateProofV1,
): boolean {
  return left.candidateHash === right.candidateHash
    && canonicalJsonSha256(palmierCandidateReservationValue(left))
      === canonicalJsonSha256(palmierCandidateReservationValue(right));
}

function sagaMatchesProof(
  saga: PalmierCommitSagaV1,
  proof: PalmierSagaCandidateProofV1,
): boolean {
  return saga.expectedPalmierParentId === proof.expectedParentId
    && saga.reservedPalmierCandidateId === proof.candidateId
    && saga.reservedPalmierCandidateHash === proof.candidateHash
    && saga.reservedPalmierTimelineHash === proof.timelineHash;
}

function readSagaFile(filePath: string): PalmierCommitSagaV1 {
  const info = lstatSync(filePath);
  if (!info.isFile() || info.isSymbolicLink() || info.nlink !== 1) {
    throw new Error("Palmier startup saga is not one safe regular file");
  }
  return parsePalmierCommitSagaV1(
    JSON.parse(readFileSync(filePath, "utf8")),
  );
}

function pendingSaga(producerDir: string): PalmierCommitSagaV1 | null {
  const root = producerAuthorityPaths(producerDir).sagas;
  const pending = readdirSync(root, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".json"))
    .map((entry) => readSagaFile(path.join(root, entry.name)))
    .filter((saga) => ![
      "COMMITTED", "ABORTED", "RECONCILIATION_REQUIRED",
    ].includes(saga.state));
  if (pending.length > 1) {
    throw new Error("multiple nonterminal Palmier commit sagas require reconciliation");
  }
  return pending[0] ?? null;
}

/** Read the durable state for one candidate without starting any effect. */
export function palmierSagaStateForCandidateSync(
  producerDir: string,
  candidateId: string,
): PalmierCommitSagaV1["state"] | null {
  const root = path.join(
    producerDir, ".sniper-authority-v1", "sagas");
  if (!existsSync(root)) return null;
  const matches = readdirSync(root, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".json"))
    .map((entry) => readSagaFile(path.join(root, entry.name)))
    .filter((saga) => saga.reservedPalmierCandidateId === candidateId);
  if (matches.length > 1) {
    throw new Error("Palmier candidate has conflicting durable commit sagas");
  }
  return matches[0]?.state ?? null;
}

function sagaPath(producerDir: string, idempotencyKey: string): string {
  const name = `${authorityKey(idempotencyKey)}.json`;
  return path.join(producerAuthorityPaths(producerDir).sagas, name);
}

function adapter(
  producerDir: string,
  bridge: PalmierNativeSagaBridgeV1,
  expectedProof?: PalmierSagaCandidateProofV1,
): PalmierSagaAdapterV1 {
  let selectedSaga: PalmierCommitSagaV1 | null = null;
  return {
    proveCandidates: (saga) => {
      const proof = bridge.proveCandidate();
      selectedSaga = saga;
      return (!expectedProof || sameProof(expectedProof, proof))
        && sagaMatchesProof(saga, proof)
        && provePalmierRevisionChildSync(producerDir, proof, saga);
    },
    observePalmier: () => {
      const observed = bridge.observeHead();
      return {
        headId: observed.headId,
        candidateHash: observed.candidateHash,
        timelineHash: observed.timelineHash,
        observedAt: observed.observedAt,
      };
    },
    activatePalmier: (expectedParentId, candidateId) => {
      bridge.promoteCandidate(expectedParentId, candidateId);
    },
    observeLocal: () => resolveProducerAuthorityHeadSync(producerDir),
    commitLocal: (expectedParentHash, childHash) => {
      if (!selectedSaga
          || selectedSaga.expectedLocalParentHash !== expectedParentHash
          || selectedSaga.reservedLocalChildHash !== childHash) {
        throw new Error("Palmier local commit was not preceded by exact proof");
      }
      publishPalmierRevisionChildSync(producerDir, selectedSaga);
    },
  };
}

function newSagaValue(
  proof: PalmierSagaCandidateProofV1,
  expectedParentHash: string,
  childHash: string,
): PalmierCommitSagaV1 {
  return {
    schemaVersion: 1,
    sagaId: deterministicUuid("palmier-saga", proof.candidateHash),
    idempotencyKey: deterministicUuid(
      "palmier-dual-commit", proof.candidateHash),
    state: "PREPARING",
    expectedLocalParentHash: expectedParentHash,
    reservedLocalChildHash: childHash,
    expectedPalmierParentId: proof.expectedParentId,
    reservedPalmierCandidateId: proof.candidateId,
    reservedPalmierCandidateHash: proof.candidateHash,
    reservedPalmierTimelineHash: proof.timelineHash,
    activationReadback: null,
    updatedAt: new Date().toISOString(),
  };
}

function recover(
  producerDir: string,
  saga: PalmierCommitSagaV1,
  bridge: PalmierNativeSagaBridgeV1,
  proof?: PalmierSagaCandidateProofV1,
): PalmierCommitSagaV1 {
  return recoverProducerPalmierSagaSync(
    producerDir,
    saga.idempotencyKey,
    adapter(producerDir, bridge, proof),
  );
}

function executeCommit(
  producerDir: string,
  bridge: PalmierNativeSagaBridgeV1,
  hooks: PalmierNativeCommitHooksV1,
): {
  saga: PalmierCommitSagaV1;
  proof: PalmierSagaCandidateProofV1 | undefined;
} {
  let observedProof: PalmierSagaCandidateProofV1 | undefined;
  const trackedBridge: PalmierNativeSagaBridgeV1 = {
    proveCandidate: () => {
      observedProof = bridge.proveCandidate();
      return observedProof;
    },
    observeHead: () => bridge.observeHead(),
    promoteCandidate: (parent, candidate) =>
      bridge.promoteCandidate(parent, candidate),
  };
  const interrupted = pendingSaga(producerDir);
  let proof: PalmierSagaCandidateProofV1 | undefined;
  let saga: PalmierCommitSagaV1;
  if (interrupted) {
    saga = recover(producerDir, interrupted, trackedBridge);
  } else {
    proof = trackedBridge.proveCandidate();
    const idempotencyKey = deterministicUuid(
      "palmier-dual-commit", proof.candidateHash);
    const existingPath = sagaPath(producerDir, idempotencyKey);
    if (existsSync(existingPath)) {
      saga = recover(
        producerDir, readSagaFile(existingPath), trackedBridge, proof);
    } else {
      const reserved = reservePalmierRevisionChildSync(producerDir, proof);
      hooks.after?.("after-local-child-reserved");
      saga = newSagaValue(
        proof, reserved.expectedParentHash, reserved.childHash);
      initializeProducerPalmierSagaSync(producerDir, saga);
      hooks.after?.("after-saga-initialized");
      saga = recover(producerDir, saga, trackedBridge, proof);
    }
  }
  return { saga, proof: observedProof };
}

/**
 * Production commit boundary for an approved Palmier candidate plus its local
 * ProjectRevision child. Startup always resumes a nonterminal saga first.
 */
export function commitApprovedPalmierCandidateSync(
  producerDir: string,
  bridge: PalmierNativeSagaBridgeV1,
  hooks: PalmierNativeCommitHooksV1 = {},
): PalmierNativeDualCommitOutcomeV1 {
  const { saga, proof } = executeCommit(producerDir, bridge, hooks);
  if (saga.state !== "COMMITTED" || !saga.activationReadback) {
    throw new Error(
      `Palmier dual commit stopped at ${saga.state}: `
      + (saga.failureReason ?? "reconciliation is required"),
    );
  }
  if (!proof) {
    throw new Error("Palmier dual commit completed without candidate proof");
  }
  return {
    status: "candidate-promoted",
    approvedHead: {
      projectId: proof.projectId,
      timelineId: saga.reservedPalmierCandidateId,
      fingerprint: saga.reservedPalmierTimelineHash,
    },
    localRevisionHash: saga.reservedLocalChildHash,
    sagaState: "COMMITTED",
  };
}
