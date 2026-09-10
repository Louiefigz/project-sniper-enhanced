import {
  exactKeys,
  objectValue,
  stringValue,
} from "./validation";

export interface CutRepairTargetV1 {
  phrase: string;
  sourceId?: string;
  occurrence?: number;
  speaker?: string;
  beforeContext?: string;
  afterContext?: string;
  approximateSourceSample?: number;
  toleranceSamples?: number;
}

const KEYS = [
  "phrase", "sourceId", "occurrence", "speaker", "beforeContext",
  "afterContext", "approximateSourceSample", "toleranceSamples",
] as const;

function boundedString(value: unknown, label: string): string {
  const parsed = stringValue(value, label, 160).trim();
  if (!parsed) throw new Error(`${label} must not be blank`);
  return parsed;
}

function optionalString(
  value: unknown,
  label: string,
): string | undefined {
  return value === undefined ? undefined : boundedString(value, label);
}

function optionalInteger(
  value: unknown,
  label: string,
  minimum: number,
): number | undefined {
  if (value === undefined) return undefined;
  if (!Number.isSafeInteger(value) || Number(value) < minimum) {
    throw new Error(`${label} must be a safe integer >= ${minimum}`);
  }
  return Number(value);
}

/** Parse the one closed phrase target shared by HTTP and authority records. */
export function parseCutRepairTargetV1(value: unknown): CutRepairTargetV1 {
  const row = objectValue(value, "cut.restoreSpeech target");
  exactKeys(row, KEYS, ["phrase"], "cut.restoreSpeech target");
  const approximateSourceSample = optionalInteger(
    row.approximateSourceSample, "approximateSourceSample", 0);
  const toleranceSamples = optionalInteger(
    row.toleranceSamples, "toleranceSamples", 0);
  if ((approximateSourceSample === undefined)
      !== (toleranceSamples === undefined)) {
    throw new Error(
      "approximateSourceSample and toleranceSamples must be supplied together",
    );
  }
  const sourceId = optionalString(row.sourceId, "sourceId");
  const occurrence = optionalInteger(row.occurrence, "occurrence", 1);
  const speaker = optionalString(row.speaker, "speaker");
  const beforeContext = optionalString(row.beforeContext, "beforeContext");
  const afterContext = optionalString(row.afterContext, "afterContext");
  return {
    phrase: boundedString(row.phrase, "target phrase"),
    ...(sourceId ? { sourceId } : {}),
    ...(occurrence ? { occurrence } : {}),
    ...(speaker ? { speaker } : {}),
    ...(beforeContext ? { beforeContext } : {}),
    ...(afterContext ? { afterContext } : {}),
    ...(approximateSourceSample === undefined
      ? {} : { approximateSourceSample, toleranceSamples }),
  };
}
