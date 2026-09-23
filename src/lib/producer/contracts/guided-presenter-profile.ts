/** Explicit, unreleased presenter classes. Metadata eligibility is not live ownership, clearance or approval. */
import { objectValue, exactKeys } from "./validation";
import { assertManualShortGeometry } from "./guided-media-profile";
import { assertCaptionPresetPlan } from "./guided-caption-profile";
import { parseTreatmentProposalV8, proposalV8ValidationView, type TreatmentProposalV8 } from "./treatment-proposal-v8";
import { proposalV7ValidationView } from "./treatment-proposal-v7";
import { proposalV6ValidationView } from "./treatment-proposal-v6";
import { assertPresenterGraphWorkload, presenterNativeCanvas } from "./guided-presenter-workload";
import { canonicalJsonSha256 } from "@/lib/server/auto-edit-hash";
import { applyGuidedPresenterOperations, assertGuidedPresenterCandidate, guidedPresenterPolicy,
  guidedPresenterWindows, type GuidedPresenterWindow } from "@/lib/server/guided-proposal-presenter";
import { applyGuidedMusicOperations } from "@/lib/server/guided-proposal-music";
import { applyGuidedCaptionOperations, guidedCaptionPolicy } from "@/lib/server/guided-proposal-captions";
import { assertGuidedReframeCandidate } from "@/lib/server/guided-proposal-reframe";
import { assertGuidedFrameBindings, type GuidedGraphicFrameBinding } from "@/lib/server/guided-proposal-bindings";
import type { ProposalEvidence } from "@/lib/server/guided-proposal-evidence";
export { assertPresenterGraphWorkload } from "./guided-presenter-workload";

export const PRESENTER_PROFILE = "unity-source-float-own-screen-presenter-layout-v1" as const;
export const PRESENTER_SHORT_PROFILE = "unity-source-float-manual-short-own-screen-presenter-layout-v1" as const;
export const PRESENTER_CAPTION_PROFILE = "unity-source-float-own-screen-presenter-caption-layout-v1" as const;
export const PRESENTER_CAPTION_SHORT_PROFILE = "unity-source-float-manual-short-own-screen-presenter-caption-layout-v1" as const;
export const PRESENTER_BODY_PROFILE = "held-source-float-own-screen-presenter-layout-body-v1" as const;
export const PRESENTER_SHORT_BODY_PROFILE = "held-source-float-manual-short-own-screen-presenter-layout-body-v1" as const;
export const PRESENTER_CAPTION_BODY_PROFILE = "held-source-float-own-screen-presenter-caption-layout-body-v1" as const;
export const PRESENTER_CAPTION_SHORT_BODY_PROFILE = "held-source-float-manual-short-own-screen-presenter-caption-layout-body-v1" as const;
const BODY_BY_OPENING = { [PRESENTER_PROFILE]: PRESENTER_BODY_PROFILE, [PRESENTER_SHORT_PROFILE]: PRESENTER_SHORT_BODY_PROFILE,
  [PRESENTER_CAPTION_PROFILE]: PRESENTER_CAPTION_BODY_PROFILE, [PRESENTER_CAPTION_SHORT_PROFILE]: PRESENTER_CAPTION_SHORT_BODY_PROFILE } as const;
export type PresenterOpeningProfile = keyof typeof BODY_BY_OPENING;
export type PresenterBodyProfile = typeof BODY_BY_OPENING[PresenterOpeningProfile];
export interface GuidedPresenterProfileInput {
  accepted: Record<string, unknown>; candidate: Record<string, unknown>; manifest: Record<string, unknown>;
  proposal: unknown; evidence: ProposalEvidence; bindings: unknown;
}

/** Token classification only; it cannot select a profile for a plan or authenticate an execution. */
export function isPresenterOpeningProfile(value: unknown): value is PresenterOpeningProfile {
  return typeof value === "string" && Object.hasOwn(BODY_BY_OPENING, value);
}

export function isPresenterBodyProfile(value: unknown): value is PresenterBodyProfile {
  return typeof value === "string" && Object.values(BODY_BY_OPENING).some(profile => profile === value);
}

export function presenterOpeningProfile(value: unknown): PresenterOpeningProfile {
  if (typeof value !== "string" || !Object.hasOwn(BODY_BY_OPENING, value)) throw new Error("Unsupported explicit presenter opening profile");
  return value as PresenterOpeningProfile;
}

export function presenterBodyProfile(value: PresenterOpeningProfile): PresenterBodyProfile {
  return BODY_BY_OPENING[presenterOpeningProfile(value)];
}

export function isPresenterCaptionProfile(value: unknown): boolean {
  return value === PRESENTER_CAPTION_PROFILE || value === PRESENTER_CAPTION_SHORT_PROFILE;
}

