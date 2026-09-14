/** Prove source/selection bindings; semantic quality remains a separate critic judgment. */
import { DIRECTOR_CONDITIONS, parseNativeDirectorPlan, type DirectorQuote, type NativeDirectorPlan } from "@/lib/producer/contracts/native-director-v1";
import type { ProposalEvidence } from "./guided-proposal-evidence";
import { templateSlots, type DirectorCatalog } from "./native-director-library";

export type DirectorInput = Pick<ProposalEvidence, "frameRate" | "totalFrames" | "occurrences" | "target" | "timelineMapHash"> & { rawIntent: string };
export const MAX_DIRECTOR_HOOK_WORDS = 12;

export function directorInput(rawIntent: string, evidence: ProposalEvidence): DirectorInput {
  return { rawIntent, frameRate: evidence.frameRate, totalFrames: evidence.totalFrames,
    occurrences: evidence.occurrences, target: evidence.target, timelineMapHash: evidence.timelineMapHash };
}

function sourceQuote(row: DirectorQuote, input: DirectorInput): void {
  const words = row.occurrenceIds.map((id) => input.occurrences[id]);
  if (words.some((word, i) => !word || word[0] !== row.occurrenceIds[i] || word[6] !== 0
      || (i > 0 && word[0] !== words[i - 1][0] + 1)) || words.map((word) => word[5]).join(" ") !== row.quote) {
    throw new Error("Director quote must name exact contiguous, unclipped retained source words");
  }
}

function selectedTemplate(plan: NativeDirectorPlan, catalog: DirectorCatalog, input: DirectorInput): void {
  const anchor = catalog.anchors.find((row) => row.id === plan.template.anchor);
  const example = catalog.examples.find((row) => row.id === plan.template.referenceId);
  if (!anchor || !example) throw new Error("Director hook anchor/example does not resolve in its frozen library");
  const alternatives = [plan.template, ...plan.template.alternatives];
  if (alternatives.some((row) => !catalog.anchors.some((item) => item.id === row.anchor)
      || !catalog.examples.some((item) => item.id === row.referenceId))
      || new Set(alternatives.map((row) => `${row.anchor}:${row.referenceId}`)).size !== alternatives.length) throw new Error("Director template shortlist must resolve and contain different choices");
  const required = example.formula ? example.slots : templateSlots(anchor.template);
  const actual = plan.template.slots.map((slot) => slot.name);
  if (new Set(actual).size !== actual.length || [...required].sort().join("\n") !== actual.sort().join("\n")) {
    throw new Error("Director adaptation must fill every source-template slot exactly once");
  }
  for (const slot of plan.template.slots) sourceQuote(slot, input);
  for (const fill of plan.fills) {
    const normalized = fill.writtenHook.replace(/\s+/gu, " ").trim().toLowerCase();
    if (normalized.split(" ").length >= 5 && example.content.toLowerCase().includes(normalized)) throw new Error("Director copied reference wording instead of adapting it");
  }
}

function auditFills(plan: NativeDirectorPlan): void {
  const seen = new Set<string>();
  for (const fill of plan.fills) {
    const text = fill.writtenHook.trim(), words = text.split(/\s+/u);
    if (words.length > MAX_DIRECTOR_HOOK_WORDS || text.split("\n").length > 2 || seen.has(words.join(" ").toLowerCase())) throw new Error(`Director fills require distinct concise screen hooks (at most ${MAX_DIRECTOR_HOOK_WORDS} words/two lines)`);
    seen.add(words.join(" ").toLowerCase());
    const surfaces = { written: text, spoken: plan.spokenOpening.quote, visual: plan.visual.firstPicture };
    for (const key of DIRECTOR_CONDITIONS) {
      const item = fill.audit[key];
      if (!surfaces[item.surface].includes(item.quote)) throw new Error(`Director ${key} audit cites absent opening evidence`);
    }
  }
  if (DIRECTOR_CONDITIONS.some((key) => !plan.fills[plan.chosenFill].audit[key].pass)) throw new Error("Selected Director hook failed its condition audit");
}

/** No source/default fallback: a failed selection prevents dependent native planning. */
export function validateDirectorPlan(value: unknown, catalog: DirectorCatalog, input: DirectorInput): NativeDirectorPlan {
  const plan = parseNativeDirectorPlan(value), formats = [plan.format, ...plan.format.alternatives];
  if (formats.some((row) => !catalog.formats.some((format) => format.id === row.id))
      || new Set(formats.map((row) => row.id)).size !== formats.length) throw new Error("Director format choices must resolve and be different");
  sourceQuote(plan.payoff, input); sourceQuote(plan.spokenOpening, input);
  if (plan.spokenOpening.occurrenceIds[0] !== 0) throw new Error("Director cannot replace the recorded first words with a stronger invented opener");
  if (plan.visual.exitFrame < 1 || plan.visual.exitFrame > input.totalFrames) throw new Error("Director hook lifetime exceeds the retained Short");
  selectedTemplate(plan, catalog, input); auditFills(plan); return plan;
}
