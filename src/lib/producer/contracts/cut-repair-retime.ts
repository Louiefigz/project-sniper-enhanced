import { parsePositiveRationalV1 } from "./positive-rational";
import type { PositiveRationalV1 } from "./positive-rational";
import {
  exactKeys,
  objectValue,
} from "./validation";

export interface CutRepairRetimeV1 {
  requestedSpeed: PositiveRationalV1;
  sourceSampleRange: {
    startSample: number;
    endSampleExclusive: number;
  };
  sourceSampleRate: number;
  normalizedSourceSampleRange: {
    startSample: number;
    endSampleExclusive: number;
  };
  outputSamples: number;
  effectiveRatio: PositiveRationalV1;
}

const KEYS = [
  "requestedSpeed", "sourceSampleRange", "sourceSampleRate",
  "normalizedSourceSampleRange", "outputSamples", "effectiveRatio",
] as const;

function integer(value: unknown, label: string, minimum: number): number {
  if (!Number.isSafeInteger(value) || Number(value) < minimum) {
    throw new Error(`${label} must be a safe integer >= ${minimum}`);
  }
  return Number(value);
}

function sampleRange(
  value: unknown,
  label: string,
): CutRepairRetimeV1["sourceSampleRange"] {
  const row = objectValue(value, label);
  const keys = ["startSample", "endSampleExclusive"] as const;
  exactKeys(row, keys, keys, label);
  const startSample = integer(row.startSample, `${label}.startSample`, 0);
  const endSampleExclusive = integer(
    row.endSampleExclusive, `${label}.endSampleExclusive`, 1);
  if (endSampleExclusive <= startSample) {
    throw new Error(`${label} must be non-empty`);
  }
  return { startSample, endSampleExclusive };
}

/** Parse the exact renderer/Palmier retime projection and prove its ratio. */
export function parseCutRepairRetimeV1(value: unknown): CutRepairRetimeV1 {
  const row = objectValue(value, "CutRepairRetimeV1");
  exactKeys(row, KEYS, KEYS, "CutRepairRetimeV1");
  const normalized = sampleRange(
    row.normalizedSourceSampleRange, "normalizedSourceSampleRange");
  const outputSamples = integer(row.outputSamples, "outputSamples", 1);
  const effectiveRatio = parsePositiveRationalV1(row.effectiveRatio);
  const normalizedLength = BigInt(
    normalized.endSampleExclusive - normalized.startSample);
  if (normalizedLength * BigInt(effectiveRatio.denominator)
      !== BigInt(outputSamples) * BigInt(effectiveRatio.numerator)) {
    throw new Error("cut repair effective ratio does not match its ranges");
  }
  return {
    requestedSpeed: parsePositiveRationalV1(row.requestedSpeed),
    sourceSampleRange: sampleRange(
      row.sourceSampleRange, "sourceSampleRange"),
    sourceSampleRate: integer(
      row.sourceSampleRate, "sourceSampleRate", 1),
    normalizedSourceSampleRange: normalized,
    outputSamples,
    effectiveRatio,
  };
}
