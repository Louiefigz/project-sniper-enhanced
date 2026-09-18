import { exactKeys, objectValue, stringValue } from "./validation";

export interface ProposalClauseV2 {
  start: number; end: number; quote: string;
  disposition: "supported" | "ambiguous" | "unsupported" | "cut-affecting";
  rationale: string; operationIndices: number[];
}
export interface ProposalBeatV2 {
  startAnchor: number; endAnchorExclusive: number;
  purpose: "opening" | "body" | "closing"; summary: string; supportsBeatIndices: number[];
}
export interface ProposalOperationV2 {
  type: "catalog-graphic" | "grade" | "preserve-cut";
  clauseIndex: number; beatIndex: number | null;
  catalogKind: string | null; variables: Array<{ name: string; value: string | number | boolean }> | null;
  grade: "warm" | "none" | null;
  startAnchor: number | null; endAnchorExclusive: number | null;
}
export interface TreatmentProposalV2 {
  schemaVersion: 2; summary: string; clauses: ProposalClauseV2[]; beats: ProposalBeatV2[];
  operations: ProposalOperationV2[]; openingEndAnchor: number | null; continuityEndAnchor: number | null;
  audioPolicy: "preserve-full-program"; colorPolicy: "preserve" | "warm" | "none";
}

export function proposalInteger(value: unknown, label: string, maximum = 100_000): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0 || value > maximum) {
    throw new Error(`${label} must be a bounded nonnegative integer`);
  }
  return value;
}
function indices(value: unknown, label: string): number[] {
  if (!Array.isArray(value) || value.length > 128) throw new Error(`${label} must be bounded`);
  const result = value.map((item) => proposalInteger(item, label, 127));
  if (new Set(result).size !== result.length) throw new Error(`${label} has duplicate references`);
  return result;
}
function list<T>(value: unknown, label: string, parser: (value: unknown) => T): T[] {
  if (!Array.isArray(value) || value.length > 128) throw new Error(`${label} must be a bounded array`);
  return value.map(parser);
}
function clause(value: unknown): ProposalClauseV2 {
  const row = objectValue(value, "proposal clause"), keys = ["start", "end", "quote", "disposition", "rationale", "operationIndices"];
  exactKeys(row, keys, keys, "proposal clause");
  if (!["supported", "ambiguous", "unsupported", "cut-affecting"].includes(String(row.disposition))) throw new Error("Invalid proposal clause disposition");
  return { start: proposalInteger(row.start, "clause.start", 20_000), end: proposalInteger(row.end, "clause.end", 20_000),
    quote: stringValue(row.quote, "clause.quote", 20_000), disposition: row.disposition as ProposalClauseV2["disposition"],
    rationale: stringValue(row.rationale, "clause.rationale", 2000), operationIndices: indices(row.operationIndices, "clause operations") };
}
function beat(value: unknown): ProposalBeatV2 {
  const row = objectValue(value, "proposal beat"), keys = ["startAnchor", "endAnchorExclusive", "purpose", "summary", "supportsBeatIndices"];
  exactKeys(row, keys, keys, "proposal beat");
  if (!["opening", "body", "closing"].includes(String(row.purpose))) throw new Error("Invalid beat purpose");
  return { startAnchor: proposalInteger(row.startAnchor, "startAnchor", 60001), endAnchorExclusive: proposalInteger(row.endAnchorExclusive, "endAnchorExclusive", 60001),
    purpose: row.purpose as ProposalBeatV2["purpose"], summary: stringValue(row.summary, "beat summary", 2000),
    supportsBeatIndices: indices(row.supportsBeatIndices, "supporting beat references") };
}
function operation(value: unknown): ProposalOperationV2 {
  const row = objectValue(value, "proposal operation"), keys = ["type", "clauseIndex", "beatIndex", "catalogKind", "variables", "grade", "startAnchor", "endAnchorExclusive"];
  exactKeys(row, keys, keys, "proposal operation");
  if (!["catalog-graphic", "grade", "preserve-cut"].includes(String(row.type))) throw new Error("Unsupported proposal operation");
  const result = { type: row.type as ProposalOperationV2["type"], clauseIndex: proposalInteger(row.clauseIndex, "clauseIndex", 127),
    beatIndex: row.beatIndex === null ? null : proposalInteger(row.beatIndex, "beatIndex", 127),
    catalogKind: row.catalogKind === null ? null : stringValue(row.catalogKind, "catalogKind", 100),
    variables: row.variables === null ? null : list(row.variables, "graphic variables", variable),
    grade: row.grade as ProposalOperationV2["grade"],
    startAnchor: row.startAnchor === null ? null : proposalInteger(row.startAnchor, "startAnchor", 60001),
    endAnchorExclusive: row.endAnchorExclusive === null ? null : proposalInteger(row.endAnchorExclusive, "endAnchorExclusive", 60001) };
  if (result.type === "catalog-graphic" && (result.beatIndex === null || !result.catalogKind || !result.variables?.length || result.grade !== null || result.startAnchor === null || result.endAnchorExclusive === null)
      || result.type === "grade" && (!["none", "warm"].includes(String(result.grade)) || result.catalogKind !== null || result.variables !== null || result.beatIndex !== null || result.startAnchor !== null || result.endAnchorExclusive !== null)
      || result.type === "preserve-cut" && Object.values({ ...result, type: null, clauseIndex: null }).some((item) => item !== null)) {
    throw new Error("Proposal operation fields do not match its closed type");
  }
  return result;
}

