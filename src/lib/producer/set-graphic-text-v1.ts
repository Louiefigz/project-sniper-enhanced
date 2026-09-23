import type { EditPlan } from "./edit-plan";
import { GRAPHIC_ID_RE } from "./graphic-ids";

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

const RETIRED = "SetGraphicTextV1 is retired with statement-card. Edit the selected HyperFrames catalog component in the native project, then refresh its reviews.";

/** Historical operation decoding remains available; retired visuals cannot be edited into a candidate. */
export function applySetGraphicTextV1<T extends EditPlan>(_plan: T, value: unknown): T {
  parseSetGraphicTextV1(value);
  throw new Error(RETIRED);
}

/** Never compile a new operation whose only target was a removed house template. */
export function compileSetGraphicTextV1(_parent: EditPlan, _candidate: EditPlan): SetGraphicTextV1 {
  void _parent;
  void _candidate;
  throw new Error(RETIRED);
}
