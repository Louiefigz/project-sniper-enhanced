import {
  INTENT_PRESETS,
  mimicLaneConflicts,
  presetToIntent,
  type ProjectIntent,
  type ReferenceIntent,
} from "@/lib/producer/intent-presets";

const STYLE_PRESETS = {
  caleb: "caleb-light",
  jadenly: "jadenly-produced",
  angela: "angela-involved",
} as const;

function allMimicLanesAvailable(intent: ProjectIntent): boolean {
  return mimicLaneConflicts(intent).length === 0;
}

function presetForReference(reference: ReferenceIntent) {
  const id = reference.strategy === "extend" && reference.targetStyle
    ? STYLE_PRESETS[reference.targetStyle]
    : reference.mode === "short" ? "produced-short" : "longform-produced";
  return INTENT_PRESETS.find((preset) => preset.id === id) ?? INTENT_PRESETS[0];
}

function compatible(intent: ProjectIntent, reference: ReferenceIntent): boolean {
  if (intent.mode !== reference.mode) return false;
  if (reference.strategy === "mimic" && !allMimicLanesAvailable(intent)) return false;
  if (reference.strategy === "extend") {
    const styleOk = !intent.style || intent.style === reference.targetStyle;
    const paceOk = !intent.pace || intent.pace === reference.targetStyle;
    return styleOk && paceOk;
  }
  return !intent.style && !intent.pace;
}

function attachReference(intent: ProjectIntent, reference: ReferenceIntent): ProjectIntent {
  const base = { ...intent };
  delete base.style;
  delete base.pace;
  const extend = reference.strategy === "extend" && reference.targetStyle && reference.mode === "short";
  return {
    ...base,
    mode: reference.mode,
    music: intent.music ?? false,
    reference,
    ...(extend ? { style: reference.targetStyle, pace: reference.targetStyle } : {}),
  };
}

export function intentForReference(reference: ReferenceIntent): ProjectIntent {
  return attachReference(presetToIntent(presetForReference(reference), reference.mode), reference);
}

export function applyReferenceChange(intent: ProjectIntent, reference: ReferenceIntent): {
  intent: ProjectIntent;
  cleared: boolean;
} {
  if (compatible(intent, reference)) return { intent: attachReference(intent, reference), cleared: false };
  const clean = { ...intent };
  delete clean.reference;
  return { intent: clean, cleared: true };
}
