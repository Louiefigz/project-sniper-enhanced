import { lstatSync, readFileSync } from "node:fs";
import path from "node:path";
import { parsePalmierCommitSagaV1,
  type PalmierActivationReadbackV1, type PalmierCommitSagaV1,
} from "@/lib/producer/contracts/palmier-commit-saga";
import type { CommitIntentStateV1 } from
  "@/lib/producer/contracts/commit-intent";
import { atomicCreateJsonSync, atomicWriteJsonSync } from "./atomic-file";
import { authorityKey,
  producerAuthorityPaths } from "./producer-authority-files";
import { exactPalmierReadback, unreadableObservation,
  type PalmierObservedHeadV1 } from "./producer-palmier-saga-readback";
export type { PalmierObservedHeadV1 } from "./producer-palmier-saga-readback";
export interface PalmierSagaAdapterV1 {
  proveCandidates: (saga: PalmierCommitSagaV1) => boolean;
  observePalmier: () => PalmierObservedHeadV1;
  activatePalmier: (expectedParentId: string, candidateId: string) => void;
  observeLocal: () => string;
  commitLocal: (expectedParentHash: string, childHash: string) => void;
}
export type PalmierSagaBoundaryV1 =
  | "after-candidates-proved"
  | "after-palmier-activating"
  | "after-palmier-effect"
  | "after-palmier-active"
  | "after-local-committing"
  | "after-local-effect"
  | "after-committed";
