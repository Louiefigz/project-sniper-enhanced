import type { ProjectRevisionV2 } from
  "@/lib/producer/contracts/project-revision";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import {
  writeAuthorityObjectSync,
  type ProducerAuthorityPaths,
} from "./producer-authority-files";
import type { AutoEditGenesisFacts } from
  "./producer-auto-edit-genesis-facts";

const RENDERABLE_PARENT_STATES = new Set([
  "PICTURE_LOCKED",
  "TREATMENT_DRAFT",
  "TREATMENT_REVIEW",
  "READY_TO_FINALIZE",
]);

export interface ProducerAuthorityMigrationBlockerV1 {
  schemaVersion: 1;
  code: "PRODUCER_AUTHORITY_MIGRATION_REQUIRED";
  changedFacts: string[];
  observedSourceSnapshotSetHash: string;
  expectedSourceSnapshotSetHash: string;
  recognizedLegacySourceSnapshotSetHash: string;
}

export class ProducerAuthorityMigrationRequiredError extends Error {
  readonly code = "PRODUCER_AUTHORITY_MIGRATION_REQUIRED";

  constructor(readonly blocker: ProducerAuthorityMigrationBlockerV1) {
    super(`producer authority migration required: ${
      blocker.changedFacts.join(", ")}`);
    this.name = "ProducerAuthorityMigrationRequiredError";
  }
}

function sameList(left: string[], right: string[]): boolean {
  return left.length === right.length
    && left.every((value, index) => value === right[index]);
}

function changedFacts(
  parent: ProjectRevisionV2,
  facts: AutoEditGenesisFacts,
): string[] {
  const checks: Array<[string, boolean]> = [
    ["manifest", parent.manifestHash === facts.manifestHash],
    ["source set",
      parent.sourceSnapshotSetHash === facts.sourceSnapshotSetHash],
    ["transcript",
      parent.transcriptTimingHash === facts.transcriptTimingHash],
    ["timeline", parent.timelineMapHash === facts.timelineMapHash],
    ["canvas", parent.canvasProfileHash === facts.canvasProfileHash],
    ["destinations", sameList(
      parent.destinationProfileHashes, facts.destinationProfileHashes)],
    ["picture lock", parent.pictureLockHash === facts.pictureLockHash],
  ];
  return checks.filter(([, matches]) => !matches).map(([name]) => name);
}

function legacySourceHash(parent: ProjectRevisionV2): string {
  return canonicalJsonSha256({
    kind: "compatibility-source-binding-v1",
    manifestHash: parent.manifestHash,
    transcriptDigest: parent.transcriptTimingHash,
  });
}

function migrationBlocker(
  parent: ProjectRevisionV2,
  facts: AutoEditGenesisFacts,
  changed: string[],
): ProducerAuthorityMigrationRequiredError {
  return new ProducerAuthorityMigrationRequiredError({
    schemaVersion: 1,
    code: "PRODUCER_AUTHORITY_MIGRATION_REQUIRED",
    changedFacts: changed,
    observedSourceSnapshotSetHash: parent.sourceSnapshotSetHash,
    expectedSourceSnapshotSetHash: facts.sourceSnapshotSetHash,
    recognizedLegacySourceSnapshotSetHash: legacySourceHash(parent),
  });
}

function assertRenderable(parent: ProjectRevisionV2): void {
  if (!RENDERABLE_PARENT_STATES.has(parent.workflowState)) {
    throw new Error(
      `cannot append a rendered successor to ${parent.workflowState}`);
  }
}

/**
 * Admit only the historical synthetic source formula. Every other locked
 * mismatch remains a structured, machine-readable migration blocker.
 */
export function prepareLegacyCompatibilityAdoptionSync(
  paths: ProducerAuthorityPaths,
  parentRevisionHash: string,
  parent: ProjectRevisionV2,
  facts: AutoEditGenesisFacts,
): string | null {
  assertRenderable(parent);
  const changed = changedFacts(parent, facts);
  if (!changed.length) return null;
  const sourceOnly = changed.length === 1 && changed[0] === "source set";
  const recognized = parent.sourceSnapshotSetHash === legacySourceHash(parent)
    && parent.authoritativeSidecars.compatibilityLock
      === facts.pictureLockHash;
  if (!sourceOnly || !recognized) {
    if (changed.includes("source set")) {
      throw migrationBlocker(parent, facts, changed);
    }
    throw new Error(
      `rendered successor changes locked authority: ${changed.join(", ")}`);
  }
  return writeAuthorityObjectSync(paths.objects.receipts, {
    schemaVersion: 1,
    kind: "legacy-compatibility-shadow-source-adoption",
    parentRevisionHash,
    legacySourceSnapshotSetHash: parent.sourceSnapshotSetHash,
    admittedSourceSnapshotSetHash: facts.sourceSnapshotSetHash,
    sourceSetAdmissionReceipt:
      facts.authoritativeSidecars.sourceSetAdmissionReceipt,
    manifestHash: facts.manifestHash,
    transcriptTimingHash: facts.transcriptTimingHash,
    pictureLockHash: facts.pictureLockHash,
  }).hash;
}
