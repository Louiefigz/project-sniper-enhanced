/** Full-context metadata dispatch only; no profile is selected from a caller token or stripped plan. */
import { objectValue } from "@/lib/producer/contracts/validation";
import { openingMediaProfileForPlan, bodyMediaProfile, openingMediaProfile } from "@/lib/producer/contracts/guided-media-profile";
import { assertGuidedPresenterProfile, isPresenterOpeningProfile, presenterBodyProfile,
  type GuidedPresenterProfileInput } from "@/lib/producer/contracts/guided-presenter-profile";
import { currentOpeningMediaProfile, type CurrentOpeningMediaProfile } from "@/lib/producer/contracts/guided-opening-media-v1";
import type { CurrentBodyMediaProfile } from "@/lib/producer/contracts/guided-body-media-v1";
import { parseCurrentTreatmentProposal } from "@/lib/producer/contracts/treatment-proposal-v8";
import { assertNoPresenterOpening } from "./guided-opening-request-lanes";
import type { ProposalEvidence } from "./guided-proposal-evidence";

export const PRESENTER_OPENING_PROFILE_FILES = ["src/lib/server/guided-opening-profile.ts",
  "src/lib/producer/contracts/guided-presenter-profile.ts", "src/lib/producer/contracts/guided-presenter-workload.ts",
  "src/lib/producer/contracts/guided-media-profile.ts", "src/lib/producer/contracts/guided-caption-profile.ts"] as const;

/** Property presence is work/unsupported intent, never a way to select the legacy no-op branch. */
export function hasPresenterMediaRequest(proposal: unknown, candidate: Record<string, unknown>): boolean {
  if (Object.hasOwn(candidate, "presenterLayouts")) return true;
  if (proposal === undefined) return false;
  const parsed = parseCurrentTreatmentProposal(proposal);
  return parsed.schemaVersion === 8 && parsed.operations.some(row => row.type === "presenter-layout-window");
}

/** Cold/fresh selection uses the same complete immutable request context. Held legacy tokens are never upgraded. */
export function openingProfileForContext(input: GuidedPresenterProfileInput, heldProfile?: unknown): CurrentOpeningMediaProfile {
  if (!hasPresenterMediaRequest(input.proposal, input.candidate)) {
    assertNoPresenterOpening(input);
    return openingMediaProfileForPlan(input.candidate, heldProfile);
  }
  const selected = assertGuidedPresenterProfile(input).profile;
  if (heldProfile !== undefined && currentOpeningMediaProfile(heldProfile) !== selected) {
    throw new Error("Held presenter profile differs from exact original request/candidate class; no legacy upgrade or downgrade");
  }
  return selected;
}

/** Map the already-held original opening class, without selecting another plan or inventing fresh authority. */
export function currentBodyMediaProfile(value: unknown): CurrentBodyMediaProfile {
  const opening = currentOpeningMediaProfile(value);
  return isPresenterOpeningProfile(opening) ? presenterBodyProfile(opening) : bodyMediaProfile(openingMediaProfile(opening));
}

export interface PresenterOpeningMetadata {
  plan: Record<string, unknown>; bindings: unknown; reviewEndFrame: number;
  accepted?: Record<string, unknown>; manifest?: Record<string, unknown>; proposal?: unknown; evidence?: ProposalEvidence;
}

/** Metadata-only direct callers cannot use V2 selected layout without its original accepted/source context. */
export function presenterMetadataContext(input: PresenterOpeningMetadata): GuidedPresenterProfileInput {
  if (!input.evidence || input.proposal === undefined) throw new Error("Presenter metadata requires original proposal/evidence context");
  return { accepted: objectValue(input.accepted, "presenter accepted plan"), candidate: input.plan,
    manifest: objectValue(input.manifest, "presenter original manifest"), proposal: input.proposal,
    evidence: input.evidence, bindings: input.bindings };
}

/** Whole-body rederivation/budget always runs. Opening additionally preserves its existing eight-graphic bound. */
export function assertPresenterOpeningMetadata(input: PresenterOpeningMetadata, allPresentations: boolean): void {
  const context = presenterMetadataContext(input); assertGuidedPresenterProfile(context);
  const bindings = objectValue(input.bindings, "presenter frame bindings");
  if (!Number.isSafeInteger(input.reviewEndFrame) || input.reviewEndFrame <= 0 || input.reviewEndFrame > Number(bindings.totalFrames)) {
    throw new Error("Presenter review range differs from the original whole clock");
  }
  const rows = bindings.graphics as Array<{ startFrame: number }>;
  if (!allPresentations && rows.filter(row => row.startFrame < input.reviewEndFrame).length > 8) {
    throw new Error("Private opening exceeds its initial eight-graphic admission bound");
  }
}