export function isPresenterManualProfile(value: unknown): boolean {
  return value === PRESENTER_SHORT_PROFILE || value === PRESENTER_CAPTION_SHORT_PROFILE;
}

function active(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 0;
  if (value !== null && typeof value === "object") return Object.keys(value).length > 0;
  return Boolean(value);
}

function sameFields(expected: Record<string, unknown>, candidate: Record<string, unknown>, keys: string[]): void {
  if (keys.some(key => Object.hasOwn(candidate, key) !== Object.hasOwn(expected, key)
      || Object.hasOwn(expected, key) && canonicalJsonSha256(candidate[key]) !== canonicalJsonSha256(expected[key]))) {
    throw new Error("Presenter candidate prior lanes differ from actual requested or inherited fields");
  }
}

/** Views are local prior-lane validation only; actual V8 evidence/bindings/operation indices remain unchanged. */
function assertPriorLanes(input: GuidedPresenterProfileInput, proposal: TreatmentProposalV8): void {
  const musicView = proposalV8ValidationView(proposal), cropView = proposalV7ValidationView(musicView);
  const captionPolicy = input.evidence.captionPolicy;
  if (!captionPolicy || canonicalJsonSha256(captionPolicy) !== canonicalJsonSha256(guidedCaptionPolicy(captionPolicy.configuration))) {
    throw new Error("Presenter V8 evidence lacks the exact captured caption policy");
  }
  if (!input.evidence.musicPolicy) throw new Error("Presenter V8 evidence lacks its original music policy");
  const music = applyGuidedMusicOperations({ plan: input.accepted, manifest: input.manifest,
    proposal: musicView, policy: input.evidence.musicPolicy });
  sameFields(music, input.candidate, ["music"]);
  if (cropView.operations.some(row => row.type === "reframe-manual-short")) {
    assertGuidedReframeCandidate(input.accepted, input.candidate, cropView);
    return;
  }
  const captioned = applyGuidedCaptionOperations(input.accepted, proposalV6ValidationView(cropView));
  sameFields(captioned, input.candidate, ["reframe", "captions", "captionsTrack", "captionStyles", "captionCorrectionLedger",
    "captionChapters", "dialogueCaptionAuthority", "chapters"]);
}

function declaredCaptionMode(plan: Record<string, unknown>): boolean {
  const captions = objectValue(plan.captions, "presenter explicit caption choice");
  exactKeys(captions, ["burn"], ["burn"], "presenter explicit caption choice");
  if (captions.burn === true) { assertCaptionPresetPlan(plan); return true; }
  if (captions.burn !== false || Object.hasOwn(plan, "captionsTrack")) {
    throw new Error("Uncaptioned presenter requires explicit burn:false and absent captionsTrack");
  }
  return false;
}

function assertCandidateClass(plan: Record<string, unknown>, captioned: boolean): void {
  const target = objectValue(plan.target, "presenter target"); presenterNativeCanvas(target);
  const unsupported = ["titleCards", "brollTrack", "baselineLook", "punchIns", "transitions", "audioEnhance", "audioGain",
    "persistentText", "faceBBoxNorm", "chapters"];
  const authority = ["captionStyles", "captionCorrectionLedger", "captionChapters", "dialogueCaptionAuthority"];
  if (unsupported.some(key => active(plan[key])) || authority.some(key => Object.hasOwn(plan, key))) {
    throw new Error("Presenter profile has unqualified additional lane or caption authority");
  }
  if (target.mode === "short") assertManualShortGeometry(plan, captioned);
  else {
    const reframe = plan.reframe == null ? {} : objectValue(plan.reframe, "presenter longform reframe");
    if (Object.keys(reframe).some(key => key !== "strategy") || Object.hasOwn(reframe, "strategy") && reframe.strategy !== "none") {
      throw new Error("Presenter longform does not qualify reframing, tracking or implicit crop");
    }
  }
  if (!Array.isArray(plan.cutTrack) || !plan.cutTrack.length) throw new Error("Presenter needs nonempty unity cuts");
  for (const value of plan.cutTrack) {
    const cut = objectValue(value, "presenter cut");
    if (Object.hasOwn(cut, "speed") && cut.speed !== 1 || cut.audioLeadMs !== undefined && cut.audioLeadMs !== 0) {
      throw new Error("Presenter profile does not qualify speed changes or J-cut audio leads");
    }
  }
}

