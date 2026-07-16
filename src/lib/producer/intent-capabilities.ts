import {
  resolveLanes,
  type ProjectIntent,
} from "./intent-presets";
import type { AssetManifest, ManifestAsset } from "./types";

export const INTENT_CAPABILITY_CODES = {
  BROLL_UNAVAILABLE_RESOLVED: "BROLL_UNAVAILABLE_RESOLVED",
  BROLL_REQUIRED_UNAVAILABLE: "BROLL_REQUIRED_UNAVAILABLE",
} as const;

export type IntentCapabilityCode =
  (typeof INTENT_CAPABILITY_CODES)[keyof typeof INTENT_CAPABILITY_CODES];

export interface IntentCapabilityDecision {
  code: IntentCapabilityCode;
  lane: "broll";
  requested: "auto";
  resolved: "off" | null;
  status: "resolved" | "blocked";
  eligibleAssets: number;
  message: string;
}

export interface IntentCapabilityResolution {
  ok: boolean;
  requestedIntent: ProjectIntent;
  resolvedIntent?: ProjectIntent;
  decisions: IntentCapabilityDecision[];
  error?: string;
}

function copyIntent(intent: ProjectIntent): ProjectIntent {
  return {
    ...intent,
    lanes: { ...intent.lanes },
    ...(intent.audioEnhance ? { audioEnhance: { ...intent.audioEnhance } } : {}),
    ...(intent.reference ? { reference: { ...intent.reference } } : {}),
  };
}

/** Manifest-only eligibility: the deterministic renderer needs both id and path. */
export function eligibleBrollAssets(
  manifest: Pick<AssetManifest, "broll">,
): ManifestAsset[] {
  return (manifest.broll ?? []).filter((asset) =>
    typeof asset?.id === "string" && asset.id.trim().length > 0
      && typeof asset.path === "string" && asset.path.trim().length > 0);
}

function resolvedDecision(
  intent: ProjectIntent,
  eligibleAssets: number,
): IntentCapabilityDecision {
  const fidelity = intent.reference?.strategy === "mimic"
    ? "The reference can still guide pacing and graphics, but its cutaway pattern cannot be matched exactly."
    : intent.scope === "full"
      ? "The rest of the Full edit remains enabled."
      : "The rest of the Produced edit remains enabled.";
  return {
    code: INTENT_CAPABILITY_CODES.BROLL_UNAVAILABLE_RESOLVED,
    lane: "broll",
    requested: "auto",
    resolved: "off",
    status: "resolved",
    eligibleAssets,
    message: `This edit will continue without cutaways. Text cards, graphics, captions, and motion remain enabled. ${fidelity} You can add cutaways later.`,
  };
}

/**
 * Reconcile asset-dependent lane obligations without mutating operator intent.
 * Explicit off/operator decisions and available assets pass through unchanged.
 */
export function reconcileIntentCapabilities(
  intent: ProjectIntent,
  manifest: Pick<AssetManifest, "broll">,
): IntentCapabilityResolution {
  const requestedIntent = copyIntent(intent);
  const eligibleAssets = eligibleBrollAssets(manifest).length;
  const broll = resolveLanes(intent.scope, intent.lanes).broll;
  if (broll !== "auto" || eligibleAssets > 0) {
    return { ok: true, requestedIntent, resolvedIntent: copyIntent(intent), decisions: [] };
  }
  const decision = resolvedDecision(intent, eligibleAssets);
  const resolvedIntent = copyIntent(intent);
  resolvedIntent.lanes.broll = "off";
  resolvedIntent.preset = "custom";
  return { ok: true, requestedIntent, resolvedIntent, decisions: [decision] };
}
