import { createHash } from "node:crypto";
import { existsSync, lstatSync, readFileSync } from "node:fs";
import path from "node:path";
import { atomicWriteFileSync, atomicWriteJsonSync } from "@/lib/server/atomic-file";
import {
  SURGICAL_RECONCILIATION_CANDIDATE_FILE,
  SURGICAL_RECONCILIATION_FILE,
} from "@/lib/server/ask-editor-reconciliation";
export {
  assertNoPromotionReconciliation,
  PromotionReconciliationError,
  SURGICAL_RECONCILIATION_CANDIDATE_FILE,
  SURGICAL_RECONCILIATION_FILE,
} from "@/lib/server/ask-editor-reconciliation";

export interface PromotionRecoveryInput {
  dir: string;
  planPath: string;
  authorityPlanPath?: string;
  originalPlanText: string;
  parentPlanHash: string;
}

export interface PromotedPlanSnapshot {
  authorityPath: string;
  parentBytes: Buffer;
  parentHash: string;
  childBytes: Buffer;
  childHash: string;
}

export interface ReviewedCandidateSnapshot {
  bytes: Buffer;
  hash: string;
}

interface AuthorityObservation {
  bytes: Buffer | null;
  exists: boolean;
  failure?: unknown;
}

const promotionRecoveryOutcomes = new WeakMap<object, "restored" | "reconciliation">();

function sha256(value: string | Buffer): string {
  return createHash("sha256").update(value).digest("hex");
}

function assertExactParent(input: PromotionRecoveryInput, authorityPath: string): void {
  if (sha256(input.originalPlanText) !== input.parentPlanHash) {
    throw new Error("captured Ask Editor parent bytes do not match their authority hash");
  }
  const observation = observeAuthority(authorityPath);
  if (observation.failure || !observation.bytes) {
    throw new Error("canonical edit_plan.json is not one safe regular authority file");
  }
  const current = observation.bytes;
  if (sha256(current) === input.parentPlanHash
      && current.equals(Buffer.from(input.originalPlanText))) return;
  throw new Error(
    "canonical edit_plan.json changed during Ask Editor candidate work; "
      + "refusing exact-parent promotion",
  );
}

export function promoteCandidateUnderLease(
  input: PromotionRecoveryInput,
  reviewed: ReviewedCandidateSnapshot,
  capture: (snapshot: PromotedPlanSnapshot) => void,
): PromotedPlanSnapshot {
  const authorityPath = input.authorityPlanPath ?? input.planPath;
  const parentBytes = Buffer.from(input.originalPlanText);
  if (authorityPath !== input.planPath) assertExactParent(input, authorityPath);
  else if (sha256(parentBytes) !== input.parentPlanHash) {
    throw new Error("captured Ask Editor parent bytes do not match their authority hash");
  }
  const childBytes = readFileSync(input.planPath);
  if (reviewed.hash !== sha256(reviewed.bytes)
      || sha256(childBytes) !== reviewed.hash
      || !childBytes.equals(reviewed.bytes)) {
    throw new Error("Ask Editor candidate changed after deterministic review");
  }
  const snapshot = {
    authorityPath,
    parentBytes,
    parentHash: input.parentPlanHash,
    childBytes: reviewed.bytes,
    childHash: reviewed.hash,
  };
  capture(snapshot);
  if (authorityPath !== input.planPath) {
    atomicWriteFileSync(authorityPath, reviewed.bytes);
  }
  return snapshot;
}

function reconciliationPath(dir: string): string {
  return path.join(dir, SURGICAL_RECONCILIATION_FILE);
}

function failureMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function candidateEvidencePath(dir: string): string {
  return path.join(dir, SURGICAL_RECONCILIATION_CANDIDATE_FILE);
}

function preserveCandidateEvidence(
  input: PromotionRecoveryInput,
  promoted: PromotedPlanSnapshot,
): string {
  const destination = candidateEvidencePath(input.dir);
  if (existsSync(destination)) {
    const prior = readFileSync(destination);
    if (sha256(prior) === promoted.childHash && prior.equals(promoted.childBytes)) {
      return destination;
    }
    throw new Error("existing Ask Editor reconciliation candidate conflicts");
  }
  atomicWriteFileSync(destination, promoted.childBytes);
  const retained = readFileSync(destination);
  if (sha256(retained) !== promoted.childHash || !retained.equals(promoted.childBytes)) {
    throw new Error("Ask Editor reconciliation candidate failed readback");
  }
  return destination;
}

