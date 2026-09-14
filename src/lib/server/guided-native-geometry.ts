/** Recheck accepted native cut, speech, caption and source geometry without rendering. */
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { objectValue } from "@/lib/producer/contracts/validation";
import type { NativeShortDirection } from "./guided-native-candidate";
import { assertNativeCaptionGroups, type NativeCaptionGroups } from "./guided-native-captions";
import type { NativeShortProjectInput } from "./native-short-project";
import type { GuidedNativeAssetResolution } from "./guided-native-assets";

export interface NativeProjectMedia { sourceId: string; file: string; sha256: string }
export interface GuidedNativeVisualPlan {
  candidateHash: string; project: NativeShortProjectInput; assetResolutions?: GuidedNativeAssetResolution[];
}

/** Resolve accepted source identities without letting the visual plan substitute another file. */
export function guidedNativeSourceMedia(input: NativeShortProjectInput, sources: unknown): NativeProjectMedia[] {
  if (!Array.isArray(sources) || !sources.length) throw new Error("Native proposal lost admitted sources");
  const media = sources.map(value => {
    const source = objectValue(value, "native source");
    const binding = input.assets.find(asset => asset.path === source.path && asset.sha256 === source.sourceSha256);
    if (!binding || binding.role !== "source") throw new Error("Native project substituted the admitted source bytes/path");
    return { sourceId: String(source.id), file: binding.file, sha256: binding.sha256 };
  });
  if (new Set(media.map(row => row.sourceId)).size !== media.length) throw new Error("Native admitted source identity is duplicated");
  return media;
}

/** Explicit inspected geometry is required; never recreate the obsolete landscape panel. */
export function assertGuidedNativeGeometry(candidate: Record<string, unknown>, assets: NativeProjectMedia[],
  groups: NativeCaptionGroups, visual?: GuidedNativeVisualPlan): NativeShortDirection {
  const { nativeDirection: value, executionRoute, ...accepted } = candidate;
  const direction = objectValue(value, "compiled native direction") as unknown as NativeShortDirection;
  if (executionRoute !== "native-short-v1" || direction.route !== executionRoute
      || direction.sourceCutHash !== canonicalJsonSha256(accepted) || !Array.isArray(accepted.cutTrack)) {
    throw new Error("Native candidate lost its accepted cut identity");
  }
  if (!visual) throw new Error("Native visual strategy and inspected crop/title/caption geometry are required before assembly");
  if (visual.project.strategy.schemaVersion !== 3) throw new Error("New guided native builds require strategy version 3 with script-bound pacing and asset-use decisions");
  if (visual.candidateHash !== canonicalJsonSha256(candidate)) throw new Error("Native visual strategy belongs to a different proposal");
  assertNativeCaptionGroups(groups, direction);
  const canvas = visual.project.canvas;
  const cuts = accepted.cutTrack.map((value) => {
    const cut = objectValue(value, "native cut"), source = assets.find((row) => row.sourceId === cut.sourceId);
    if (!source || source.file !== canvas.sourceFile || source.file !== `assets/${source.sha256}.mp4`
        || Number(cut.audioLeadMs ?? 0) !== 0) throw new Error("Native source/cut binding differs from the inspected visual plan");
    return { start: cut.start, end: cut.end, speed: cut.speed };
  });
  const expected = { cuts, occurrences: direction.occurrences, captionGroups: groups,
    segments: direction.segments.map(({ startFrame, endFrameExclusive }) => ({ startFrame, endFrameExclusive })),
    frameRate: direction.frameRate, totalFrames: direction.totalFrames };
  const actual = { cuts: canvas.cuts.map(({ start, end, speed }) => ({ start, end, speed })),
    occurrences: canvas.occurrences, captionGroups: canvas.captionGroups, segments: canvas.segments,
    frameRate: canvas.frameRate, totalFrames: canvas.totalFrames };
  if (canonicalJsonSha256(expected) !== canonicalJsonSha256(actual)) throw new Error("Native canvas changed accepted speech, cuts, caption groups or frame clock");
  return direction;
}