function assertGraphicClass(entry: Record<string, unknown>, row: GuidedGraphicFrameBinding): void {
  const p = row.presentation, spec = active(entry.spec) ? objectValue(entry.spec, "presenter graphic spec") : {};
  const hole = entry.kind === "module-takeover"
    || ["module-scoreboard", "module-pipeline", "module-ledger-dark"].includes(String(entry.kind)) && active(spec.presenterFrame);
  if (p.schemaVersion !== 1 || p.anchor !== "own-screen" || p.placement !== "full-canvas" || p.compositeMode !== "normal"
      || p.baseTreatment !== "preserve" || entry.anchor !== "own-screen" || entry.takeoverBase != null
      || active(entry.exitOnCut) || active(entry.placement) || hole) {
    throw new Error("Presenter profile requires normal full-canvas preserve graphics without holes or added placement");
  }
}

/** Whole-body half-open comparison; even all-future graphics cannot hide an explicitly requested presenter. */
export function assertPresenterGraphicsDisjoint(graphics: GuidedGraphicFrameBinding[], windows: GuidedPresenterWindow[]): void {
  if (graphics.some(graphic => windows.some(window => graphic.startFrame < window.endFrameExclusive
      && window.startFrame < graphic.endFrameExclusive))) {
    throw new Error("Presenter windows must not overlap any original full-canvas graphic; no inputs may be removed or retimed");
  }
}

function exactBindings(input: GuidedPresenterProfileInput, proposal: TreatmentProposalV8) {
  if (active(input.accepted.graphicsTrack)) throw new Error("Inherited graphics have no fresh exact presenter profile bindings");
  const bindings = assertGuidedFrameBindings({ proposal, evidence: input.evidence, candidate: input.candidate, inheritedCount: 0 }, input.bindings);
  if (bindings.schemaVersion !== 2 || !bindings.presenterLayouts.length || bindings.unboundInheritedGraphicIds.length) {
    throw new Error("Presenter profiles require nonempty actual V8 windows and exact V2 bindings");
  }
  const track = input.candidate.graphicsTrack as unknown[], ids = new Set<string>();
  for (const row of bindings.graphics) {
    const entry = objectValue(track[row.order], "presenter graphic");
    if (ids.has(row.graphicId) || !Number.isSafeInteger(row.startFrame) || !Number.isSafeInteger(row.endFrameExclusive)
        || row.startFrame < 0 || row.startFrame >= row.endFrameExclusive || row.endFrameExclusive > bindings.totalFrames) {
      throw new Error("Presenter graphic bindings lack exact ordered unique whole-body intervals");
    }
    ids.add(row.graphicId); assertGraphicClass(entry, row);
  }
  assertPresenterGraphicsDisjoint(bindings.graphics, bindings.presenterLayouts);
  return bindings;
}

function selectedProfile(short: boolean, captioned: boolean): PresenterOpeningProfile {
  if (captioned) return short ? PRESENTER_CAPTION_SHORT_PROFILE : PRESENTER_CAPTION_PROFILE;
  return short ? PRESENTER_SHORT_PROFILE : PRESENTER_PROFILE;
}

/** Pure metadata preflight only. Owners still owe original intent/source, live media, caption clearance and QC. */
export function assertGuidedPresenterProfile(input: GuidedPresenterProfileInput) {
  const proposal = parseTreatmentProposalV8(input.proposal);
  if (input.evidence.schemaVersion !== 8 || !input.evidence.presenterPolicy || proposal.colorPolicy !== "preserve"
      || proposal.operations.some(row => row.type === "grade")) throw new Error("Presenter profile requires actual V8 policy and unchanged source color");
  applyGuidedPresenterOperations({ plan: input.accepted, manifest: input.manifest, proposal,
    policy: input.evidence.presenterPolicy, evidence: input.evidence });
  assertGuidedPresenterCandidate({ ...input, proposal }); assertPriorLanes(input, proposal);
  const captioned = declaredCaptionMode(input.candidate); assertCandidateClass(input.candidate, captioned);
  const bindings = exactBindings(input, proposal), windows = guidedPresenterWindows(proposal, input.evidence);
  if (windows.some(row => row.layout.presenterRect.width > row.layout.presenterCrop.width
      || row.layout.presenterRect.height > row.layout.presenterCrop.height)) throw new Error("Initial presenter executor does not qualify presenter upscaling");
  const assets = guidedPresenterPolicy(input.accepted, input.manifest).assets;
  const canvases = windows.map(row => assets.find(asset => asset.assetId === row.layout.assetId)!);
  const workload = assertPresenterGraphWorkload({ target: input.candidate.target, clock: bindings,
    graphicCount: bindings.graphics.length, captioned, presenterAssetCanvases: canvases });
  const profile = selectedProfile(objectValue(input.candidate.target, "presenter target").mode === "short", captioned);
  return { profile, bodyProfile: presenterBodyProfile(profile), windows, workload };
}
