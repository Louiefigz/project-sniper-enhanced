/** Pure V6 manual crop projection; no source observation, execution, or approval. */
import { enumValue, objectValue } from "@/lib/producer/contracts/validation";
import { SCOPES, resolveLanes, validateLaneOverrides } from "@/lib/producer/intent-presets";
import { assertManualCaptionShortPlan } from "@/lib/producer/contracts/guided-media-profile";
import { parseTreatmentProposalV6, proposalV6ValidationView, type TreatmentProposalV6 } from "@/lib/producer/contracts/treatment-proposal-v6";
import { applyGuidedCaptionOperations } from "./guided-proposal-captions";
import { canonicalJsonSha256 } from "./auto-edit-hash";

function assertAcceptedDestination(plan: Record<string, unknown>): void {
  const target = objectValue(plan.target, "accepted manual short target");
  if (target.mode !== "short" || target.width !== 1080 || target.height !== 1920) {
    throw new Error("Post-cut manual crop requires an unchanged explicit short1080x1920 target");
  }
  // Bootstrap stores an explicit scope. Scope-default auto is accepted; trim+auto is not.
  const scope = enumValue(target.scope, SCOPES, "accepted scope");
  const lanes = validateLaneOverrides(target.lanes);
  if (resolveLanes(scope, lanes).captions !== "auto") throw new Error("Accepted caption lane must resolve to auto");
  if (Object.hasOwn(plan, "reframe")) throw new Error("Post-cut manual crop requires fresh absent reframe, not replacement geometry");
}

function assertSelectedSource(plan: Record<string, unknown>, sourceId: string): void {
  if (!Array.isArray(plan.cutTrack) || !plan.cutTrack.length) throw new Error("Manual crop requires a nonempty accepted cut track");
  const sources = plan.cutTrack.map((cut) => objectValue(cut, "accepted crop cut").sourceId);
  if (sources.some((source) => source !== sourceId)) throw new Error("Manual crop sourceId must match the one used accepted source");
}

/** Add only reframe. A separately requested V5 caption operation is validated, never applied here. */
export function applyGuidedReframeOperations(plan: Record<string, unknown>, proposal: TreatmentProposalV6): Record<string, unknown> {
  const current = parseTreatmentProposalV6(proposal);
  const operation = current.operations.find((item) => item.type === "reframe-manual-short");
  if (!operation) return structuredClone(plan);
  assertAcceptedDestination(plan);
  const selection = operation.reframe!;
  assertSelectedSource(plan, selection.sourceId);
  const candidate = { ...structuredClone(plan), reframe: { layout: selection.layout, crop: [...selection.crop], track: false } };
  // Actual explicit caption operation supplies this validation view; never invent captions-off.
  const captionedView = applyGuidedCaptionOperations(candidate, proposalV6ValidationView(current));
  assertManualCaptionShortPlan(captionedView);
  const { reframe: _reframe, ...unchanged } = candidate; void _reframe;
  if (canonicalJsonSha256(unchanged) !== canonicalJsonSha256(plan)) throw new Error("Manual crop projection changed another plan field");
  return candidate;
}

/** Reproduce the requested fields from the accepted cut, not from a rehashed candidate. */
export function assertGuidedReframeCandidate(accepted: Record<string, unknown>, candidate: Record<string, unknown>,
  proposal: TreatmentProposalV6): void {
  const current = parseTreatmentProposalV6(proposal);
  if (!current.operations.some((item) => item.type === "reframe-manual-short")) {
    throw new Error("V6 manual candidate requires its actual explicit crop operation");
  }
  const reframed = applyGuidedReframeOperations(accepted, current);
  const expected = applyGuidedCaptionOperations(reframed, proposalV6ValidationView(current));
  const keys = ["reframe", "captions", "captionsTrack", "captionStyles", "captionCorrectionLedger",
    "captionChapters", "dialogueCaptionAuthority", "chapters"];
  if (keys.some((key) => Object.hasOwn(candidate, key) !== Object.hasOwn(expected, key)
      || Object.hasOwn(expected, key) && canonicalJsonSha256(candidate[key]) !== canonicalJsonSha256(expected[key]))) {
    throw new Error("Opening crop/caption fields differ from the actual V6 request and accepted cut");
  }
}
