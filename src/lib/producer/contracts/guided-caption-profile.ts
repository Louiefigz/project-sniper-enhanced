/** Explicit initial all-kept caption presets; not typography, ASR or execution approval. */
import { exactKeys, objectValue } from "./validation";
import { parsePositiveRationalV1 } from "./positive-rational";

export const CAPTION_PROFILE = "unity-source-float-own-screen-caption-pages-v1" as const;
export const CAPTION_SHORT_PROFILE = "unity-source-float-manual-short-own-screen-caption-pages-v1" as const;
export const CAPTION_BODY_PROFILE = "held-source-float-own-screen-caption-pages-body-v1" as const;
export const CAPTION_SHORT_BODY_PROFILE = "held-source-float-manual-short-own-screen-caption-pages-body-v1" as const;
export const SCREENED_CAPTION_PROFILE = "unity-source-float-own-screen-caption-layout-v2" as const;
export const SCREENED_CAPTION_SHORT_PROFILE = "unity-source-float-manual-short-own-screen-caption-layout-v2" as const;
export const SCREENED_CAPTION_BODY_PROFILE = "held-source-float-own-screen-caption-layout-body-v2" as const;
export const SCREENED_CAPTION_SHORT_BODY_PROFILE = "held-source-float-manual-short-own-screen-caption-layout-body-v2" as const;

/** An execution requirement, never proof that the actual layout passed. */
export function isScreenedCaptionProfile(value: unknown): boolean {
  return value === SCREENED_CAPTION_PROFILE || value === SCREENED_CAPTION_SHORT_PROFILE;
}

export function isCaptionProfile(value: unknown): boolean {
  return value === CAPTION_PROFILE || value === CAPTION_SHORT_PROFILE || isScreenedCaptionProfile(value);
}

/** No defaults/mutation or ignored custom/group/correction fields. Python independently runs the real compiler. */
export function assertCaptionPresetPlan(plan: Record<string, unknown>): void {
  const target = objectValue(plan.target, "caption target");
  const size = target.mode === "short" ? [1080, 1920] : target.mode === "longform" ? [1920, 1080] : [];
  if (!size.length || target.width !== size[0] || target.height !== size[1]) throw new Error("Caption preset requires exact native compiler destination");
  const captions = objectValue(plan.captions, "caption burn");
  exactKeys(captions, ["burn"], ["burn"], "caption burn");
  if (captions.burn !== true) throw new Error("Caption preset requires explicit captions.burn=true");
  const track = objectValue(plan.captionsTrack, "caption track"), keys = ["schemaVersion", "source", "defaultPolicy", "groups"];
  exactKeys(track, keys, keys, "caption preset track");
  if (track.schemaVersion !== 1 || track.source !== "kept-transcript" || (track.defaultPolicy !== "line" && track.defaultPolicy !== "karaoke")
      || !Array.isArray(track.groups) || track.groups.length) throw new Error("Caption preset requires all-kept line/karaoke without custom groups");
  if (["captionCorrectionLedger", "captionStyles", "captionChapters", "dialogueCaptionAuthority"].some((key) => Object.hasOwn(plan, key))
      || [plan.chapters, plan.overlays, plan.presenter].some(active)) throw new Error("Caption preset has unqualified correction/style/chapter/visual authority");
}

function active(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 0;
  if (value && typeof value === "object") return Object.keys(value).length > 0;
  return Boolean(value);
}

/** Conservative entire-program page upper bound, not only simultaneous captions or opening pages. */
export function assertCaptionGraphWorkload(plan: Record<string, unknown>, clock: { frameRate: string; totalFrames: number }, graphicCount: number): void {
  const target = objectValue(plan.target, "caption canvas");
  const [numerator, denominator = "1", extra] = clock.frameRate.split("/");
  if (extra !== undefined) throw new Error("Caption workload frame rate is malformed");
  const rate = parsePositiveRationalV1({ numerator, denominator });
  if (!Number.isSafeInteger(clock.totalFrames) || clock.totalFrames <= 0 || !Number.isSafeInteger(graphicCount) || graphicCount < 0) {
    throw new Error("Caption workload needs exact positive frame/count metadata");
  }
  const pageFrames = Math.max(1, Number(BigInt(rate.numerator) * BigInt(30) / BigInt(rate.denominator)));
  const pages = Math.ceil(clock.totalFrames / pageFrames), count = pages + graphicCount;
  const pixels = Number(target.width) * Number(target.height);
  if (!Number.isSafeInteger(pixels) || pixels <= 0 || count > 128 || (count + 1) * pixels > 64 * 1024 * 1024) {
    throw new Error("Caption combined graph exceeds existing64MiPixel workload; no inputs may be dropped");
  }
}
