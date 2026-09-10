/** Private screening vocabulary. Nothing here is a renderer-ready grade. */
export type ColorProfile = "unknown" | "bt709-sdr" | "log" | "hdr";
export type LightingIntent = "unknown" | "neutral" | "dark" | "colored";
export interface ColorContext {
  sourceId: string; sourceProfile: ColorProfile; cameraProfile: string | null;
  historyState: "known" | "unknown"; transformHistory: string[];
  lightingGroups: { id: string; start: number; end: number; intent: LightingIntent; description: string }[];
}
export interface ColorSource {
  id: string; label: string; duration: number; sha256: string | null;
}
export interface ColorDescriptor {
  ok: true; kind: "descriptor"; planHash: string; manifestHash: string;
  cutHash: string; sources: ColorSource[]; blockers: string[];
  projectHistory: { stage: string; at: string }[];
}
export interface ColorStart {
  dir: string; jobId: string; expectedPlanHash: string; expectedManifestHash: string;
  contexts: ColorContext[];
}
export interface ColorGroup {
  sourceId: string; groupId: string; intent: LightingIntent;
  context: ColorContext;
  metadata: Record<string, string | number | boolean | null>;
  retainedIntervals: { sourceStart: number; sourceEnd: number; outStart: number; outEnd: number }[];
  unsampledIntervalIndices: number[];
  observations: { requestedTime: number; actualSourceTime: number | null; status: string;
    error: string | null; elapsedMs: number; frameMetadata: Record<string, string | boolean | null> }[];
  sampledFrames: number; minimumMeanLuma: number | null; maximumMeanLuma: number | null;
  worstNominalBlackFraction: number | null; worstNominalWhiteFraction: number | null;
  warnings: string[]; screeningOffsets: number[];
}
export interface ColorJob {
  ok: true; kind: "job"; jobId: string; state: "running" | "complete" | "partial" | "failed" | "interrupted";
  startedAt: string; elapsedMs: number; queueMs: 0; cleanupVerified: boolean;
  inputsRevalidated: boolean; parentsCurrent: boolean; error: string | null;
  planHash: string; manifestHash: string; diagnosticId: string | null;
  groups: ColorGroup[]; caveats: string[];
  timings: { sourceId: string; elapsedMs: number; workerMs: number | null;
    ffmpeg: string | null; phases: Record<string, number> }[];
  reviewState: "unreviewed"; deliveryApproved: false; qualityQualified: false; writesGrade: false;
}

/** The whole-source declaration is explicit, never a guessed lighting group. */
export function unknownColorContext(source: ColorSource): ColorContext {
  return { sourceId: source.id, sourceProfile: "unknown", cameraProfile: null,
    historyState: "unknown", transformHistory: [], lightingGroups: [
      { id: "whole-source", start: 0, end: source.duration, intent: "unknown", description: "" },
    ] };
}
