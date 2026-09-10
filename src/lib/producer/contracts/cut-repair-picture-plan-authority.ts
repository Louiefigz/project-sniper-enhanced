import type {
  CutRestoreSpeechV1,
  FrameRangeV1,
  SampleRangeV1,
} from "./cut-restore-speech-v1";
import type { ProjectRevision } from "./project-revision";
import {
  exactKeys,
  objectValue,
  sha256,
} from "./validation";
import { canonicalJsonSha256 } from
  "@/lib/server/auto-edit-hash";

const FIELD = "cutRepairPicturePlanAuthority";
const KEYS = [
  "schemaVersion", "kind", "operationHash", "parentPlanObjectHash",
  "parentTimelineMapHash", "childTimelineMapHash", "target",
  "parentCutRow", "parentCutRowHash", "childCutRow", "childCutRowHash",
  "sourceExtension", "reclaimedSilence", "dirtyFrameRange",
  "mappingProof", "mappingProofHash", "reversion", "authorityHash",
] as const;
const TARGET_KEYS = [
  "index", "segmentId", "parentElementVersion", "childElementVersion",
] as const;
const REVERSION_KEYS = [
  "action", "index", "segmentId", "expectedChildCutRowHash",
  "restoreParentCutRowHash",
] as const;

export interface CutRepairPicturePlanAuthorityV1 {
  schemaVersion: 1;
  kind: "cut-repair-picture-plan-authority";
  operationHash: string;
  parentPlanObjectHash: string;
  parentTimelineMapHash: string;
  childTimelineMapHash: string;
  target: {
    index: number;
    segmentId: string;
    parentElementVersion: number;
    childElementVersion: number;
  };
  parentCutRow: Record<string, unknown>;
  parentCutRowHash: string;
  childCutRow: Record<string, unknown>;
  childCutRowHash: string;
  sourceExtension: SampleRangeV1;
  reclaimedSilence: SampleRangeV1;
  dirtyFrameRange: FrameRangeV1;
  mappingProof: Record<string, unknown>;
  mappingProofHash: string;
  reversion: Record<string, unknown>;
  authorityHash: string;
}

function integer(value: unknown, minimum: number, label: string): number {
  if (!Number.isSafeInteger(value) || Number(value) < minimum) {
    throw new Error(`${label} must be a safe integer >= ${minimum}`);
  }
  return Number(value);
}

function frameRange(value: unknown, label: string): FrameRangeV1 {
  const row = objectValue(value, label);
  const keys = ["startFrame", "endFrameExclusive"] as const;
  exactKeys(row, keys, keys, label);
  const startFrame = integer(row.startFrame, 0, `${label}.startFrame`);
  const endFrameExclusive = integer(
    row.endFrameExclusive, 1, `${label}.endFrameExclusive`);
  if (endFrameExclusive <= startFrame) throw new Error(`${label} is empty`);
  return { startFrame, endFrameExclusive };
}

function sampleRange(value: unknown, label: string): SampleRangeV1 {
  const row = objectValue(value, label);
  const keys = ["startSample", "endSampleExclusive"] as const;
  exactKeys(row, keys, keys, label);
  const startSample = integer(row.startSample, 0, `${label}.startSample`);
  const endSampleExclusive = integer(
    row.endSampleExclusive, 1, `${label}.endSampleExclusive`);
  if (endSampleExclusive <= startSample) throw new Error(`${label} is empty`);
  return { startSample, endSampleExclusive };
}

function elementVersion(
  row: Record<string, unknown>,
  label: string,
): number {
  if (row.generation !== undefined && row.version !== undefined) {
    throw new Error(`${label} has two version fields`);
  }
  return integer(row.generation ?? row.version ?? 1, 1, `${label} version`);
}

function parseTarget(value: unknown) {
  const row = objectValue(value, "picture plan target");
  exactKeys(row, TARGET_KEYS, TARGET_KEYS, "picture plan target");
  if (typeof row.segmentId !== "string" || !row.segmentId) {
    throw new Error("picture plan target segmentId is empty");
  }
  return {
    index: integer(row.index, 0, "picture plan target index"),
    segmentId: row.segmentId,
    parentElementVersion: integer(
      row.parentElementVersion, 1, "picture plan parent version"),
    childElementVersion: integer(
      row.childElementVersion, 1, "picture plan child version"),
  };
}

