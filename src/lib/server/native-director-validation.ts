/** Prove source/selection bindings; semantic quality remains a separate critic judgment. */
import { CURRENT_DIRECTOR_PLAN_VERSION, directorCriteria, parseNativeDirectorPlan, type DirectorAudit, type DirectorQuote,
  type NativeDirectorPlan, type NativeDirectorPlanV2 } from "@/lib/producer/contracts/native-director-v2";
import type { ProposalEvidence } from "./guided-proposal-evidence";
import { templateSlots, type DirectorCatalog } from "./native-director-library";

export type DirectorInput = Pick<ProposalEvidence, "frameRate" | "totalFrames" | "occurrences" | "target" | "timelineMapHash"> & { rawIntent: string };
/** Sniper design parameter: the longest written opening code accepts (resources/director/README.md, glanceReadable). */
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
  const seen = new Set<string>(), criteria = directorCriteria(plan);
  for (const fill of plan.fills) {
    const text = fill.writtenHook.trim(), words = text.split(/\s+/u);
    if (words.length > MAX_DIRECTOR_HOOK_WORDS || text.split("\n").length > 2 || seen.has(words.join(" ").toLowerCase())) throw new Error(`Director fills require distinct concise screen hooks (at most ${MAX_DIRECTOR_HOOK_WORDS} words/two lines)`);
    seen.add(words.join(" ").toLowerCase());
    const surfaces = { written: text, spoken: plan.spokenOpening.quote, visual: plan.visual.firstPicture };
    const audit = fill.audit as Record<string, DirectorAudit>;
    for (const key of criteria) {
      if (!surfaces[audit[key].surface].includes(audit[key].quote)) throw new Error(`Director ${key} audit cites absent opening evidence`);
    }
  }
  const chosen = plan.fills[plan.chosenFill].audit as Record<string, DirectorAudit>;
  if (criteria.some((key) => !chosen[key].pass)) throw new Error("Selected Director hook failed its criteria audit");
}

function checkedPlan(plan: NativeDirectorPlan, catalog: DirectorCatalog, input: DirectorInput): NativeDirectorPlan {
  const formats = [plan.format, ...plan.format.alternatives];
  if (formats.some((row) => !catalog.formats.some((format) => format.id === row.id))
      || new Set(formats.map((row) => row.id)).size !== formats.length) throw new Error("Director format choices must resolve and be different");
  sourceQuote(plan.payoff, input); sourceQuote(plan.spokenOpening, input);
  if (plan.spokenOpening.occurrenceIds[0] !== 0) throw new Error("Director cannot replace the recorded first words with a stronger invented opener");
  if (plan.visual.exitFrame < 1 || plan.visual.exitFrame > input.totalFrames) throw new Error("Director hook lifetime exceeds the retained Short");
  selectedTemplate(plan, catalog, input); auditFills(plan); return plan;
}

/** A new decision: plan v2 only. No source/default fallback; a failed selection prevents dependent native planning. */
export function validateDirectorPlan(value: unknown, catalog: DirectorCatalog, input: DirectorInput): NativeDirectorPlanV2 {
  const plan = parseNativeDirectorPlan(value);
  if (plan.schemaVersion !== CURRENT_DIRECTOR_PLAN_VERSION) throw new Error("New Director decisions must use plan schema v2 and its opening criteria");
  return checkedPlan(plan, catalog, input) as NativeDirectorPlanV2;
}

/** A retained decision (v1 or v2) re-checked against its own frozen library with the same bindings and audit rules. */
export function validateStoredDirectorPlan(value: unknown, catalog: DirectorCatalog, input: DirectorInput): NativeDirectorPlan {
  return checkedPlan(parseNativeDirectorPlan(value), catalog, input);
}