function observeAuthority(authorityPath: string): AuthorityObservation {
  const exists = existsSync(authorityPath);
  if (!exists) return { bytes: null, exists: false };
  try {
    const before = lstatSync(authorityPath);
    if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1) {
      throw new Error("canonical edit_plan.json is not one regular non-symlink file");
    }
    const bytes = readFileSync(authorityPath);
    const after = lstatSync(authorityPath);
    if (!after.isFile() || after.isSymbolicLink() || after.nlink !== 1
        || before.dev !== after.dev || before.ino !== after.ino) {
      throw new Error("canonical edit_plan.json changed identity while observed");
    }
    return { bytes, exists: true };
  } catch (failure) {
    return { bytes: null, exists: true, failure };
  }
}

/** Re-observe the exact safe child after any asynchronous promotion boundary. */
export function assertPromotedCandidateCurrent(
  promoted: PromotedPlanSnapshot,
): void {
  const observation = observeAuthority(promoted.authorityPath);
  const current = observation.bytes;
  if (observation.failure || !current
      || sha256(current) !== promoted.childHash
      || !current.equals(promoted.childBytes)) {
    throw new Error("canonical edit_plan.json changed after Ask Editor promotion");
  }
}

function writeReconciliationEvidence(
  input: PromotionRecoveryInput,
  promoted: PromotedPlanSnapshot,
  observation: AuthorityObservation,
  trigger: unknown,
): void {
  const retainedPath = preserveCandidateEvidence(input, promoted);
  atomicWriteJsonSync(reconciliationPath(input.dir), {
    schemaVersion: 1,
    kind: "ask-editor-promotion-reconciliation",
    status: "manual-reconciliation-required",
    parentPlanHash: promoted.parentHash,
    promotedChildHash: promoted.childHash,
    observedAuthorityHash: observation.bytes ? sha256(observation.bytes) : null,
    observedAuthorityExists: observation.exists,
    observedAuthorityReadable: !observation.failure,
    observedAuthorityError: observation.failure
      ? failureMessage(observation.failure) : null,
    retainedCandidatePath: retainedPath,
    triggeringFailure: failureMessage(trigger),
  });
}

function exactObservation(
  observation: AuthorityObservation,
  hash: string,
  bytes: Buffer,
): boolean {
  return observation.bytes !== null && sha256(observation.bytes) === hash
    && observation.bytes.equals(bytes);
}

function restoreExactChild(
  input: PromotionRecoveryInput,
  promoted: PromotedPlanSnapshot,
  trigger: unknown,
): void {
  try {
    atomicWriteFileSync(promoted.authorityPath, promoted.parentBytes);
  } catch (failure) {
    const restored = observeAuthority(promoted.authorityPath);
    if (exactObservation(restored, promoted.parentHash, promoted.parentBytes)) {
      promotionRecoveryOutcomes.set(input, "restored");
      return;
    }
    return refuseUnsafeRestore(input, promoted, restored, failure);
  }
  const restored = observeAuthority(promoted.authorityPath);
  if (exactObservation(restored, promoted.parentHash, promoted.parentBytes)) {
    promotionRecoveryOutcomes.set(input, "restored");
    return;
  }
  return refuseUnsafeRestore(input, promoted, restored, trigger);
}

export function restorePromotedCandidate(
  input: PromotionRecoveryInput,
  promoted: PromotedPlanSnapshot,
  trigger: unknown,
): void {
  const observation = observeAuthority(promoted.authorityPath);
  if (observation.failure) {
    return refuseUnsafeRestore(input, promoted, observation, trigger);
  }
  if (exactObservation(observation, promoted.parentHash, promoted.parentBytes)) {
    promotionRecoveryOutcomes.set(input, "restored");
    return;
  }
  if (exactObservation(observation, promoted.childHash, promoted.childBytes)) {
    return restoreExactChild(input, promoted, trigger);
  }
  return refuseUnsafeRestore(input, promoted, observation, trigger);
}

function refuseUnsafeRestore(
  input: PromotionRecoveryInput,
  promoted: PromotedPlanSnapshot,
  observation: AuthorityObservation,
  trigger: unknown,
): never {
  promotionRecoveryOutcomes.set(input, "reconciliation");
  let evidenceFailure = "";
  try {
    writeReconciliationEvidence(input, promoted, observation, trigger);
  } catch (error) {
    evidenceFailure = ` Reconciliation evidence could not be written: ${failureMessage(error)}`;
  }
  throw new Error(
    "Ask Editor post-promotion rollback found a different canonical plan; "
      + "manual reconciliation required, and no authority bytes were overwritten."
      + ` Candidate retained at ${input.planPath}.`
      + evidenceFailure,
  );
}

export function isPromotionRecoverySettled(input: object): boolean {
  return promotionRecoveryOutcomes.has(input);
}

export function shouldPreservePromotionCandidate(input: object): boolean {
  return promotionRecoveryOutcomes.get(input) === "reconciliation";
}

/** A foreign post-promotion state needs deliberate operator reconciliation. */
