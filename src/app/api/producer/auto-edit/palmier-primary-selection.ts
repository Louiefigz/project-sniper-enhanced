import type { AutoEditCtx } from "./stream";
import { resolveLanes, type Lane } from "@/lib/producer/intent-presets";
import {
  SURGICAL_EDIT_LANES,
  type SurgicalEditLane,
} from "@/lib/producer/surgical-edit";
import {
  classifyPalmierWorkspace,
  type PalmierWorkspaceClassification,
} from "../ai-edit/palmier-native-stream";
import type { PalmierNativePromptInput } from "../ai-edit/palmier-native-prompt";

export interface PalmierPrimaryLimitation {
  lane: string;
  fidelity: "approximate" | "partial";
  detail: string;
}

export type PalmierPrimaryBuild =
  | { kind: "legacy" }
  | {
    kind: "governed-plan";
    message: string;
    requiredLanes: string[];
  }
  | {
    kind: "blocked";
    code: "PALMIER_MANAGED_STATE_INVALID" | "PALMIER_NATIVE_INITIAL_UNSUPPORTED";
    message: string;
    unsupported: string[];
  }
  | {
    kind: "native";
    input: PalmierNativePromptInput;
    limitations: PalmierPrimaryLimitation[];
  };

function activeLanes(ctx: AutoEditCtx): Record<Lane, boolean> {
  const resolved = resolveLanes(ctx.scope, ctx.intent?.lanes);
  return Object.fromEntries(
    Object.entries(resolved).map(([lane, directive]) => [lane, directive === "auto"]),
  ) as Record<Lane, boolean>;
}

function nativeScope(ctx: AutoEditCtx, active: Record<Lane, boolean>): SurgicalEditLane[] {
  const wanted = new Set<SurgicalEditLane>(["cuts", "reframe"]);
  if (active.graphics || active.credibility) wanted.add("graphics");
  if (active.motion || active.transitions) wanted.add("motion");
  if (active.captions) wanted.add("captions");
  if (ctx.intent?.audioEnhance) wanted.add("audio");
  return SURGICAL_EDIT_LANES.filter((lane) => wanted.has(lane));
}

function unsupportedLanes(ctx: AutoEditCtx, active: Record<Lane, boolean>): string[] {
  const unsupported: string[] = [];
  if (active.broll) unsupported.push("broll");
  if (ctx.intent?.music === true) unsupported.push("music");
  if (ctx.referenceStudy || ctx.intent?.reference) unsupported.push("reference-mechanics");
  return unsupported;
}

function requiresRichPlan(
  ctx: AutoEditCtx,
  active: Record<Lane, boolean>,
): string[] {
  const required: string[] = [];
  for (const lane of ["graphics", "transitions", "credibility", "broll"] as const) {
    if (active[lane]) required.push(lane);
  }
  if (ctx.intent?.music === true) required.push("music");
  if (ctx.referenceStudy || ctx.intent?.reference) required.push("reference-mechanics");
  return required;
}

function fidelityLimitations(
  ctx: AutoEditCtx,
  active: Record<Lane, boolean>,
): PalmierPrimaryLimitation[] {
  const rows: PalmierPrimaryLimitation[] = [];
  if (active.graphics) rows.push({
    lane: "graphics", fidelity: "partial",
    detail: "Native editable text and layouts are connected; generated cards, shapes, icons, and imported graphic media are not yet connected.",
  });
  if (active.transitions) rows.push({
    lane: "transitions", fidelity: "approximate",
    detail: "Palmier-native keyframed motion is available, but a dedicated seam-transition primitive is not.",
  });
  if (active.credibility) rows.push({
    lane: "credibility", fidelity: "partial",
    detail: "Editable text/layout treatment is available; importing a separate credibility PIP asset is not.",
  });
  if (ctx.intent?.audioEnhance) rows.push({
    lane: "audio", fidelity: "approximate",
    detail: "Palmier denoise and gain are editable; the prior in-house voice-RNN preset is not reproduced exactly.",
  });
  return rows;
}

function initialRequest(
  ctx: AutoEditCtx,
  active: Record<Lane, boolean>,
  lanes: SurgicalEditLane[],
  limitations: PalmierPrimaryLimitation[],
): string {
  return [
    "Create the first complete, editable video directly in the current Palmier source timeline.",
    `Resolved build contract JSON: ${JSON.stringify({
      target: { mode: ctx.intent?.mode ?? null, scope: ctx.scope },
      brief: ctx.intent?.brief ?? null,
      pace: ctx.intent?.pace ?? null,
      style: ctx.intent?.style ?? null,
      activeLanes: active,
      nativeControllerLanes: lanes,
      limitations,
    })}`,
    "Use transcript-grounded cuts, editable native text/captions, restrained motivated keyframes, dialogue cleanup, and delivery-safe framing only where evidence earns them.",
    "Do not invent unsupported b-roll, music, reference mechanics, imported graphics, or transition primitives.",
    "The exact edited candidate must remain an editable Palmier timeline for exported QC and promotion.",
  ].join(" ");
}

export function selectPalmierPrimaryBuild(
  ctx: AutoEditCtx,
  classify: (dir: string) => PalmierWorkspaceClassification = classifyPalmierWorkspace,
): PalmierPrimaryBuild {
  const workspace = classify(ctx.dir);
  if (workspace.state === "absent") return { kind: "legacy" };
  if (workspace.state === "invalid") return {
    kind: "blocked", code: "PALMIER_MANAGED_STATE_INVALID",
    message: `${workspace.error} Refusing to fall back to a stale Sniper plan.`,
    unsupported: [],
  };
  if (workspace.workspaceMode !== "managed-draft"
      || workspace.assetKind !== "source") return {
    kind: "blocked", code: "PALMIER_NATIVE_INITIAL_UNSUPPORTED",
    unsupported: ["editable-source-bootstrap"],
    message: "Palmier-primary initial build requires the managed editable source view. A saved-cut or legacy flat mirror cannot truthfully recover separated edits; create/migrate a source working view first.",
  };
  const active = activeLanes(ctx);
  const requiredLanes = requiresRichPlan(ctx, active);
  if (requiredLanes.length) return {
    kind: "governed-plan",
    requiredLanes,
    message: "This edit requests catalog-backed graphics, seam decisions, cutaways, credibility, music, or studied-reference mechanics. It must use the full transcript-grounded edit-plan and deterministic gate path before Palmier execution; the primitive native planner is not allowed to claim those checked deliverables.",
  };
  const unsupported = unsupportedLanes(ctx, active);
  if (unsupported.length) return {
    kind: "blocked", code: "PALMIER_NATIVE_INITIAL_UNSUPPORTED",
    unsupported,
    message: `Palmier-primary initial build cannot yet reproduce ${unsupported.join(", ")} without silently dropping material intent. Turn those lanes off/operator, or build them manually in Palmier.`,
  };
  const lanes = nativeScope(ctx, active);
  const limitations = fidelityLimitations(ctx, active);
  return {
    kind: "native",
    limitations,
    input: {
      dir: ctx.dir,
      request: initialRequest(ctx, active, lanes, limitations),
      scope: { lanes },
      workflow: "initial-auto-edit",
      evidencePaths: [ctx.manifestPath, ctx.transcriptsDir],
    },
  };
}
