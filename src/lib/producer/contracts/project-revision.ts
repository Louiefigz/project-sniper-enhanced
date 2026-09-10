import {
  enumValue,
  exactKeys,
  hashRecord,
  objectValue,
  sha256,
  uniqueStrings,
} from "./validation";

export const WORKFLOW_STATES = [
  "INGESTED",
  "CUT_DRAFT",
  "CUT_REVIEW",
  "PICTURE_LOCKED",
  "TREATMENT_DRAFT",
  "TREATMENT_REVIEW",
  "READY_TO_FINALIZE",
  "QC_APPROVED",
] as const;

export type WorkflowStateV1 = typeof WORKFLOW_STATES[number];

export interface ProjectRevisionV1 {
  schemaVersion: 1;
  parentRevisionHash: string | null;
  planContentHash: string;
  manifestHash: string;
  sourceSnapshotSetHash: string;
  transcriptTimingHash: string;
  timelineMapHash: string;
  canvasProfileHash: string;
  destinationProfileHashes: string[];
  pictureLockHash: string | null;
  workflowState: WorkflowStateV1;
  requestLedgerHash: string;
  renderGraphHash: string;
  projectionReceiptHash: string | null;
  authoritativeSidecars: Record<string, string>;
}

export interface ProjectRevisionV2 extends Omit<ProjectRevisionV1, "schemaVersion"> {
  schemaVersion: 2;
  planObjectHash: string;
}

export type ProjectRevision = ProjectRevisionV1 | ProjectRevisionV2;

export type ProjectRevisionDraftV1 = Omit<
  ProjectRevisionV1,
  "schemaVersion" | "parentRevisionHash" | "requestLedgerHash"
  | "renderGraphHash" | "projectionReceiptHash"
>;

export type ProjectRevisionDraftV2 = Omit<
  ProjectRevisionV2,
  "schemaVersion" | "parentRevisionHash" | "planObjectHash"
  | "requestLedgerHash" | "renderGraphHash" | "projectionReceiptHash"
>;

const V1_KEYS = [
  "schemaVersion", "parentRevisionHash", "planContentHash", "manifestHash",
  "sourceSnapshotSetHash", "transcriptTimingHash", "timelineMapHash",
  "canvasProfileHash", "destinationProfileHashes", "pictureLockHash",
  "workflowState", "requestLedgerHash", "renderGraphHash",
  "projectionReceiptHash", "authoritativeSidecars",
] as const;

const V2_KEYS = [...V1_KEYS, "planObjectHash"] as const;

function optionalHash(value: unknown, label: string): string | null {
  return value === null ? null : sha256(value, label);
}

function commonRevision(
  revision: Record<string, unknown>,
): Omit<ProjectRevisionV1, "schemaVersion"> {
  return {
    parentRevisionHash: optionalHash(
      revision.parentRevisionHash,
      "parentRevisionHash",
    ),
    planContentHash: sha256(revision.planContentHash, "planContentHash"),
    manifestHash: sha256(revision.manifestHash, "manifestHash"),
    sourceSnapshotSetHash: sha256(
      revision.sourceSnapshotSetHash,
      "sourceSnapshotSetHash",
    ),
    transcriptTimingHash: sha256(
      revision.transcriptTimingHash,
      "transcriptTimingHash",
    ),
    timelineMapHash: sha256(revision.timelineMapHash, "timelineMapHash"),
    canvasProfileHash: sha256(revision.canvasProfileHash, "canvasProfileHash"),
    destinationProfileHashes: uniqueStrings(
      revision.destinationProfileHashes,
      "destinationProfileHashes",
      sha256,
    ),
    pictureLockHash: optionalHash(revision.pictureLockHash, "pictureLockHash"),
    workflowState: enumValue(
      revision.workflowState,
      WORKFLOW_STATES,
      "workflowState",
    ),
    requestLedgerHash: sha256(revision.requestLedgerHash, "requestLedgerHash"),
    renderGraphHash: sha256(revision.renderGraphHash, "renderGraphHash"),
    projectionReceiptHash: optionalHash(
      revision.projectionReceiptHash,
      "projectionReceiptHash",
    ),
    authoritativeSidecars: hashRecord(
      revision.authoritativeSidecars,
      "authoritativeSidecars",
    ),
  };
}

export function parseProjectRevisionV1(value: unknown): ProjectRevisionV1 {
  const revision = objectValue(value, "ProjectRevisionV1");
  exactKeys(revision, V1_KEYS, V1_KEYS, "ProjectRevisionV1");
  if (revision.schemaVersion !== 1) {
    throw new Error("ProjectRevisionV1 version is unsupported");
  }
  return { schemaVersion: 1, ...commonRevision(revision) };
}

export function parseProjectRevisionV2(value: unknown): ProjectRevisionV2 {
  const revision = objectValue(value, "ProjectRevisionV2");
  exactKeys(revision, V2_KEYS, V2_KEYS, "ProjectRevisionV2");
  if (revision.schemaVersion !== 2) {
    throw new Error("ProjectRevisionV2 version is unsupported");
  }
  return {
    schemaVersion: 2,
    ...commonRevision(revision),
    planObjectHash: sha256(revision.planObjectHash, "planObjectHash"),
  };
}

/** Read legacy V1 authority, while all new revision-mode writes use V2. */
export function parseProjectRevision(value: unknown): ProjectRevision {
  const revision = objectValue(value, "ProjectRevision");
  if (revision.schemaVersion === 1) return parseProjectRevisionV1(revision);
  if (revision.schemaVersion === 2) return parseProjectRevisionV2(revision);
  throw new Error("ProjectRevision version is unsupported");
}
