import { parsePositiveRationalV1 } from "./positive-rational";
import type { PositiveRationalV1 } from "./positive-rational";
import type {
  DialogueSampleRangeV1,
  DialogueTrackSegmentV1,
} from "./dialogue-authority-types";
import { sha256 } from "./validation";

const SAFE_MAX = Number.MAX_SAFE_INTEGER;

export interface DialogueHeaderFieldsV1 {
  sourceSnapshotSetHash: string;
  pictureTimelineMapHash: string;
  projectFps: PositiveRationalV1;
  projectSampleRate: number;
  totalOutputFrames: number;
  totalOutputSamples: number;
  maxAbsoluteSpeedDeviation: PositiveRationalV1;
}

export interface DerivedDialogueMappingV1 {
  normalizedSourceSampleRange: DialogueSampleRangeV1;
  effectiveSpeed: PositiveRationalV1;
}

export function dialogueSafeInteger(
  value: unknown,
  label: string,
  minimum = 0,
): number {
  if (!Number.isSafeInteger(value)
      || Number(value) < minimum
      || Number(value) > SAFE_MAX) {
    throw new Error(`${label} must be a safe integer >= ${minimum}`);
  }
  return Number(value);
}

function gcd(left: bigint, right: bigint): bigint {
  let a = left;
  let b = right;
  while (b !== BigInt(0)) [a, b] = [b, a % b];
  return a;
}

function rationalParts(value: PositiveRationalV1): [bigint, bigint] {
  return [BigInt(value.numerator), BigInt(value.denominator)];
}

function safeBigInt(value: bigint, label: string): number {
  if (value < BigInt(0) || value > BigInt(SAFE_MAX)) {
    throw new Error(`${label} exceeds the JSON-safe integer range`);
  }
  return Number(value);
}

function normalizedBoundary(sample: number,
                            projectRate: number, sourceRate: number): number {
  return safeBigInt(
    BigInt(sample) * BigInt(projectRate) / BigInt(sourceRate),
    "normalized sample boundary",
  );
}

function exceedsTolerance(
  effective: PositiveRationalV1,
  requested: PositiveRationalV1,
  tolerance: PositiveRationalV1,
): boolean {
  const [en, ed] = rationalParts(effective);
  const [rn, rd] = rationalParts(requested);
  const [tn, td] = rationalParts(tolerance);
  const delta = en * rd >= rn * ed
    ? en * rd - rn * ed
    : rn * ed - en * rd;
  return delta * td > tn * ed * rd;
}

export function deriveDialogueMappingV1(
  row: DialogueTrackSegmentV1,
  projectRate: number,
  tolerance: PositiveRationalV1,
): DerivedDialogueMappingV1 {
  const startSample = normalizedBoundary(
    row.sourceSampleRange.startSample, projectRate, row.sourceSampleRate);
  const endSampleExclusive = normalizedBoundary(
    row.sourceSampleRange.endSampleExclusive,
    projectRate,
    row.sourceSampleRate,
  );
  if (endSampleExclusive <= startSample) {
    throw new Error("source span collapses on the project sample clock");
  }
  const numerator = BigInt(endSampleExclusive - startSample);
  const denominator = BigInt(
    row.outputSampleRange.endSampleExclusive
      - row.outputSampleRange.startSample);
  const divisor = gcd(numerator, denominator);
  const effectiveSpeed = {
    numerator: String(numerator / divisor),
    denominator: String(denominator / divisor),
  };
  if (exceedsTolerance(effectiveSpeed, row.speed, tolerance)) {
    throw new Error("effective dialogue speed exceeds the frozen tolerance");
  }
  return {
    normalizedSourceSampleRange: { startSample, endSampleExclusive },
    effectiveSpeed,
  };
}

export function parseDialogueHeaderV1(
  row: Record<string, unknown>,
  kind: "dialogue-track" | "dialogue-map",
): DialogueHeaderFieldsV1 {
  if (row.schemaVersion !== 1 || row.kind !== kind) {
    throw new Error(`${kind} version/kind is unsupported`);
  }
  const projectFps = parsePositiveRationalV1(row.projectFps);
  const projectSampleRate = dialogueSafeInteger(
    row.projectSampleRate, `${kind}.projectSampleRate`, 1);
  const totalOutputFrames = dialogueSafeInteger(
    row.totalOutputFrames, `${kind}.totalOutputFrames`, 1);
  const totalOutputSamples = dialogueSafeInteger(
    row.totalOutputSamples, `${kind}.totalOutputSamples`, 1);
  const [fpsNumerator, fpsDenominator] = rationalParts(projectFps);
  const expected = BigInt(totalOutputFrames) * BigInt(projectSampleRate)
    * fpsDenominator / fpsNumerator;
  if (safeBigInt(expected, "total output samples") !== totalOutputSamples) {
    throw new Error("total output samples do not equal exact B(total frames)");
  }
  return {
    sourceSnapshotSetHash: sha256(
      row.sourceSnapshotSetHash, `${kind}.sourceSnapshotSetHash`),
    pictureTimelineMapHash: sha256(
      row.pictureTimelineMapHash, `${kind}.pictureTimelineMapHash`),
    projectFps,
    projectSampleRate,
    totalOutputFrames,
    totalOutputSamples,
    maxAbsoluteSpeedDeviation: parsePositiveRationalV1(
      row.maxAbsoluteSpeedDeviation),
  };
}
