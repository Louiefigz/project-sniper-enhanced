import { existsSync } from "node:fs";
import path from "node:path";
import { atomicWriteJsonSync } from "./atomic-file";
import {
  copyNodeDurable,
  ensureDurableDirectory,
  nodeState,
  removeNodeDurable,
  sameNodeState,
} from "./candidate-promotion-fs";
import {
  promotionTopologyHash,
  type CandidatePromotionIntentV1,
  type PromotionMissingSourcePolicy,
  type PromotionIntentEntry,
  type PromotionTransfer,
  type PromotionTopology,
} from "./candidate-promotion-intent";
import {
  recoverCandidatePromotionSync,
  type PromotionRecoveryHooks,
  type PromotionRecoveryOutcome,
} from "./candidate-promotion-recovery";

const EMPTY_DIRECTORY_SHA256 =
  "e3b0c44298fc1c149afbf4c8996fb924"
  + "27ae41e4649b934ca495991b7852b855";

export type PromotionCrashBoundary =
  | "after-intent"
  | "after-backups"
  | "after-transfers"
  | "after-commit"
  | "after-committed"
  | "after-rollback-marked"
  | "after-move-cleanup"
  | "after-recovery-directory-removed"
  | "after-intent-removed";

export interface RecoverablePromotionInput extends PromotionTopology {
  commit: () => void;
  rollbackAuthority?: () => void;
  acceptCommitReady?: () => boolean;
  confirmCommitted?: () => void;
  allowMutableRollback?: PromotionRecoveryHooks["allowMutableRollback"];
  afterBoundary?: (boundary: PromotionCrashBoundary) => void;
}

function normalizedTopology(
  input: RecoverablePromotionInput,
): PromotionTopology {
  return {
    scopeRoot: path.resolve(input.scopeRoot),
    recoveryRoot: path.resolve(input.recoveryRoot),
    reconciliationPath: path.resolve(input.reconciliationPath),
    transactionId: input.transactionId,
    moves: input.moves.map((row) => ({
      source: path.resolve(row.source),
      destination: path.resolve(row.destination),
      missingSource: row.missingSource ?? "reject",
    })),
    copies: input.copies.map((row) => ({
      source: path.resolve(row.source),
      destination: path.resolve(row.destination),
      missingSource: row.missingSource ?? "reject",
    })),
    mutablePaths: input.mutablePaths.map((row) => path.resolve(row)),
  };
}

interface PromotionEntrySeed {
  kind: "move" | "copy" | "mutable";
  source: string | null;
  missingSource: PromotionMissingSourcePolicy | null;
  destination: string;
}

function entry(
  seed: PromotionEntrySeed,
  directory: string,
  index: number,
): PromotionIntentEntry {
  const oldState = nodeState(seed.destination);
  const sourceState = seed.source === null ? null : nodeState(seed.source);
  if (sourceState?.kind === "missing" && seed.missingSource === "reject") {
    throw new Error(
      `candidate promotion required source is missing: ${seed.source}`);
  }
  const temporary = path.join(
    path.dirname(seed.destination),
    `.promotion-${path.basename(directory)}-${index}.tmp`,
  );
  if (nodeState(temporary).kind !== "missing") {
    throw new Error(
      `candidate promotion temporary path is foreign: ${temporary}`);
  }
  return {
    ...seed,
    backup: oldState.kind === "missing"
      ? null : path.join(directory, `prior-${index}`),
    temporary,
    sourceState,
    oldState,
    committedState: null,
  };
}

function intentEntries(
  topology: PromotionTopology,
  directory: string,
): PromotionIntentEntry[] {
  const rows = [
    ...topology.moves.map((row) => ({
      kind: "move" as const, ...row,
      missingSource: row.missingSource ?? "reject",
    })),
    ...topology.copies.map((row) => ({
      kind: "copy" as const, ...row,
      missingSource: row.missingSource ?? "reject",
    })),
    ...topology.mutablePaths.map((destination) => ({
      kind: "mutable" as const, source: null,
      missingSource: null, destination,
    })),
  ];
  return rows.map((row, index) => entry(row, directory, index));
}

function createIntent(topology: PromotionTopology): CandidatePromotionIntentV1 {
  if (!/^[0-9a-f]{64}$/u.test(topology.transactionId)) {
    throw new Error("candidate promotion transactionId must be one SHA-256");
  }
  const directory = path.join(
    topology.recoveryRoot, `promotion-${topology.transactionId}`);
  if (existsSync(directory)) {
    const state = nodeState(directory);
    if (state.kind !== "directory"
        || state.sha256 !== EMPTY_DIRECTORY_SHA256) {
      throw new Error(
        "candidate promotion has foreign unowned recovery state");
    }
  }
  const entries = intentEntries(topology, directory);
  ensureDurableDirectory(topology.recoveryRoot, topology.scopeRoot);
  if (existsSync(directory)) removeNodeDurable(directory);
  return {
    schemaVersion: 1,
    kind: "candidate-promotion-transaction",
    transactionId: topology.transactionId,
    topologyHash: promotionTopologyHash(topology),
    phase: "prepared",
    recoveryDirectory: directory,
    entries,
    failures: [],
  };
}

