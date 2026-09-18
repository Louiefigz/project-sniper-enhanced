import { existsSync, rmdirSync } from "node:fs";
import path from "node:path";
import { atomicWriteJsonSync } from "./atomic-file";
import {
  nodeState,
  removeNodeDurable,
  restoreNodeDurable,
  sameNodeState,
  syncDirectory,
  type PromotionDurabilityHooks,
  type PromotionNodeState,
} from "./candidate-promotion-fs";
import {
  type CandidatePromotionIntentV1,
  type PromotionIntentEntry,
  type PromotionTopology,
} from "./candidate-promotion-intent";
import {
  assertPromotionTopology,
  blockPromotionReconciliation,
  publishPromotionTerminal,
  readPromotionIntent,
  readPromotionTerminal,
} from "./candidate-promotion-recovery-intent";

export interface PromotionRecoveryHooks {
  acceptCommitReady?: () => boolean;
  confirmCommitted?: () => void;
  rollbackAuthority?: () => void;
  allowMutableRollback?: (
    destination: string,
    current: PromotionNodeState,
    prior: PromotionNodeState,
  ) => boolean;
  afterOldRestored?: () => void;
  afterMoveSourcesCleaned?: () => void;
  afterRecoveryDirectoryRemoved?: () => void;
  afterIntentRemoved?: () => void;
  durabilityHooks?: PromotionDurabilityHooks;
}

export type PromotionRecoveryOutcome =
  "none" | "recovered-old" | "recovered-new";

function backupExact(entry: PromotionIntentEntry): boolean {
  if (entry.oldState.kind === "missing") return entry.backup === null;
  return entry.backup !== null
    && sameNodeState(nodeState(entry.backup), entry.oldState);
}

function transferCurrentAllowed(entry: PromotionIntentEntry): boolean {
  const current = nodeState(entry.destination);
  if (sameNodeState(current, entry.oldState)
      || current.kind === "missing") return true;
  return entry.sourceState !== null
    && sameNodeState(current, entry.sourceState);
}

function assertRollbackSafe(
  intent: CandidatePromotionIntentV1,
  hooks: PromotionRecoveryHooks,
): void {
  for (const entry of intent.entries) {
    if (!backupExact(entry)) {
      throw new Error(`promotion backup is torn: ${entry.destination}`);
    }
    if (entry.kind !== "mutable" && !transferCurrentAllowed(entry)) {
      throw new Error(`promotion destination is foreign: ${entry.destination}`);
    }
    if (entry.kind === "mutable") {
      const current = nodeState(entry.destination);
      const allowed = sameNodeState(current, entry.oldState)
        || hooks.allowMutableRollback?.(
          entry.destination, current, entry.oldState) === true;
      if (!allowed) {
        throw new Error(
          `promotion mutable authority is foreign: ${entry.destination}`);
      }
    }
  }
}

function restoreOld(
  intent: CandidatePromotionIntentV1,
  hooks: PromotionRecoveryHooks,
): void {
  assertRollbackSafe(intent, hooks);
  for (const entry of [...intent.entries].reverse()) {
    restoreNodeDurable(
      entry.backup, entry.destination, entry.oldState, entry.temporary);
  }
  hooks.rollbackAuthority?.();
  for (const entry of intent.entries) {
    if (!sameNodeState(nodeState(entry.destination), entry.oldState)) {
      throw new Error(`promotion old state did not reopen: ${entry.destination}`);
    }
    if (entry.sourceState && !sameNodeState(
      nodeState(entry.source!), entry.sourceState)) {
      throw new Error(`promotion source changed during rollback: ${entry.source}`);
    }
  }
}

function transfersAreIntended(intent: CandidatePromotionIntentV1): boolean {
  return intent.entries.every((entry) => entry.kind === "mutable"
    || (entry.sourceState !== null
      && sameNodeState(nodeState(entry.destination), entry.sourceState)));
}

function committedStateExact(intent: CandidatePromotionIntentV1): boolean {
  return intent.entries.every((entry) => entry.committedState !== null
    && sameNodeState(nodeState(entry.destination), entry.committedState));
}

function cleanupMoveSources(intent: CandidatePromotionIntentV1): void {
  for (const entry of intent.entries) {
    if (entry.kind !== "move" || !entry.sourceState) continue;
    const current = nodeState(entry.source!);
    if (current.kind === "missing") continue;
    if (!sameNodeState(current, entry.sourceState)) {
      throw new Error(`promotion move source is foreign: ${entry.source}`);
    }
    removeNodeDurable(entry.source!);
  }
}

function cleanup(
  topology: PromotionTopology,
  intent: CandidatePromotionIntentV1,
  hooks: PromotionRecoveryHooks,
): void {
  removeNodeDurable(intent.recoveryDirectory);
  hooks.afterRecoveryDirectoryRemoved?.();
  removeNodeDurable(topology.reconciliationPath);
  hooks.afterIntentRemoved?.();
  try {
    rmdirSync(topology.recoveryRoot);
    syncDirectory(path.dirname(topology.recoveryRoot));
  } catch (error) {
    if (!["ENOENT", "ENOTEMPTY"].includes(
      (error as NodeJS.ErrnoException).code ?? "")) throw error;
  }
}

