import {
  INTENT_PRESETS,
  mimicLaneConflicts,
  presetToIntent,
  validateReferenceIntent,
  type ProjectIntent,
  type ReferenceIntent,
} from "@/lib/producer/intent-presets";

function allMimicLanesAvailable(intent: ProjectIntent): boolean {
  return mimicLaneConflicts(intent).length === 0;
}

function presetForReference(reference: ReferenceIntent) {
  const id = reference.mode === "short" ? "produced-short" : "longform-produced";
  const preset = INTENT_PRESETS.find((candidate) => candidate.id === id);
  if (!preset) throw new Error(`Required reference preset is missing: ${id}`);
  return preset;
}

function compatible(intent: ProjectIntent, reference: ReferenceIntent): boolean {
  if (intent.mode !== reference.mode) return false;
  if (reference.strategy === "mimic" && !allMimicLanesAvailable(intent)) return false;
  return !intent.style && !intent.pace;
}

function attachReference(intent: ProjectIntent, reference: ReferenceIntent): ProjectIntent {
  const base = { ...intent };
  delete base.style;
  delete base.pace;
  return {
    ...base,
    mode: reference.mode,
    music: intent.music ?? false,
    reference,
  };
}

export function intentForReference(reference: ReferenceIntent): ProjectIntent {
  reference = validateReferenceIntent(reference);
  return attachReference(presetToIntent(presetForReference(reference), reference.mode), reference);
}

export function applyReferenceChange(intent: ProjectIntent, reference: ReferenceIntent): {
  intent: ProjectIntent;
  cleared: boolean;
} {
  reference = validateReferenceIntent(reference);
  if (compatible(intent, reference)) return { intent: attachReference(intent, reference), cleared: false };
  const clean = { ...intent };
  delete clean.reference;
  return { intent: clean, cleared: true };
}
