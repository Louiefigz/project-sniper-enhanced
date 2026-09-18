import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import {
  exactKeys,
  objectValue,
  sha256,
  stableId,
  stringValue,
  uniqueStrings,
} from "./validation";
import {
  parseCutRepairRippleImpactV1,
  type CutRepairRippleImpactV1,
} from "./cut-repair-ripple-impact";

export interface CutRepairRippleAnalysisV1 {
  schemaVersion: 1;
  operation: "cut.restoreSpeech";
  status: "NON_RIPPLE_IMPOSSIBLE";
  resolvedTarget: {
    kind: "word-range";
    sourceId: string;
    wordIds: string[];
    occurrence: number;
    sourceSampleRange: {
      startSample: number;
      endSampleExclusive: number;
    };
    transcriptTimingHash: string;
  };
  candidates: [];
  recommendedCandidate: null;
  rippleImpact: CutRepairRippleImpactV1;
  evidencePolicy: {
    alignment: "bounded-evidence-not-sole-audibility-proof";
    operatorReport: "ground-truth-when-audition-disagrees";
  };
  routeStatus: "analysis-only-no-mutation";
  contextAuthorityHash: string;
  parentRevisionHash: string;
}

const ANALYSIS_KEYS = [
  "schemaVersion", "operation", "status", "resolvedTarget", "candidates",
  "recommendedCandidate", "rippleImpact", "evidencePolicy", "routeStatus",
  "contextAuthorityHash", "parentRevisionHash",
] as const;

function integer(value: unknown, label: string, minimum: number): number {
  if (!Number.isSafeInteger(value) || Number(value) < minimum) {
    throw new Error(`${label} must be a safe integer >= ${minimum}`);
  }
  return Number(value);
}

function resolvedTarget(
  value: unknown,
): CutRepairRippleAnalysisV1["resolvedTarget"] {
  const row = objectValue(value, "ripple analysis resolvedTarget");
  const keys = [
    "kind", "sourceId", "wordIds", "occurrence", "sourceSampleRange",
    "transcriptTimingHash",
  ] as const;
  exactKeys(row, keys, keys, "ripple analysis resolvedTarget");
  const range = objectValue(
    row.sourceSampleRange, "resolvedTarget.sourceSampleRange");
  const rangeKeys = ["startSample", "endSampleExclusive"] as const;
  exactKeys(range, rangeKeys, rangeKeys, "resolvedTarget.sourceSampleRange");
  const startSample = integer(range.startSample, "resolved startSample", 0);
  const endSampleExclusive = integer(
    range.endSampleExclusive, "resolved endSampleExclusive", 1);
  if (row.kind !== "word-range" || endSampleExclusive <= startSample) {
    throw new Error("ripple analysis resolved target is malformed");
  }
  return {
    kind: "word-range",
    sourceId: stringValue(row.sourceId, "resolved sourceId", 160),
    wordIds: uniqueStrings(
      row.wordIds, "resolved wordIds", stableId),
    occurrence: integer(row.occurrence, "resolved occurrence", 1),
    sourceSampleRange: { startSample, endSampleExclusive },
    transcriptTimingHash: sha256(
      row.transcriptTimingHash, "resolved transcriptTimingHash"),
  };
}

function evidencePolicy(
  value: unknown,
): CutRepairRippleAnalysisV1["evidencePolicy"] {
  const row = objectValue(value, "ripple analysis evidencePolicy");
  const keys = ["alignment", "operatorReport"] as const;
  exactKeys(row, keys, keys, "ripple analysis evidencePolicy");
  if (row.alignment !== "bounded-evidence-not-sole-audibility-proof"
      || row.operatorReport !== "ground-truth-when-audition-disagrees") {
    throw new Error("ripple analysis evidence policy is unsupported");
  }
  return {
    alignment: "bounded-evidence-not-sole-audibility-proof",
    operatorReport: "ground-truth-when-audition-disagrees",
  };
}

/** Parse the exact no-mutation analysis allowed to reopen picture lock. */
export function parseCutRepairRippleAnalysisV1(
  value: unknown,
): CutRepairRippleAnalysisV1 {
  const row = objectValue(value, "cut repair ripple analysis");
  exactKeys(row, ANALYSIS_KEYS, ANALYSIS_KEYS, "cut repair ripple analysis");
  if (row.schemaVersion !== 1 || row.operation !== "cut.restoreSpeech"
      || row.status !== "NON_RIPPLE_IMPOSSIBLE"
      || row.routeStatus !== "analysis-only-no-mutation"
      || !Array.isArray(row.candidates) || row.candidates.length !== 0
      || row.recommendedCandidate !== null) {
    throw new Error("cut repair ripple analysis is not a closed impossible result");
  }
  return {
    schemaVersion: 1,
    operation: "cut.restoreSpeech",
    status: "NON_RIPPLE_IMPOSSIBLE",
    resolvedTarget: resolvedTarget(row.resolvedTarget),
    candidates: [],
    recommendedCandidate: null,
    rippleImpact: parseCutRepairRippleImpactV1(row.rippleImpact),
    evidencePolicy: evidencePolicy(row.evidencePolicy),
    routeStatus: "analysis-only-no-mutation",
    contextAuthorityHash: sha256(
      row.contextAuthorityHash, "ripple context authority hash"),
    parentRevisionHash: sha256(
      row.parentRevisionHash, "ripple parent revision hash"),
  };
}

export function cutRepairRippleAnalysisHash(value: unknown): string {
  return canonicalJsonSha256(parseCutRepairRippleAnalysisV1(value));
}