export interface PalmierSagaHooksV1 {
  after?: (boundary: PalmierSagaBoundaryV1) => void;
}
function readSaga(filePath: string): PalmierCommitSagaV1 {
  const info = lstatSync(filePath);
  if (!info.isFile() || info.isSymbolicLink() || info.nlink !== 1) {
    throw new Error("Palmier saga must be one regular non-symlink file");
  }
  return parsePalmierCommitSagaV1(
    JSON.parse(readFileSync(filePath, "utf8")),
  );
}
function transition(
  filePath: string,
  saga: PalmierCommitSagaV1,
  state: CommitIntentStateV1,
  options: {
    readback?: PalmierActivationReadbackV1 | null;
    failureReason?: string;
  } = {},
): PalmierCommitSagaV1 {
  const stable = { ...saga };
  delete stable.failureReason;
  const next = parsePalmierCommitSagaV1({
    ...stable,
    state,
    activationReadback: options.readback === undefined
      ? saga.activationReadback : options.readback,
    updatedAt: new Date().toISOString(),
    ...(options.failureReason ? { failureReason: options.failureReason } : {}),
  });
  atomicWriteJsonSync(filePath, next);
  return next;
}
function reconcile(
  filePath: string,
  saga: PalmierCommitSagaV1,
  reason: string,
): PalmierCommitSagaV1 {
  return transition(filePath, saga, "RECONCILIATION_REQUIRED", {
    failureReason: reason,
  });
}
function proveCandidates(
  filePath: string,
  saga: PalmierCommitSagaV1,
  adapter: PalmierSagaAdapterV1,
  hooks: PalmierSagaHooksV1,
): PalmierCommitSagaV1 {
  let proved: boolean;
  try {
    proved = adapter.proveCandidates(saga);
  } catch (error) {
    return reconcile(filePath, saga, unreadableObservation(
      "reserved candidate proof", error));
  }
  if (!proved) {
    return transition(filePath, saga, "ABORTED", {
      readback: null,
      failureReason: "reserved local or Palmier candidate proof failed",
    });
  }
  const next = transition(filePath, saga, "CANDIDATES_PROVED");
  hooks.after?.("after-candidates-proved");
  return next;
}
function activatePalmier(
  filePath: string,
  saga: PalmierCommitSagaV1,
  adapter: PalmierSagaAdapterV1,
  hooks: PalmierSagaHooksV1,
): PalmierCommitSagaV1 {
  let observed: PalmierObservedHeadV1;
  try {
    observed = adapter.observePalmier();
  } catch (error) {
    return reconcile(
      filePath, saga, unreadableObservation("Palmier head", error));
  }
  let readback = exactPalmierReadback(saga, observed);
  if (!readback && observed.headId === saga.expectedPalmierParentId) {
    const activating = transition(filePath, saga, "PALMIER_ACTIVATING");
    hooks.after?.("after-palmier-activating");
    adapter.activatePalmier(
      activating.expectedPalmierParentId,
      activating.reservedPalmierCandidateId,
    );
    hooks.after?.("after-palmier-effect");
    try {
      observed = adapter.observePalmier();
    } catch (error) {
      return reconcile(filePath, activating, unreadableObservation(
        "Palmier activation readback", error));
    }
    readback = exactPalmierReadback(activating, observed);
  }
  if (!readback) {
    return reconcile(
      filePath, saga, "Palmier head is foreign, unreadable, or partial");
  }
  const active = transition(filePath, saga, "PALMIER_ACTIVE", { readback });
  hooks.after?.("after-palmier-active");
  return active;
}
function assertPalmierStillSelected(
  saga: PalmierCommitSagaV1,
  adapter: PalmierSagaAdapterV1,
): boolean {
  return exactPalmierReadback(saga, adapter.observePalmier()) !== null;
}
function finishLocalCommit(
  filePath: string,
  saga: PalmierCommitSagaV1,
  adapter: PalmierSagaAdapterV1,
  hooks: PalmierSagaHooksV1,
): PalmierCommitSagaV1 {
  let selected: boolean;
  try {
    selected = assertPalmierStillSelected(saga, adapter);
  } catch (error) {
    const reason = unreadableObservation("post-commit Palmier head", error);
    return reconcile(filePath, saga, reason);
  }
  if (!selected) return reconcile(
    filePath, saga, "Palmier changed during local commit");
  const committed = transition(filePath, saga, "COMMITTED");
  hooks.after?.("after-committed");
  return committed;
}
function commitLocal(
  filePath: string,
  saga: PalmierCommitSagaV1,
  adapter: PalmierSagaAdapterV1,
  hooks: PalmierSagaHooksV1,
): PalmierCommitSagaV1 {
  let selected: boolean;
  try {
    selected = assertPalmierStillSelected(saga, adapter);
  } catch (error) {
    return reconcile(
      filePath, saga, unreadableObservation("Palmier head", error));
  }
  if (!selected) {
    return reconcile(filePath, saga, "Palmier changed before local commit");
  }
  let current = saga;
  if (current.state !== "LOCAL_COMMITTING") {
    current = transition(filePath, current, "LOCAL_COMMITTING");
    hooks.after?.("after-local-committing");
  }
  let local: string;
  try {
    local = adapter.observeLocal();
  } catch (error) {
    return reconcile(
      filePath, current, unreadableObservation("local head", error));
  }
  if (local === current.expectedLocalParentHash) {
    adapter.commitLocal(
      current.expectedLocalParentHash, current.reservedLocalChildHash);
    hooks.after?.("after-local-effect");
    try {
      local = adapter.observeLocal();
    } catch (error) {
      return reconcile(filePath, current, unreadableObservation(
        "local commit readback", error));
    }
  }
  if (local !== current.reservedLocalChildHash) {
    return reconcile(filePath, current, "local head is foreign or partial");
  }
  return finishLocalCommit(filePath, current, adapter, hooks);
}
function auditCommitted(
  filePath: string,
  saga: PalmierCommitSagaV1,
  adapter: PalmierSagaAdapterV1,
): PalmierCommitSagaV1 {
  let selected: boolean;
  let local: string;
  try {
    selected = assertPalmierStillSelected(saga, adapter);
    local = adapter.observeLocal();
  } catch (error) {
    return reconcile(filePath, saga, unreadableObservation(
      "committed dual-head readback", error));
  }
  if (!selected || local !== saga.reservedLocalChildHash) {
    return reconcile(filePath, saga, "committed dual heads no longer match");
  }
  return saga;
}
export function initializePalmierSagaSync(
  filePath: string,
  value: unknown,
): PalmierCommitSagaV1 {
  const saga = parsePalmierCommitSagaV1(value);
  if (saga.state !== "PREPARING") {
    throw new Error("new Palmier saga must start in PREPARING");
  }
  atomicCreateJsonSync(filePath, saga);
  return readSaga(filePath);
}
/** Recover from observed heads; no state infers that an external effect happened. */
export function recoverPalmierSagaSync(
  filePath: string,
  adapter: PalmierSagaAdapterV1,
  hooks: PalmierSagaHooksV1 = {},
): PalmierCommitSagaV1 {
  let saga = readSaga(filePath);
  const requiresReproof = ![
    "PREPARING", "ABORTED", "RECONCILIATION_REQUIRED",
  ].includes(saga.state);
  if (requiresReproof) {
    let proved: boolean;
    try {
      proved = adapter.proveCandidates(saga);
    } catch (error) {
      return reconcile(filePath, saga, unreadableObservation(
        "reserved candidate re-proof", error));
    }
    if (!proved) {
      return reconcile(filePath, saga, "reserved candidate re-proof failed");
    }
  }
  for (let step = 0; step < 8; step += 1) {
    if (saga.state === "PREPARING") {
      saga = proveCandidates(filePath, saga, adapter, hooks);
    } else if (["CANDIDATES_PROVED", "PALMIER_ACTIVATING"]
      .includes(saga.state)) {
      saga = activatePalmier(filePath, saga, adapter, hooks);
    } else if (["PALMIER_ACTIVE", "LOCAL_COMMITTING"].includes(saga.state)) {
      saga = commitLocal(filePath, saga, adapter, hooks);
    } else if (saga.state === "COMMITTED") {
      return auditCommitted(filePath, saga, adapter);
    } else {
      return saga;
    }
  }
  return reconcile(filePath, saga, "Palmier saga exceeded transition bound");
}
function producerSagaPath(
  producerDir: string,
  idempotencyKey: string,
): string {
  const fileName = `${authorityKey(idempotencyKey)}.json`;
  return path.join(producerAuthorityPaths(producerDir).sagas, fileName);
}
/** Create one durable saga inside the producer revision authority. */
export function initializeProducerPalmierSagaSync(
  producerDir: string,
  value: unknown,
): { filePath: string; saga: PalmierCommitSagaV1 } {
  const parsed = parsePalmierCommitSagaV1(value);
  const filePath = producerSagaPath(producerDir, parsed.idempotencyKey);
  return { filePath, saga: initializePalmierSagaSync(filePath, parsed) };
}
/** Recover a named durable saga without accepting a caller-selected path. */
export function recoverProducerPalmierSagaSync(
  producerDir: string,
  idempotencyKey: string,
  adapter: PalmierSagaAdapterV1,
  hooks: PalmierSagaHooksV1 = {},
): PalmierCommitSagaV1 {
  const filePath = producerSagaPath(producerDir, idempotencyKey);
  const saga = readSaga(filePath);
  if (saga.idempotencyKey !== idempotencyKey) {
    throw new Error("Palmier saga idempotency identity does not match its path");
  }
  return recoverPalmierSagaSync(filePath, adapter, hooks);
}