function parseReversion(value: unknown): Record<string, unknown> {
  const row = objectValue(value, "picture plan reversion");
  exactKeys(row, REVERSION_KEYS, REVERSION_KEYS, "picture plan reversion");
  if (row.action !== "restore-parent-cut-row"
      || typeof row.segmentId !== "string" || !row.segmentId) {
    throw new Error("picture plan reversion is unsupported");
  }
  integer(row.index, 0, "picture plan reversion index");
  sha256(row.expectedChildCutRowHash, "picture plan reversion child");
  sha256(row.restoreParentCutRowHash, "picture plan reversion parent");
  return row;
}

function parseMappingProof(
  value: unknown,
  expectedHash: string,
): Record<string, unknown> {
  const row = objectValue(value, "picture plan mapping proof");
  const keys = [
    "schemaVersion", "parentTimelineMapHash", "childTimelineMapHash",
    "authorizedDirtyWindows", "unchangedRanges",
  ] as const;
  exactKeys(row, keys, keys, "picture plan mapping proof");
  if (row.schemaVersion !== 1
      || !Array.isArray(row.authorizedDirtyWindows)
      || !row.authorizedDirtyWindows.length
      || !Array.isArray(row.unchangedRanges)
      || !row.unchangedRanges.length
      || canonicalJsonSha256(row) !== expectedHash) {
    throw new Error("picture plan mapping proof is stale");
  }
  row.authorizedDirtyWindows.forEach((item, index) =>
    frameRange(item, `mapping authorizedDirtyWindows[${index}]`));
  return row;
}

function assertRowBindings(
  authority: CutRepairPicturePlanAuthorityV1,
): void {
  const target = authority.target;
  const parentVersion = elementVersion(
    authority.parentCutRow, "picture plan parent row");
  const childVersion = elementVersion(
    authority.childCutRow, "picture plan child row");
  const reversion = authority.reversion;
  if (authority.parentCutRow.id !== target.segmentId
      || authority.childCutRow.id !== target.segmentId
      || parentVersion !== target.parentElementVersion
      || childVersion !== target.childElementVersion
      || childVersion !== parentVersion + 1
      || reversion.index !== target.index
      || reversion.segmentId !== target.segmentId
      || reversion.expectedChildCutRowHash !== authority.childCutRowHash
      || reversion.restoreParentCutRowHash !== authority.parentCutRowHash) {
    throw new Error("picture plan row or reversion binding is stale");
  }
}

/** Parse the plan-carried exact row mutation and deterministic reversion. */
export function parseCutRepairPicturePlanAuthorityV1(
  value: unknown,
): CutRepairPicturePlanAuthorityV1 {
  const row = objectValue(value, "CutRepairPicturePlanAuthorityV1");
  exactKeys(row, KEYS, KEYS, "CutRepairPicturePlanAuthorityV1");
  const core = Object.fromEntries(
    Object.entries(row).filter(([key]) => key !== "authorityHash"));
  if (row.schemaVersion !== 1
      || row.kind !== "cut-repair-picture-plan-authority"
      || canonicalJsonSha256(core) !== row.authorityHash) {
    throw new Error("picture plan authority is stale");
  }
  const parentCutRow = objectValue(row.parentCutRow, "picture plan parent row");
  const childCutRow = objectValue(row.childCutRow, "picture plan child row");
  const parentCutRowHash = sha256(
    row.parentCutRowHash, "picture plan parent row hash");
  const childCutRowHash = sha256(
    row.childCutRowHash, "picture plan child row hash");
  if (canonicalJsonSha256(parentCutRow) !== parentCutRowHash
      || canonicalJsonSha256(childCutRow) !== childCutRowHash) {
    throw new Error("picture plan cut-row hash is stale");
  }
  const mappingProofHash = sha256(
    row.mappingProofHash, "picture plan mapping proof hash");
  const authority = {
    schemaVersion: 1,
    kind: "cut-repair-picture-plan-authority",
    operationHash: sha256(row.operationHash, "picture plan operation"),
    parentPlanObjectHash: sha256(
      row.parentPlanObjectHash, "picture plan parent plan"),
    parentTimelineMapHash: sha256(
      row.parentTimelineMapHash, "picture plan parent timeline"),
    childTimelineMapHash: sha256(
      row.childTimelineMapHash, "picture plan child timeline"),
    target: parseTarget(row.target),
    parentCutRow, parentCutRowHash, childCutRow, childCutRowHash,
    sourceExtension: sampleRange(
      row.sourceExtension, "picture plan source extension"),
    reclaimedSilence: sampleRange(
      row.reclaimedSilence, "picture plan reclaimed silence"),
    dirtyFrameRange: frameRange(
      row.dirtyFrameRange, "picture plan dirty frame range"),
    mappingProof: parseMappingProof(row.mappingProof, mappingProofHash),
    mappingProofHash,
    reversion: parseReversion(row.reversion),
    authorityHash: sha256(row.authorityHash, "picture plan authority"),
  } satisfies CutRepairPicturePlanAuthorityV1;
  assertRowBindings(authority);
  return authority;
}