function writeIntent(
  topology: PromotionTopology,
  intent: CandidatePromotionIntentV1,
): void {
  atomicWriteJsonSync(topology.reconciliationPath, intent);
}

function createBackups(intent: CandidatePromotionIntentV1): void {
  for (const entry of intent.entries) {
    if (!entry.backup) continue;
    copyNodeDurable(entry.destination, entry.backup);
    if (!sameNodeState(nodeState(entry.backup), entry.oldState)) {
      throw new Error(`candidate promotion backup changed: ${entry.destination}`);
    }
  }
}

function installTransfers(intent: CandidatePromotionIntentV1): void {
  for (const entry of intent.entries) {
    if (entry.kind === "mutable") continue;
    if (nodeState(entry.temporary).kind !== "missing") {
      throw new Error(
        `candidate promotion temporary path became foreign: ${entry.temporary}`);
    }
    if (entry.sourceState?.kind === "missing"
        && entry.missingSource === "delete-destination") {
      removeNodeDurable(entry.destination);
      continue;
    }
    if (!entry.sourceState || entry.sourceState.kind === "missing") {
      throw new Error(
        `candidate promotion required source is missing: ${entry.source}`);
    }
    copyNodeDurable(entry.source!, entry.destination, entry.temporary);
    if (!sameNodeState(nodeState(entry.destination), entry.sourceState)) {
      throw new Error(
        `candidate promotion transfer changed: ${entry.destination}`);
    }
  }
}

function committedIntent(
  intent: CandidatePromotionIntentV1,
): CandidatePromotionIntentV1 {
  return {
    ...intent,
    phase: "committed",
    entries: intent.entries.map((entry) => ({
      ...entry,
      committedState: nodeState(entry.destination),
    })),
  };
}

function recoveryHooks(
  input: RecoverablePromotionInput,
  immediate = false,
): PromotionRecoveryHooks {
  return {
    acceptCommitReady: input.acceptCommitReady,
    confirmCommitted: input.confirmCommitted,
    rollbackAuthority: input.rollbackAuthority,
    allowMutableRollback: immediate
      ? () => true : input.allowMutableRollback,
    afterOldRestored: () => input.afterBoundary?.("after-rollback-marked"),
    afterMoveSourcesCleaned: () =>
      input.afterBoundary?.("after-move-cleanup"),
    afterRecoveryDirectoryRemoved: () =>
      input.afterBoundary?.("after-recovery-directory-removed"),
    afterIntentRemoved: () =>
      input.afterBoundary?.("after-intent-removed"),
  };
}

function finishCommitted(
  topology: PromotionTopology,
  input: RecoverablePromotionInput,
): void {
  const outcome = recoverCandidatePromotionSync(
    topology, recoveryHooks(input));
  if (outcome !== "recovered-new") {
    throw new Error("committed candidate promotion did not reopen exact new state");
  }
}

function executePromotion(
  topology: PromotionTopology,
  input: RecoverablePromotionInput,
): void {
  let intent = createIntent(topology);
  writeIntent(topology, intent);
  input.afterBoundary?.("after-intent");
  ensureDurableDirectory(intent.recoveryDirectory, topology.scopeRoot);
  createBackups(intent);
  intent = { ...intent, phase: "backed-up" };
  writeIntent(topology, intent);
  input.afterBoundary?.("after-backups");
  installTransfers(intent);
  intent = { ...intent, phase: "commit-ready" };
  writeIntent(topology, intent);
  input.afterBoundary?.("after-transfers");
  input.commit();
  input.afterBoundary?.("after-commit");
  intent = committedIntent(intent);
  writeIntent(topology, intent);
  input.afterBoundary?.("after-committed");
  finishCommitted(topology, input);
}

/** Recover first, then publish old-or-new without an unblocked mixed state. */
export function runRecoverablePromotionSync(
  input: RecoverablePromotionInput,
): PromotionRecoveryOutcome {
  const topology = normalizedTopology(input);
  const recovered = recoverCandidatePromotionSync(
    topology, recoveryHooks(input));
  if (recovered === "recovered-new") return recovered;
  try {
    executePromotion(topology, input);
    return "recovered-new";
  } catch (trigger) {
    if (!existsSync(topology.reconciliationPath)) throw trigger;
    try {
      recoverCandidatePromotionSync(
        topology, recoveryHooks(input, true));
    } catch (rollback) {
      throw new Error("candidate promotion requires reconciliation", {
        cause: new AggregateError([trigger, rollback]),
      });
    }
    throw trigger;
  }
}

export { recoverCandidatePromotionSync };
export type {
  PromotionRecoveryHooks,
  PromotionRecoveryOutcome,
  PromotionTransfer,
  PromotionTopology,
};