function recoverCommitted(
  topology: PromotionTopology,
  intent: CandidatePromotionIntentV1,
  hooks: PromotionRecoveryHooks,
): PromotionRecoveryOutcome {
  if (!committedStateExact(intent)) {
    return blockPromotionReconciliation(
      topology, intent, "committed promotion state is torn or foreign");
  }
  hooks.confirmCommitted?.();
  cleanupMoveSources(intent);
  hooks.afterMoveSourcesCleaned?.();
  publishPromotionTerminal(topology, intent, hooks.durabilityHooks);
  cleanup(topology, intent, hooks);
  return "recovered-new";
}

function recoverTerminal(
  topology: PromotionTopology,
  intent: CandidatePromotionIntentV1,
  hooks: PromotionRecoveryHooks,
): PromotionRecoveryOutcome {
  try {
    if (!committedStateExact(intent)) {
      return blockPromotionReconciliation(
        topology, intent, "terminal promotion state is torn or foreign");
    }
    publishPromotionTerminal(topology, intent, hooks.durabilityHooks);
    hooks.confirmCommitted?.();
    cleanupMoveSources(intent);
    return "recovered-new";
  } catch (error) {
    return blockPromotionReconciliation(topology, intent, error);
  }
}

function recoverIncomplete(
  topology: PromotionTopology,
  intent: CandidatePromotionIntentV1,
  hooks: PromotionRecoveryHooks,
  forceRollback: boolean,
): PromotionRecoveryOutcome {
  const accept = !forceRollback && intent.phase === "commit-ready"
    && hooks.acceptCommitReady?.() === true;
  if (accept) {
    if (!transfersAreIntended(intent)) {
      return blockPromotionReconciliation(
        topology, intent, "accepted child has foreign promoted transfers");
    }
    const committed = {
      ...intent,
      phase: "committed" as const,
      entries: intent.entries.map((entry) => ({
        ...entry,
        committedState: nodeState(entry.destination),
      })),
    };
    atomicWriteJsonSync(topology.reconciliationPath, committed);
    return recoverCommitted(topology, committed, hooks);
  }
  restoreOld(intent, hooks);
  const restored = {
    ...intent,
    phase: "rolled-back" as const,
  };
  atomicWriteJsonSync(topology.reconciliationPath, restored);
  hooks.afterOldRestored?.();
  cleanup(topology, restored, hooks);
  return "recovered-old";
}

function preparedStateExact(intent: CandidatePromotionIntentV1): boolean {
  return intent.entries.every((entry) => {
    const destinationExact = sameNodeState(
      nodeState(entry.destination), entry.oldState);
    const sourceExact = entry.sourceState === null
      || sameNodeState(nodeState(entry.source!), entry.sourceState);
    return destinationExact && sourceExact;
  });
}

function recoverPrepared(
  topology: PromotionTopology,
  intent: CandidatePromotionIntentV1,
  hooks: PromotionRecoveryHooks,
): PromotionRecoveryOutcome {
  if (!preparedStateExact(intent)) {
    return blockPromotionReconciliation(
      topology, intent, "prepared promotion state is torn or foreign");
  }
  cleanup(topology, intent, hooks);
  return "recovered-old";
}

function recoverRolledBack(
  topology: PromotionTopology,
  intent: CandidatePromotionIntentV1,
  hooks: PromotionRecoveryHooks,
): PromotionRecoveryOutcome {
  if (!preparedStateExact(intent)) {
    return blockPromotionReconciliation(
      topology, intent, "rolled-back promotion state is torn or foreign");
  }
  cleanup(topology, intent, hooks);
  return "recovered-old";
}

/** Reconcile one exact durable promotion intent; foreign evidence is retained. */
export function recoverCandidatePromotionSync(
  topology: PromotionTopology,
  hooks: PromotionRecoveryHooks = {},
  forceRollback = false,
): PromotionRecoveryOutcome {
  assertPromotionTopology(topology);
  if (!existsSync(topology.reconciliationPath)) {
    const terminal = readPromotionTerminal(topology);
    return terminal ? recoverTerminal(topology, terminal, hooks) : "none";
  }
  const intent = readPromotionIntent(topology);
  if (intent.phase === "reconciliation-required") {
    throw new Error(
      "candidate promotion is blocked by unresolved reconciliation state");
  }
  try {
    if (intent.phase === "committed") {
      return recoverCommitted(topology, intent, hooks);
    }
    if (intent.phase === "prepared") {
      return recoverPrepared(topology, intent, hooks);
    }
    if (intent.phase === "rolled-back") {
      return recoverRolledBack(topology, intent, hooks);
    }
    return recoverIncomplete(topology, intent, hooks, forceRollback);
  } catch (error) {
    return blockPromotionReconciliation(topology, intent, error);
  }
}
