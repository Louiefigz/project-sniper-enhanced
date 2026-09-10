/** Distinct private manual-crop class, not raw-request interpretation or visual approval. */
import { objectValue } from "./validation";
import { CAPTION_PROFILE, CAPTION_SHORT_PROFILE, CAPTION_BODY_PROFILE, CAPTION_SHORT_BODY_PROFILE,
  SCREENED_CAPTION_PROFILE, SCREENED_CAPTION_SHORT_PROFILE, SCREENED_CAPTION_BODY_PROFILE,
  SCREENED_CAPTION_SHORT_BODY_PROFILE, assertCaptionPresetPlan } from "./guided-caption-profile";

export const MANUAL_SHORT_PROFILE = "unity-source-float-manual-short-own-screen-v1" as const;
export const MANUAL_SHORT_BODY_PROFILE = "held-source-float-manual-short-own-screen-body-v1" as const;
const BODY_BY_OPENING = { "unity-source-float-own-screen-v1": "held-source-float-own-screen-body-v1",
  [MANUAL_SHORT_PROFILE]: MANUAL_SHORT_BODY_PROFILE, [CAPTION_PROFILE]: CAPTION_BODY_PROFILE,
  [CAPTION_SHORT_PROFILE]: CAPTION_SHORT_BODY_PROFILE, [SCREENED_CAPTION_PROFILE]: SCREENED_CAPTION_BODY_PROFILE,
  [SCREENED_CAPTION_SHORT_PROFILE]: SCREENED_CAPTION_SHORT_BODY_PROFILE } as const;
export type OpeningMediaProfile = keyof typeof BODY_BY_OPENING;
export type BodyMediaProfile = typeof BODY_BY_OPENING[OpeningMediaProfile];

export function openingMediaProfile(value: unknown): OpeningMediaProfile {
  if (typeof value !== "string" || !Object.hasOwn(BODY_BY_OPENING, value)) {
    throw new Error("Private opening media profile is unsupported");
  }
  return value as OpeningMediaProfile;
}

export function bodyMediaProfile(value: OpeningMediaProfile): BodyMediaProfile {
  return BODY_BY_OPENING[openingMediaProfile(value)];
}

export function isManualMediaProfile(value: unknown): boolean {
  return value === MANUAL_SHORT_PROFILE || value === CAPTION_SHORT_PROFILE || value === SCREENED_CAPTION_SHORT_PROFILE;
}

function active(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 0;
  if (value !== null && typeof value === "object") return Object.keys(value).length > 0;
  return Boolean(value);
}

/** Property presence is unsupported intent even when its supplied value is empty. */
function assertNoPresenterLayouts(plan: Record<string, unknown>): void {
  if (Object.hasOwn(plan, "presenterLayouts")) throw new Error("Legacy opening profile has no presenterLayouts execution owner");
}

/** Exact explicit subset of plan_lint_reframe; actual displayed geometry remains Python-observed. */
export function assertManualShortPlan(plan: Record<string, unknown>): void {
  assertNoPresenterLayouts(plan); assertManualShortGeometry(plan, false);
}

export function assertManualCaptionShortPlan(plan: Record<string, unknown>): void {
  assertCaptionPresetPlan(plan); assertNoPresenterLayouts(plan); assertManualShortGeometry(plan, true);
}

/** Shared declared crop subset only, not profile admission. Public legacy entries retain their owner fence. */
export function assertManualShortGeometry(plan: Record<string, unknown>, captioned: boolean): void {
  const target = objectValue(plan.target, "manual short target"), reframe = objectValue(plan.reframe, "manual short reframe");
  if (target.mode !== "short" || target.width !== 1080 || target.height !== 1920) {
    throw new Error("Manual short profile requires explicit1080x1920 short target");
  }
  if (Object.keys(reframe).sort().join(",") !== "crop,layout,track" || reframe.layout !== "fill" || reframe.track !== false) {
    throw new Error("Manual short requires only explicit fill/crop/track:false");
  }
  if (objectValue(plan.captions, "manual short captions").burn !== captioned) {
    throw new Error("Manual short requires explicit captions.burn=false; captioned short is unqualified");
  }
  if ([plan.overlays, plan.presenter].some(active)) {
    throw new Error("Manual short has unsupported additional visual intent");
  }
  const crop = reframe.crop;
  if (!Array.isArray(crop) || crop.length !== 4 || crop.some((item) => typeof item !== "number" || !Number.isFinite(item))) {
    throw new Error("Manual short crop requires four finite nonboolean numbers");
  }
  const [x, y, width, height] = crop;
  // Existing REFRAME_SPLIT.crop_min_frac, parity-tested against Python; no changed renderer bound.
  if (!(x >= 0 && y >= 0 && x <= 1 && y <= 1 && width >= 0.05 && height >= 0.05 && x + width <= 1 && y + height <= 1)) {
    throw new Error("Manual short crop is outside the existing normalized source bounds");
  }
  if (!Array.isArray(plan.cutTrack) || !plan.cutTrack.length) throw new Error("Manual short needs an explicit nonempty cut track");
  const cuts = plan.cutTrack.map((value) => objectValue(value, "manual short cut")), source = cuts[0].sourceId;
  if (typeof source !== "string" || !source || cuts.some((row) => row.sourceId !== source)) {
    throw new Error("Manual short supports exactly one used source and one fixed crop");
  }
}

function freshProfileForPlan(plan: Record<string, unknown>): OpeningMediaProfile {
  const target = objectValue(plan.target, "opening target"), reframe = plan.reframe;
  if (plan.captionsTrack && typeof plan.captionsTrack === "object" && !Array.isArray(plan.captionsTrack)) {
    assertCaptionPresetPlan(plan);
    if (target.mode === "short") { assertManualCaptionShortPlan(plan); return SCREENED_CAPTION_SHORT_PROFILE; }
    return SCREENED_CAPTION_PROFILE;
  }
  if (target.mode === "short" && reframe && typeof reframe === "object" && Object.hasOwn(reframe, "crop")) {
    assertManualShortPlan(plan);
    return MANUAL_SHORT_PROFILE;
  }
  return "unity-source-float-own-screen-v1";
}

/** Fresh execution requires screening. A separately held legacy input keeps its exact original class.
 * The optional token is not public request authority: callers still verify original input/authority bytes. */
export function openingMediaProfileForPlan(plan: Record<string, unknown>, heldProfile?: unknown): OpeningMediaProfile {
  assertNoPresenterLayouts(plan);
  const selected = freshProfileForPlan(plan);
  if (heldProfile === undefined) return selected;
  const held = openingMediaProfile(heldProfile);
  const legacy = (selected === SCREENED_CAPTION_PROFILE && held === CAPTION_PROFILE)
    || (selected === SCREENED_CAPTION_SHORT_PROFILE && held === CAPTION_SHORT_PROFILE);
  if (held !== selected && !legacy) throw new Error("Held opening profile differs from the exact candidate class");
  return held;
}
