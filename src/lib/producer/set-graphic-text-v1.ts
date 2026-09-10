import type { EditPlan, GraphicEntry } from "./edit-plan";
import { GRAPHIC_ID_RE } from "./graphic-ids";
import {
  assertSurgicalPlanChange,
  changedPlanFields,
} from "./surgical-edit";

export const SET_GRAPHIC_TEXT_MAX_LENGTH = 1000;

export interface SetGraphicTextV1 {
  schemaVersion: 1;
  operation: "SetGraphicTextV1";
  target: {
    lane: "graphicsTrack";
    id: string;
  };
  text: string;
  expectedCurrentText?: string;
}

type JsonRecord = Record<string, unknown>;

function hasOwn(value: JsonRecord, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function record(value: unknown, label: string): JsonRecord {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as JsonRecord;
}

function exactKeys(
  value: JsonRecord,
  allowed: readonly string[],
  required: readonly string[],
  label: string,
): void {
  const extras = Object.keys(value).filter((key) => !allowed.includes(key));
  if (extras.length) throw new Error(`${label} has unsupported fields: ${extras.join(", ")}`);
  const missing = required.filter((key) => !hasOwn(value, key));
  if (missing.length) throw new Error(`${label} is missing fields: ${missing.join(", ")}`);
}

function boundedText(value: unknown, label: string, nonblank: boolean): string {
  if (typeof value !== "string") throw new Error(`${label} must be a string`);
  if (nonblank && !/\S/u.test(value)) throw new Error(`${label} must not be empty`);
  if (Array.from(value).length > SET_GRAPHIC_TEXT_MAX_LENGTH) {
    throw new Error(`${label} exceeds ${SET_GRAPHIC_TEXT_MAX_LENGTH} characters`);
  }
  return value;
}

/** Runtime parser mirroring the strict SetGraphicTextV1 JSON schema. */
export function parseSetGraphicTextV1(value: unknown): SetGraphicTextV1 {
  const operation = record(value, "SetGraphicTextV1");
  exactKeys(
    operation,
    ["schemaVersion", "operation", "target", "text", "expectedCurrentText"],
    ["schemaVersion", "operation", "target", "text"],
    "SetGraphicTextV1",
  );
  if (operation.schemaVersion !== 1 || operation.operation !== "SetGraphicTextV1") {
    throw new Error("SetGraphicTextV1 has an unsupported version or operation");
  }
  const target = record(operation.target, "SetGraphicTextV1.target");
  exactKeys(target, ["lane", "id"], ["lane", "id"], "SetGraphicTextV1.target");
  if (target.lane !== "graphicsTrack") {
    throw new Error("SetGraphicTextV1.target.lane must be graphicsTrack");
  }
  if (typeof target.id !== "string" || !GRAPHIC_ID_RE.test(target.id)) {
    throw new Error("SetGraphicTextV1.target.id must be a stable graphic id");
  }
  const text = boundedText(operation.text, "SetGraphicTextV1.text", true);
  const expected = hasOwn(operation, "expectedCurrentText")
    ? boundedText(operation.expectedCurrentText, "SetGraphicTextV1.expectedCurrentText", false)
    : undefined;
  return {
    schemaVersion: 1,
    operation: "SetGraphicTextV1",
    target: { lane: "graphicsTrack", id: target.id },
    text,
    ...(expected !== undefined ? { expectedCurrentText: expected } : {}),
  };
}

function addressableTrack(plan: EditPlan, label: string): GraphicEntry[] {
  if (!Array.isArray(plan.graphicsTrack)) {
    throw new Error(`${label}.graphicsTrack must be an array`);
  }
  const seen = new Set<string>();
  for (const value of plan.graphicsTrack) {
    const entry = record(value, `${label}.graphicsTrack entry`);
    if (typeof entry.id !== "string" || !GRAPHIC_ID_RE.test(entry.id)) {
      throw new Error(`${label}.graphicsTrack contains a missing or invalid stable id`);
    }
    if (seen.has(entry.id)) {
      throw new Error(`${label}.graphicsTrack contains duplicate id ${entry.id}`);
    }
    seen.add(entry.id);
  }
  return plan.graphicsTrack;
}

function specAndText(
  entry: GraphicEntry,
  label: string,
): { spec: Record<string, unknown>; text: string | undefined } {
  if (entry.spec === undefined) return { spec: {}, text: undefined };
  const spec = record(entry.spec, `${label}.spec`);
  if (spec.text !== undefined && typeof spec.text !== "string") {
    throw new Error(`${label}.spec.text must be a string when present`);
  }
  return { spec, text: spec.text as string | undefined };
}

function sameValue(left: unknown, right: unknown): boolean {
  return changedPlanFields({ value: left }, { value: right }).length === 0;
}

/** Apply one stable-id statement-card text edit without mutating the input. */
export function applySetGraphicTextV1<T extends EditPlan>(
  plan: T,
  value: unknown,
): T {
  record(plan, "edit plan");
  const operation = parseSetGraphicTextV1(value);
  const track = addressableTrack(plan, "edit plan");
  const matches = track
    .map((entry, index) => ({ entry, index }))
    .filter(({ entry }) => entry.id === operation.target.id);
  if (matches.length !== 1) {
    throw new Error(`graphic id ${operation.target.id} did not match exactly once`);
  }
  const { entry, index } = matches[0];
  if (entry.kind !== "statement-card") {
    throw new Error("SetGraphicTextV1 targets only kind=statement-card");
  }
  const { spec, text } = specAndText(entry, `graphic ${operation.target.id}`);
  if (operation.expectedCurrentText !== undefined
      && text !== operation.expectedCurrentText) {
    throw new Error("SetGraphicTextV1 expectedCurrentText precondition failed");
  }
  if (text === operation.text) throw new Error("SetGraphicTextV1 would not change the plan");
  const nextTrack = [...track];
  nextTrack[index] = { ...entry, spec: { ...spec, text: operation.text } };
  return { ...plan, graphicsTrack: nextTrack };
}

function changedGraphicIndexes(before: GraphicEntry[], after: GraphicEntry[]): number[] {
  const changed: number[] = [];
  for (let index = 0; index < before.length; index += 1) {
    if (before[index].id !== after[index].id) {
      throw new Error("SetGraphicTextV1 cannot change or reorder graphic ids");
    }
    if (!sameValue(before[index], after[index])) changed.push(index);
  }
  return changed;
}

/**
 * Compile an isolated candidate into SetGraphicTextV1, then prove the candidate
 * equals a deterministic reapplication of that one operation to its parent.
 */
export function compileSetGraphicTextV1(
  parent: EditPlan,
  candidate: EditPlan,
): SetGraphicTextV1 {
  const parentRecord = record(parent, "parent edit plan");
  const candidateRecord = record(candidate, "candidate edit plan");
  assertSurgicalPlanChange(parentRecord, candidateRecord, { lanes: ["graphics"] });
  const before = addressableTrack(parent, "parent edit plan");
  const after = addressableTrack(candidate, "candidate edit plan");
  if (before.length !== after.length) {
    throw new Error("SetGraphicTextV1 cannot add or remove graphics");
  }
  const changed = changedGraphicIndexes(before, after);
  if (changed.length !== 1) {
    throw new Error("SetGraphicTextV1 requires exactly one changed graphic");
  }
  const index = changed[0];
  const current = specAndText(before[index], `graphic ${before[index].id}`).text;
  const desired = specAndText(after[index], `graphic ${after[index].id}`).text;
  const operation = parseSetGraphicTextV1({
    schemaVersion: 1,
    operation: "SetGraphicTextV1",
    target: { lane: "graphicsTrack", id: before[index].id },
    text: desired,
    ...(current !== undefined ? { expectedCurrentText: current } : {}),
  });
  const reapplied = applySetGraphicTextV1(parent, operation);
  if (!sameValue(reapplied, candidate)) {
    throw new Error("candidate changes more than graphicsTrack[id].spec.text");
  }
  return operation;
}
