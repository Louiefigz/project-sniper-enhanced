/** Director decisions are editable creative plans, never rendered or human quality approval. */
import { exactKeys, objectValue, stringValue } from "./validation";

export const DIRECTOR_CONDITIONS = ["knowledgeGap", "belief", "novelty", "relevance", "clarity"] as const;
export interface DirectorQuote { occurrenceIds: number[]; quote: string }
export interface DirectorAudit { surface: "written" | "spoken" | "visual"; quote: string; reason: string; pass: boolean }
export interface DirectorFill { writtenHook: string; reason: string; audit: Record<typeof DIRECTOR_CONDITIONS[number], DirectorAudit> }
export interface NativeDirectorPlan {
  schemaVersion: 1; viewer: string; problem: string; payoff: DirectorQuote;
  awareness: { level: "unaware" | "problem_aware" | "solution_aware" | "product_aware" | "most_aware"; reason: string };
  format: { id: string; reason: string; alternatives: Array<{ id: string; reason: string }> };
  template: { anchor: string; referenceId: string; reason: string;
    slots: Array<DirectorQuote & { name: string; value: string }>;
    alternatives: Array<{ anchor: string; referenceId: string; reason: string }> };
  spokenOpening: DirectorQuote; fills: DirectorFill[]; chosenFill: number;
  visual: { firstPicture: string; placement: string; contrast: string; reading: string; exitFrame: number; exitReason: string };
}
export interface NativeDirectorReview { schemaVersion: 1; planHash: string; verdict: "pass" | "revise"; findings: string[] }

function record(value: unknown, keys: string[], name: string) {
  const row = objectValue(value, name); exactKeys(row, keys, keys, name); return row;
}
function text(value: unknown, name: string) { return stringValue(value, name, 2000); }
function integer(value: unknown, maximum: number) {
  if (!Number.isSafeInteger(value) || Number(value) < 0 || Number(value) > maximum) throw new Error("Invalid Director integer");
  return Number(value);
}
function list<T>(value: unknown, maximum: number, parse: (row: unknown) => T): T[] {
  if (!Array.isArray(value) || !value.length || value.length > maximum) throw new Error("Director list is missing or exceeds its bound");
  return value.map(parse);
}
function quote(value: unknown): DirectorQuote {
  const row = record(value, ["occurrenceIds", "quote"], "Director source quote");
  return { occurrenceIds: list(row.occurrenceIds, 128, (id) => integer(id, 29999)), quote: text(row.quote, "source quote") };
}
function choice(value: unknown) {
  const row = record(value, ["id", "reason"], "Director format choice");
  return { id: text(row.id, "format id"), reason: text(row.reason, "format reason") };
}
function template(value: unknown): NativeDirectorPlan["template"] {
  const row = record(value, ["anchor", "referenceId", "reason", "slots", "alternatives"], "Director template");
  if (!Array.isArray(row.slots) || row.slots.length > 16) throw new Error("Director slot list is invalid");
  const slots = row.slots.map((value) => {
    const slot = record(value, ["name", "value", "quote", "occurrenceIds"], "Director slot");
    return { name: text(slot.name, "slot name"), value: text(slot.value, "slot value"),
      ...quote({ quote: slot.quote, occurrenceIds: slot.occurrenceIds }) };
  });
  const alternatives = list(row.alternatives, 2, (value) => {
    const alternative = record(value, ["anchor", "referenceId", "reason"], "Director template alternative");
    return { anchor: text(alternative.anchor, "alternative anchor"), referenceId: text(alternative.referenceId, "alternative example"), reason: text(alternative.reason, "alternative rejection reason") };
  });
  return { anchor: text(row.anchor, "hook anchor"), referenceId: text(row.referenceId, "hook example"), reason: text(row.reason, "template reason"), slots, alternatives };
}
function audit(value: unknown): DirectorAudit {
  const row = record(value, ["surface", "quote", "reason", "pass"], "Director condition");
  if (!["written", "spoken", "visual"].includes(String(row.surface)) || typeof row.pass !== "boolean") throw new Error("Invalid Director condition verdict");
  return { surface: row.surface as DirectorAudit["surface"], quote: text(row.quote, "condition evidence"), reason: text(row.reason, "condition reason"), pass: row.pass };
}
function fill(value: unknown): DirectorFill {
  const row = record(value, ["writtenHook", "reason", "audit"], "Director fill");
  const conditions = record(row.audit, [...DIRECTOR_CONDITIONS], "Director condition audit");
  return { writtenHook: stringValue(row.writtenHook, "written hook", 120), reason: text(row.reason, "fill comparison"),
    audit: Object.fromEntries(DIRECTOR_CONDITIONS.map((key) => [key, audit(conditions[key])])) as DirectorFill["audit"] };
}

export function parseNativeDirectorPlan(value: unknown): NativeDirectorPlan {
  const row = record(value, ["schemaVersion", "viewer", "problem", "payoff", "awareness", "format", "template", "spokenOpening", "fills", "chosenFill", "visual"], "Director plan");
  if (row.schemaVersion !== 1) throw new Error("Unsupported Director plan version");
  const format = record(row.format, ["id", "reason", "alternatives"], "Director format");
  const awareness = record(row.awareness, ["level", "reason"], "Director audience awareness");
  if (!["unaware", "problem_aware", "solution_aware", "product_aware", "most_aware"].includes(String(awareness.level))) throw new Error("Invalid Director awareness level");
  const visual = record(row.visual, ["firstPicture", "placement", "contrast", "reading", "exitFrame", "exitReason"], "Director visual plan");
  const fills = list(row.fills, 3, fill);
  if (fills.length < 2) throw new Error("Director must compare two or three fills of the selected template");
  return { schemaVersion: 1, viewer: text(row.viewer, "viewer"), problem: text(row.problem, "viewer problem"), payoff: quote(row.payoff),
    awareness: { level: awareness.level as NativeDirectorPlan["awareness"]["level"], reason: text(awareness.reason, "awareness reason") },
    format: { ...choice({ id: format.id, reason: format.reason }), alternatives: list(format.alternatives, 2, choice) },
    template: template(row.template), spokenOpening: quote(row.spokenOpening), fills, chosenFill: integer(row.chosenFill, fills.length - 1),
    visual: { firstPicture: text(visual.firstPicture, "first picture"), placement: text(visual.placement, "hook placement"),
      contrast: text(visual.contrast, "contrast plan"), reading: text(visual.reading, "reading plan"),
      exitFrame: integer(visual.exitFrame, 60000), exitReason: text(visual.exitReason, "hook exit") } };
}

export function parseNativeDirectorReview(value: unknown): NativeDirectorReview {
  const row = record(value, ["schemaVersion", "planHash", "verdict", "findings"], "Director critique");
  if (row.schemaVersion !== 1 || !["pass", "revise"].includes(String(row.verdict))) throw new Error("Invalid Director critique verdict");
  return { schemaVersion: 1, planHash: stringValue(row.planHash, "reviewed plan hash", 64),
    verdict: row.verdict as "pass" | "revise", findings: list(row.findings, 20, (item) => text(item, "critic finding")) };
}
