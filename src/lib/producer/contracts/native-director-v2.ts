/**
 * Director plan schema v2: Sniper's six opening criteria (resources/director/README.md).
 * Director decisions are editable creative plans, never rendered or human quality approval.
 * Every new decision is v2; the parser also reads retained v1 plans (native-director-v1.ts).
 */
import { exactKeys, objectValue, stringValue } from "./validation";
import { LEGACY_V1_AUDIT_KEYS, LEGACY_V1_AWARENESS } from "./native-director-v1";

/** Evaluation order: truth, then the promise the Short must keep, then attention, then execution. */
export const DIRECTOR_CRITERIA = ["supportedClaim", "answerablePromise", "viewerStake", "concreteDetail",
  "channelAgreement", "glanceReadable"] as const;
/** How much of the problem the opening must establish before its promise makes sense. */
export const DIRECTOR_VIEWER_START = ["problem_unseen", "problem_aware", "solution_aware"] as const;
export const CURRENT_DIRECTOR_PLAN_VERSION = 2;

export interface DirectorQuote { occurrenceIds: number[]; quote: string }
export interface DirectorAudit { surface: "written" | "spoken" | "visual"; quote: string; reason: string; pass: boolean }
export interface DirectorFill<K extends string = typeof DIRECTOR_CRITERIA[number]> {
  writtenHook: string; reason: string; audit: Record<K, DirectorAudit>;
}
interface DirectorPlanBody {
  viewer: string; problem: string; payoff: DirectorQuote;
  format: { id: string; reason: string; alternatives: Array<{ id: string; reason: string }> };
  template: { anchor: string; referenceId: string; reason: string;
    slots: Array<DirectorQuote & { name: string; value: string }>;
    alternatives: Array<{ anchor: string; referenceId: string; reason: string }> };
  spokenOpening: DirectorQuote; chosenFill: number;
  visual: { firstPicture: string; placement: string; contrast: string; reading: string; exitFrame: number; exitReason: string };
}
export interface NativeDirectorPlanV2 extends DirectorPlanBody {
  schemaVersion: 2; awareness: { level: typeof DIRECTOR_VIEWER_START[number]; reason: string }; fills: DirectorFill[];
}
/** A retained pre-2026-09-18 decision; read-only, never produced by the current Director. */
export interface NativeDirectorPlanV1 extends DirectorPlanBody {
  schemaVersion: 1; awareness: { level: typeof LEGACY_V1_AWARENESS[number]; reason: string };
  fills: Array<DirectorFill<typeof LEGACY_V1_AUDIT_KEYS[number]>>;
}
export type NativeDirectorPlan = NativeDirectorPlanV1 | NativeDirectorPlanV2;
export interface NativeDirectorReview { schemaVersion: 1; planHash: string; verdict: "pass" | "revise"; findings: string[] }

const VERSIONS = {
  1: { criteria: LEGACY_V1_AUDIT_KEYS as readonly string[], levels: LEGACY_V1_AWARENESS as readonly string[] },
  2: { criteria: DIRECTOR_CRITERIA as readonly string[], levels: DIRECTOR_VIEWER_START as readonly string[] },
} as const;

/** The audit keys that apply to a plan's own schema version. */
export function directorCriteria(plan: Pick<NativeDirectorPlan, "schemaVersion">): readonly string[] {
  return VERSIONS[plan.schemaVersion].criteria;
}

function record(value: unknown, keys: readonly string[], name: string) {
  const row = objectValue(value, name); exactKeys(row, [...keys], [...keys], name); return row;
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
function template(value: unknown): DirectorPlanBody["template"] {
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
  const row = record(value, ["surface", "quote", "reason", "pass"], "Director criterion");
  if (!["written", "spoken", "visual"].includes(String(row.surface)) || typeof row.pass !== "boolean") throw new Error("Invalid Director criterion verdict");
  return { surface: row.surface as DirectorAudit["surface"], quote: text(row.quote, "criterion evidence"), reason: text(row.reason, "criterion reason"), pass: row.pass };
}
function fill(value: unknown, criteria: readonly string[]): DirectorFill<string> {
  const row = record(value, ["writtenHook", "reason", "audit"], "Director fill");
  const verdicts = record(row.audit, criteria, "Director criteria audit");
  return { writtenHook: stringValue(row.writtenHook, "written hook", 120), reason: text(row.reason, "fill comparison"),
    audit: Object.fromEntries(criteria.map((key) => [key, audit(verdicts[key])])) };
}
function visual(value: unknown): DirectorPlanBody["visual"] {
  const row = record(value, ["firstPicture", "placement", "contrast", "reading", "exitFrame", "exitReason"], "Director visual plan");
  return { firstPicture: text(row.firstPicture, "first picture"), placement: text(row.placement, "hook placement"),
    contrast: text(row.contrast, "contrast plan"), reading: text(row.reading, "reading plan"),
    exitFrame: integer(row.exitFrame, 60000), exitReason: text(row.exitReason, "hook exit") };
}

/** Parse a current (v2) or retained (v1) plan with the audit keys and viewer levels of its own version. */
export function parseNativeDirectorPlan(value: unknown): NativeDirectorPlan {
  const row = record(value, ["schemaVersion", "viewer", "problem", "payoff", "awareness", "format", "template", "spokenOpening", "fills", "chosenFill", "visual"], "Director plan");
  if (row.schemaVersion !== 1 && row.schemaVersion !== 2) throw new Error("Unsupported Director plan version");
  const version = VERSIONS[row.schemaVersion], format = record(row.format, ["id", "reason", "alternatives"], "Director format");
  const awareness = record(row.awareness, ["level", "reason"], "Director audience awareness");
  if (!version.levels.includes(String(awareness.level))) throw new Error("Invalid Director awareness level");
  const fills = list(row.fills, 3, (item) => fill(item, version.criteria));
  if (fills.length < 2) throw new Error("Director must compare two or three fills of the selected template");
  return { schemaVersion: row.schemaVersion, viewer: text(row.viewer, "viewer"), problem: text(row.problem, "viewer problem"), payoff: quote(row.payoff),
    awareness: { level: String(awareness.level), reason: text(awareness.reason, "awareness reason") },
    format: { ...choice({ id: format.id, reason: format.reason }), alternatives: list(format.alternatives, 2, choice) },
    template: template(row.template), spokenOpening: quote(row.spokenOpening), fills, chosenFill: integer(row.chosenFill, fills.length - 1),
    visual: visual(row.visual) } as NativeDirectorPlan;
}

export function parseNativeDirectorReview(value: unknown): NativeDirectorReview {
  const row = record(value, ["schemaVersion", "planHash", "verdict", "findings"], "Director critique");
  if (row.schemaVersion !== 1 || !["pass", "revise"].includes(String(row.verdict))) throw new Error("Invalid Director critique verdict");
  return { schemaVersion: 1, planHash: stringValue(row.planHash, "reviewed plan hash", 64),
    verdict: row.verdict as "pass" | "revise", findings: list(row.findings, 20, (item) => text(item, "critic finding")) };
}
