import type { ProjectIntent } from "./intent-presets";
import type { AssetManifest, ManifestSource } from "./types";
import type { AutoEditDeliveryPolicy } from "./auto-edit-delivery-policy";

const SHORT_PLATFORMS = ["tiktok", "reels", "shorts"];
const LONGFORM_PLATFORMS = ["youtube"];

function sourceEnd(source: ManifestSource | undefined, longform: boolean): number {
  const duration = source?.duration ?? 30;
  const usable = Number.isFinite(duration) && duration > 0 ? duration : 30;
  return Number((longform ? usable : Math.min(30, usable)).toFixed(2));
}

function starterTarget(intent: ProjectIntent, durationTargetS: number) {
  const mode = intent.mode;
  return {
    mode,
    graphicsStyle: "catalog-first",
    durationTargetS,
    platforms: mode === "longform" ? LONGFORM_PLATFORMS : SHORT_PLATFORMS,
    scope: intent.scope,
    ...(intent.music !== undefined ? { music: intent.music } : {}),
    ...(intent.excerpt !== undefined ? { excerpt: intent.excerpt } : {}),
    ...(Object.keys(intent.lanes).length ? { lanes: intent.lanes } : {}),
    ...(intent.pace ? { pace: intent.pace } : {}),
    ...(intent.style ? { style: intent.style } : {}),
    ...(intent.shortDirection ? { shortDirection: intent.shortDirection } : {}),
    ...(intent.reference ? {
      referenceId: intent.reference.id,
      referenceStrategy: intent.reference.strategy,
    } : {}),
  };
}

/** Build the editable manual-plan scaffold from the same intent Auto-edit receives. */
export function buildStarterPlan(manifest: AssetManifest, intent: ProjectIntent) {
  const source = manifest.sources[0];
  const longform = intent.mode === "longform";
  const trimOnly = intent.scope === "trim";
  const end = sourceEnd(source, longform);
  return {
    planVersion: 1,
    audioAuthorityMode: "mastered-stereo" as const,
    target: starterTarget(intent, end),
    cutTrack: [{
      sourceId: source?.id ?? "raw-1",
      start: 0,
      end,
      speed: longform ? 1 : 1.1,
      rationale: "",
    }],
    reframe: { strategy: longform ? "none" : "face" },
    titleCards: [], // Titles are selected from the catalog in the native project.
    captions: {
      burn: !trimOnly && !longform,
      style: longform ? "line" : "karaoke",
    },
    brollTrack: [],
    music: { enabled: intent.music === true },
    ...(intent.audioEnhance ? { audioEnhance: intent.audioEnhance } : {}),
  };
}

/** Keep the one-click launch and Recent-project action on one request contract. */
export function buildAutoEditRequest(
  dir: string,
  intent?: ProjectIntent | null,
  deliveryPolicy?: AutoEditDeliveryPolicy,
): Record<string, unknown> {
  if (!intent) {
    throw new Error("Auto Edit requires a stored edit intent; choose Short/Long and an edit level first");
  }
  const body: Record<string, unknown> = { dir, scope: intent.scope };
  if (deliveryPolicy) body.deliveryPolicy = deliveryPolicy;
  body.mode = intent.mode;
  if (intent.excerpt !== undefined) body.excerpt = intent.excerpt;
  body.lanes = intent.lanes;
  if (intent.brief) body.brief = intent.brief;
  if (intent.pace) body.pace = intent.pace;
  if (intent.style) body.style = intent.style;
  if (intent.shortDirection) body.shortDirection = { ...intent.shortDirection };
  if (intent.reference) body.reference = { ...intent.reference };
  if (intent.music !== undefined) body.music = intent.music;
  if (intent.audioEnhance) body.audioEnhance = intent.audioEnhance;
  return body;
}

/** Resume uses the same validated intent contract as a fresh Auto Edit, with
 * one explicit signal for the route to recover from its last safe checkpoint. */
export function buildResumeAutoEditRequest(
  dir: string,
  intent?: ProjectIntent | null,
  deliveryPolicy?: AutoEditDeliveryPolicy,
  workflowPolicy?: "cut-first",
): Record<string, unknown> {
  if (workflowPolicy !== undefined && (workflowPolicy !== "cut-first" || deliveryPolicy !== "mp4-only")) {
    throw new Error("Cut-first continuation requires the saved MP4-only workflow");
  }
  return { ...buildAutoEditRequest(dir, intent, deliveryPolicy), resume: true,
    ...(workflowPolicy ? { workflowPolicy } : {}) };
}
