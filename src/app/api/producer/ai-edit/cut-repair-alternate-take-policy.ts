export interface CutRepairVisualSpeechRegionV1 {
  xPpm: number;
  yPpm: number;
  widthPpm: number;
  heightPpm: number;
}

export interface CutRepairAlternateTakeRequestV1 {
  schemaVersion: 1;
  kind: "cut-repair-alternate-take-request";
  visualSpeechRegion: CutRepairVisualSpeechRegionV1;
}

function object(
  value: unknown,
  label: string,
): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function exactKeys(
  value: Record<string, unknown>,
  expected: readonly string[],
  label: string,
): void {
  const observed = Object.keys(value);
  if (observed.length !== expected.length
      || expected.some((key) => !(key in value))) {
    throw new Error(`${label} has unsupported or missing fields`);
  }
}

function region(value: unknown): CutRepairVisualSpeechRegionV1 {
  const row = object(value, "alternate-take visual speech region");
  const keys = ["xPpm", "yPpm", "widthPpm", "heightPpm"] as const;
  exactKeys(row, keys, "alternate-take visual speech region");
  if (keys.some((key) => !Number.isInteger(row[key]))) {
    throw new Error(
      "alternate-take visual speech region must use integer ppm coordinates",
    );
  }
  const xPpm = row.xPpm as number;
  const yPpm = row.yPpm as number;
  const widthPpm = row.widthPpm as number;
  const heightPpm = row.heightPpm as number;
  if (xPpm < 0 || yPpm < 0 || widthPpm <= 0 || heightPpm <= 0
      || xPpm + widthPpm > 1_000_000
      || yPpm + heightPpm > 1_000_000) {
    throw new Error(
      "alternate-take visual speech region escapes the normalized frame",
    );
  }
  return { xPpm, yPpm, widthPpm, heightPpm };
}

/**
 * Parse explicit visual evidence only.
 *
 * Candidate IDs, transcript paths, and retake detector IDs are deliberately
 * absent: the controller derives them from the prepared operation.
 */
export function parseCutRepairAlternateTakeRequestV1(
  value: unknown,
): CutRepairAlternateTakeRequestV1 {
  const row = object(value, "cut repair alternate-take request");
  const keys = ["schemaVersion", "kind", "visualSpeechRegion"] as const;
  exactKeys(row, keys, "cut repair alternate-take request");
  if (row.schemaVersion !== 1
      || row.kind !== "cut-repair-alternate-take-request") {
    throw new Error("cut repair alternate-take request is unsupported");
  }
  return {
    schemaVersion: 1,
    kind: "cut-repair-alternate-take-request",
    visualSpeechRegion: region(row.visualSpeechRegion),
  };
}