function assertOperationBinding(
  value: CutRepairPicturePlanAuthorityV1,
  operation: CutRestoreSpeechV1,
): void {
  const dirty = operation.pictureDirtyWindows;
  const reclaimed = operation.reclaimedSilence;
  if (operation.method !== "extend-and-reclaim-silence"
      || dirty.length !== 1 || !reclaimed
      || value.operationHash !== canonicalJsonSha256(operation)
      || value.parentTimelineMapHash !== operation.parentTimelineMapHash
      || value.target.segmentId !== operation.segment.segmentId
      || value.target.parentElementVersion !== operation.segment.elementVersion
      || canonicalJsonSha256(value.sourceExtension)
        !== canonicalJsonSha256(operation.sourceExtension)
      || canonicalJsonSha256(value.reclaimedSilence)
        !== canonicalJsonSha256(reclaimed.sourceSampleRange)
      || canonicalJsonSha256(value.dirtyFrameRange)
        !== canonicalJsonSha256(dirty[0])) {
    throw new Error("picture plan authority contradicts the repair operation");
  }
}

/**
 * Require picture operations to carry one exact plan authority, while
 * forbidding an audio-only plan from manufacturing picture authority.
 */
export function bindCutRepairPicturePlanAuthority(
  plan: Record<string, unknown>,
  operation: CutRestoreSpeechV1,
  childTimelineMapHash: string,
): CutRepairPicturePlanAuthorityV1 | null {
  const raw = plan[FIELD];
  if (!operation.pictureDirtyWindows.length) {
    if (raw !== undefined) {
      throw new Error("audio-only repair plan carries picture authority");
    }
    return null;
  }
  if (raw === undefined) {
    throw new Error("picture repair plan lacks picture-plan authority");
  }
  const authority = parseCutRepairPicturePlanAuthorityV1(raw);
  assertOperationBinding(authority, operation);
  const track = plan.cutTrack;
  const index = authority.target.index;
  if (!Array.isArray(track) || index >= track.length
      || canonicalJsonSha256(track[index])
        !== canonicalJsonSha256(authority.childCutRow)
      || authority.childTimelineMapHash
        !== sha256(childTimelineMapHash, "picture plan child timeline")
      || authority.mappingProof.parentTimelineMapHash
        !== authority.parentTimelineMapHash
      || authority.mappingProof.childTimelineMapHash
        !== authority.childTimelineMapHash
      || canonicalJsonSha256(authority.mappingProof.authorizedDirtyWindows)
        !== canonicalJsonSha256([authority.dirtyFrameRange])) {
    throw new Error("picture plan authority does not bind the review plan");
  }
  return authority;
}

/** Bind the reopened plan mutation to its exact V2 parent revision. */
export function assertCutRepairPicturePlanParent(
  authority: CutRepairPicturePlanAuthorityV1 | null,
  operation: CutRestoreSpeechV1,
  parent: ProjectRevision,
): void {
  if (!authority) return;
  if (parent.schemaVersion !== 2
      || authority.parentPlanObjectHash !== parent.planObjectHash
      || authority.parentTimelineMapHash !== parent.timelineMapHash
      || operation.parentPictureLockHash !== parent.pictureLockHash) {
    throw new Error("picture repair plan does not bind parent authority");
  }
}
