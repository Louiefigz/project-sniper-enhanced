import {
  exactKeys,
  objectValue,
  stableId,
  stringValue,
  uniqueStrings,
} from "./validation";

export interface RippleFrameRangeV1 {
  startFrame: number;
  endFrameExclusive: number;
}

export interface RippleMovedDependentV1 {
  stableId: string;
  elementKind: string;
  from: RippleFrameRangeV1;
  to: RippleFrameRangeV1;
}

export interface CutRepairRippleImpactV1 {
  exact: true;
  requiredDurationDeltaFrames: number;
  newTotalOutputFrames: number;
  rippleFromFrame: number;
  reopensPictureLock: true;
  semanticClosureRequired: true;
  movedDependents: RippleMovedDependentV1[];
  invalidatedDependents: string[];
  unchangedOutputLockedIds: string[];
}

const IMPACT_KEYS = [
  "exact", "requiredDurationDeltaFrames", "newTotalOutputFrames",
  "rippleFromFrame", "reopensPictureLock", "semanticClosureRequired",
  "movedDependents", "invalidatedDependents", "unchangedOutputLockedIds",
] as const;

function integer(value: unknown, label: string, minimum: number): number {
  if (!Number.isSafeInteger(value) || Number(value) < minimum) {
    throw new Error(`${label} must be a safe integer >= ${minimum}`);
  }
  return Number(value);
}

function frameRange(value: unknown, label: string): RippleFrameRangeV1 {
  const row = objectValue(value, label);
  const keys = ["startFrame", "endFrameExclusive"] as const;
  exactKeys(row, keys, keys, label);
  const startFrame = integer(row.startFrame, `${label}.startFrame`, 0);
  const endFrameExclusive = integer(
    row.endFrameExclusive, `${label}.endFrameExclusive`, 1);
  if (endFrameExclusive <= startFrame) {
    throw new Error(`${label} must be a non-empty half-open frame range`);
  }
  return { startFrame, endFrameExclusive };
}

function movedDependent(
  value: unknown,
  index: number,
  delta: number,
  rippleFrom: number,
): RippleMovedDependentV1 {
  const label = `ripple impact movedDependents[${index}]`;
  const row = objectValue(value, label);
  const keys = ["stableId", "elementKind", "from", "to"] as const;
  exactKeys(row, keys, keys, label);
  const from = frameRange(row.from, `${label}.from`);
  const to = frameRange(row.to, `${label}.to`);
  if (from.startFrame < rippleFrom
      || to.startFrame !== from.startFrame + delta
      || to.endFrameExclusive !== from.endFrameExclusive + delta) {
    throw new Error(`${label} does not carry the exact ripple delta`);
  }
  return {
    stableId: stableId(row.stableId, `${label}.stableId`),
    elementKind: stringValue(row.elementKind, `${label}.elementKind`, 128),
    from,
    to,
  };
}

function uniquePartitions(
  moved: RippleMovedDependentV1[],
  invalidated: string[],
  outputLocked: string[],
): void {
  const identifiers = [
    ...moved.map((item) => item.stableId),
    ...invalidated,
    ...outputLocked,
  ];
  if (new Set(identifiers).size !== identifiers.length) {
    throw new Error("ripple dependent partitions must be mutually exclusive");
  }
}

/** Admit only an exact controller-computed ripple impact. */
export function parseCutRepairRippleImpactV1(
  value: unknown,
): CutRepairRippleImpactV1 {
  const row = objectValue(value, "cut repair ripple impact");
  exactKeys(row, IMPACT_KEYS, IMPACT_KEYS, "cut repair ripple impact");
  if (row.exact !== true || row.reopensPictureLock !== true
      || row.semanticClosureRequired !== true) {
    throw new Error("cut repair ripple impact is not exact and lock-reopening");
  }
  const delta = integer(
    row.requiredDurationDeltaFrames, "requiredDurationDeltaFrames", 1);
  const total = integer(row.newTotalOutputFrames, "newTotalOutputFrames", 2);
  const rippleFrom = integer(row.rippleFromFrame, "rippleFromFrame", 0);
  const oldTotal = total - delta;
  if (oldTotal < 1 || rippleFrom > oldTotal) {
    throw new Error("cut repair ripple impact has impossible duration bounds");
  }
  if (!Array.isArray(row.movedDependents)) {
    throw new Error("ripple impact movedDependents must be an array");
  }
  const moved = row.movedDependents.map((item, index) =>
    movedDependent(item, index, delta, rippleFrom));
  const invalidated = uniqueStrings(
    row.invalidatedDependents, "ripple invalidatedDependents");
  const outputLocked = uniqueStrings(
    row.unchangedOutputLockedIds, "ripple unchangedOutputLockedIds");
  uniquePartitions(moved, invalidated, outputLocked);
  return {
    exact: true,
    requiredDurationDeltaFrames: delta,
    newTotalOutputFrames: total,
    rippleFromFrame: rippleFrom,
    reopensPictureLock: true,
    semanticClosureRequired: true,
    movedDependents: moved,
    invalidatedDependents: invalidated,
    unchangedOutputLockedIds: outputLocked,
  };
}

export function rippleAffectedDependentIds(
  impact: CutRepairRippleImpactV1,
): string[] {
  return [
    ...impact.movedDependents.map((item) => item.stableId),
    ...impact.invalidatedDependents,
  ];
}
