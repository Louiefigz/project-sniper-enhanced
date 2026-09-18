import {
  exactKeys,
  objectValue,
  sha256,
  stableId,
} from "./validation";

export type TimingAnchorV1 =
  | { type: "timeline-frame"; frame: number; timelineMapHash: string }
  | {
      type: "transcript-range";
      startWordId: string;
      endWordId: string;
      offsetFrames?: number;
    }
  | {
      type: "cut-segment";
      segmentId: string;
      elementVersion: number;
      basis: "output-frame";
      offsetFrames: number;
      timelineMapHash: string;
    }
  | { type: "semantic-beat"; beatId: string; offsetFrames?: number }
  | {
      type: "source-time";
      sourceId: string;
      sourceFrame: number;
      sourceSample?: number;
    }
  | { type: "section"; sectionId: string; offsetFrames?: number }
  | {
      type: "music-beat";
      cueId: string;
      beatIndex: number;
      offsetSamples?: number;
    };

function integer(value: unknown, label: string, minimum?: number): number {
  if (!Number.isSafeInteger(value)
      || (minimum !== undefined && Number(value) < minimum)) {
    throw new Error(`${label} must be a safe integer${minimum === 0 ? " >= 0" : ""}`);
  }
  return Number(value);
}

function optionalInteger(
  row: Record<string, unknown>,
  key: string,
): number | undefined {
  return row[key] === undefined ? undefined : integer(row[key], key);
}

function withOffset<T extends Record<string, unknown>>(
  result: T,
  value: number | undefined,
  key: "offsetFrames" | "offsetSamples",
): T & Partial<Record<typeof key, number>> {
  return value === undefined ? result : { ...result, [key]: value };
}

/** Parse one released timing-anchor variant with exact fields. */
export function parseTimingAnchorV1(value: unknown): TimingAnchorV1 {
  const row = objectValue(value, "TimingAnchorV1");
  if (row.type === "timeline-frame") {
    exactKeys(row, ["type", "frame", "timelineMapHash"],
      ["type", "frame", "timelineMapHash"], "timeline-frame anchor");
    return {
      type: "timeline-frame",
      frame: integer(row.frame, "frame", 0),
      timelineMapHash: sha256(row.timelineMapHash, "timelineMapHash"),
    };
  }
  if (row.type === "transcript-range") {
    exactKeys(row, ["type", "startWordId", "endWordId", "offsetFrames"],
      ["type", "startWordId", "endWordId"], "transcript-range anchor");
    return withOffset({
      type: "transcript-range",
      startWordId: stableId(row.startWordId, "startWordId"),
      endWordId: stableId(row.endWordId, "endWordId"),
    }, optionalInteger(row, "offsetFrames"), "offsetFrames");
  }
  if (row.type === "cut-segment") return parseCutSegment(row);
  if (row.type === "semantic-beat") {
    return parseNamedOffset(row, "semantic-beat", "beatId") as TimingAnchorV1;
  }
  if (row.type === "source-time") return parseSourceTime(row);
  if (row.type === "section") {
    return parseNamedOffset(row, "section", "sectionId") as TimingAnchorV1;
  }
  if (row.type === "music-beat") return parseMusicBeat(row);
  throw new Error("TimingAnchorV1.type is unsupported");
}

function parseCutSegment(row: Record<string, unknown>): TimingAnchorV1 {
  const keys = [
    "type", "segmentId", "elementVersion", "basis", "offsetFrames",
    "timelineMapHash",
  ];
  exactKeys(row, keys, keys, "cut-segment anchor");
  if (row.basis !== "output-frame") throw new Error("cut-segment basis is unsupported");
  return {
    type: "cut-segment",
    segmentId: stableId(row.segmentId, "segmentId"),
    elementVersion: integer(row.elementVersion, "elementVersion", 1),
    basis: "output-frame",
    offsetFrames: integer(row.offsetFrames, "offsetFrames"),
    timelineMapHash: sha256(row.timelineMapHash, "timelineMapHash"),
  };
}

function parseNamedOffset(
  row: Record<string, unknown>,
  type: "semantic-beat" | "section",
  idKey: "beatId" | "sectionId",
): Record<string, unknown> {
  exactKeys(row, ["type", idKey, "offsetFrames"], ["type", idKey], `${type} anchor`);
  return withOffset({
    type,
    [idKey]: stableId(row[idKey], idKey),
  }, optionalInteger(row, "offsetFrames"), "offsetFrames");
}

function parseSourceTime(row: Record<string, unknown>): TimingAnchorV1 {
  exactKeys(row, ["type", "sourceId", "sourceFrame", "sourceSample"],
    ["type", "sourceId", "sourceFrame"], "source-time anchor");
  const base = {
    type: "source-time" as const,
    sourceId: stableId(row.sourceId, "sourceId"),
    sourceFrame: integer(row.sourceFrame, "sourceFrame", 0),
  };
  return row.sourceSample === undefined ? base : {
    ...base,
    sourceSample: integer(row.sourceSample, "sourceSample", 0),
  };
}

function parseMusicBeat(row: Record<string, unknown>): TimingAnchorV1 {
  exactKeys(row, ["type", "cueId", "beatIndex", "offsetSamples"],
    ["type", "cueId", "beatIndex"], "music-beat anchor");
  return withOffset({
    type: "music-beat",
    cueId: stableId(row.cueId, "cueId"),
    beatIndex: integer(row.beatIndex, "beatIndex", 0),
  }, optionalInteger(row, "offsetSamples"), "offsetSamples");
}