function variable(value: unknown): { name: string; value: string | number | boolean } {
  const row = objectValue(value, "catalog variable"); exactKeys(row, ["name", "value"], ["name", "value"], "catalog variable");
  if ((typeof row.value !== "string" && typeof row.value !== "number" && typeof row.value !== "boolean")
      || (typeof row.value === "string" && row.value.length > 2000) || (typeof row.value === "number" && !Number.isFinite(row.value))) {
    throw new Error("Catalog variable must be a bounded scalar");
  }
  return { name: stringValue(row.name, "variable name", 100), value: row.value };
}

/** Closed structured candidate only. Semantic/composition/full-program review remains mandatory. */
export function parseTreatmentProposalV2(value: unknown): TreatmentProposalV2 {
  const row = objectValue(value, "TreatmentProposalV2");
  const keys = ["schemaVersion", "summary", "clauses", "beats", "operations", "openingEndAnchor", "continuityEndAnchor", "audioPolicy", "colorPolicy"];
  exactKeys(row, keys, keys, "TreatmentProposalV2");
  if (row.schemaVersion !== 2 || row.audioPolicy !== "preserve-full-program" || !["preserve", "warm", "none"].includes(String(row.colorPolicy))) {
    throw new Error("Proposal attempts an unsupported audio/color policy");
  }
  return { schemaVersion: 2, summary: stringValue(row.summary, "proposal summary", 2000), clauses: list(row.clauses, "clauses", clause),
    beats: list(row.beats, "beats", beat), operations: list(row.operations, "operations", operation),
    openingEndAnchor: row.openingEndAnchor === null ? null : proposalInteger(row.openingEndAnchor, "openingEndAnchor", 60001),
    continuityEndAnchor: row.continuityEndAnchor === null ? null : proposalInteger(row.continuityEndAnchor, "continuityEndAnchor", 60001),
    audioPolicy: "preserve-full-program", colorPolicy: row.colorPolicy as TreatmentProposalV2["colorPolicy"] };
}

/** UTF-16 spans exhaust every original character; no prose disappears behind a compiled flag. */
export function assertProposalClauseCoverage(proposal: { clauses: ProposalClauseV2[]; operations: Array<{ clauseIndex: number }> }, rawIntent: string): void {
  let cursor = 0;
  for (const [index, item] of proposal.clauses.entries()) {
    if (item.start !== cursor || item.end <= item.start || rawIntent.slice(item.start, item.end) !== item.quote
        || /[\uD800-\uDBFF]/u.test(rawIntent[item.end - 1] ?? "") && /[\uDC00-\uDFFF]/u.test(rawIntent[item.end] ?? "")) {
      throw new Error("Proposal omitted, split a Unicode character, or rewrote original request text");
    }
    if ((item.disposition === "supported") !== (item.operationIndices.length > 0)) throw new Error("Supported clauses need operations; blocked clauses cannot execute");
    if (item.operationIndices.some((id) => proposal.operations[id]?.clauseIndex !== index)) throw new Error("Proposal clause/operation references disagree");
    cursor = item.end;
  }
  if (cursor !== rawIntent.length) throw new Error("Proposal does not exhaust the original request");
  if (proposal.operations.some((item, id) => !proposal.clauses[item.clauseIndex]?.operationIndices.includes(id))) throw new Error("Proposal has an unrequested operation");
}
