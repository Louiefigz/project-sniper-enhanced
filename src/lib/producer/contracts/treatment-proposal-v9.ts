/** Source-bound native Shorts direction. This contract grants no editorial or render approval. */
import { exactKeys, objectValue, stringValue } from "./validation";
import { parseTreatmentProposalV2, proposalInteger, type TreatmentProposalV2 } from "./treatment-proposal-v2";

export const NATIVE_SHORT_ROOT_ID = "native-short";

export interface NativeMessageStep {
  anchor: number; occurrenceId: number; text: string; transitionFrames: number;
}
export interface NativeShortScene {
  id: string; startAnchor: number; endAnchorExclusive: number;
  mechanism: "presenter-hold" | "message-reveal";
  view: "presenter" | "presenter-illustration";
  question: string; object: string; quote: string; occurrenceIds: number[];
  referenceIds: string[]; referenceReason: string; requiredAssetIds: string[];
  before: string[]; steps: NativeMessageStep[]; result: string[];
  readingHoldFrames: number; rationale: string;
}
export interface NativeSceneOperation {
  type: "native-scene"; clauseIndex: number; beatIndex: number; scene: NativeShortScene;
}
export interface TreatmentProposalV9 extends Omit<TreatmentProposalV2, "schemaVersion" | "operations" | "colorPolicy"> {
  schemaVersion: 9; operations: NativeSceneOperation[]; colorPolicy: "preserve";
}

function boundedList<T>(value: unknown, maximum: number, parse: (item: unknown) => T): T[] {
  if (!Array.isArray(value) || value.length > maximum) throw new Error("Native scene list exceeds its bound");
  return value.map(parse);
}
function label(value: unknown): string { return stringValue(value, "native scene label", 160); }
function labels(value: unknown, maximum: number): string[] { return boundedList(value, maximum, label); }

function step(value: unknown): NativeMessageStep {
  const row = objectValue(value, "native step"), keys = ["anchor", "occurrenceId", "text", "transitionFrames"];
  exactKeys(row, keys, keys, "native step");
  const transitionFrames = proposalInteger(row.transitionFrames, "transitionFrames", 60);
  if (!transitionFrames) throw new Error("Native step requires a positive transition");
  return { anchor: proposalInteger(row.anchor, "step anchor", 60001),
    occurrenceId: proposalInteger(row.occurrenceId, "step occurrence", 29999), text: label(row.text), transitionFrames };
}

/** Every field survives parsing; unsupported mechanisms never become a generic title card. */
export function parseNativeShortScene(value: unknown): NativeShortScene {
  const row = objectValue(value, "native scene");
  const keys = ["id", "startAnchor", "endAnchorExclusive", "mechanism", "view", "question", "object", "quote", "occurrenceIds",
    "referenceIds", "referenceReason", "requiredAssetIds", "before", "steps", "result", "readingHoldFrames", "rationale"];
  exactKeys(row, keys, keys, "native scene");
  const id = label(row.id);
  if (!/^[a-z][a-z0-9-]{0,63}$/u.test(id)) throw new Error("Native scene id must be a stable DOM-safe identifier");
  if (id === NATIVE_SHORT_ROOT_ID || /^(source-cut-|dialogue-cut-|caption-|word-)/u.test(id)) {
    throw new Error("Native scene id uses a reserved project, media or caption namespace");
  }
  if (!["presenter-hold", "message-reveal"].includes(String(row.mechanism))
      || !["presenter", "presenter-illustration"].includes(String(row.view))) throw new Error("Unsupported native mechanism or view");
  const scene: NativeShortScene = { id, startAnchor: proposalInteger(row.startAnchor, "scene start", 60001),
    endAnchorExclusive: proposalInteger(row.endAnchorExclusive, "scene end", 60001),
    mechanism: row.mechanism as NativeShortScene["mechanism"], view: row.view as NativeShortScene["view"],
    question: label(row.question), object: label(row.object), quote: stringValue(row.quote, "source quote", 2000),
    occurrenceIds: boundedList(row.occurrenceIds, 128, (item) => proposalInteger(item, "occurrenceId", 29999)),
    referenceIds: labels(row.referenceIds, 8), referenceReason: stringValue(row.referenceReason, "reference fit", 2000),
    requiredAssetIds: labels(row.requiredAssetIds, 8), before: labels(row.before, 3), steps: boundedList(row.steps, 3, step),
    result: labels(row.result, 3), readingHoldFrames: proposalInteger(row.readingHoldFrames, "reading hold", 1800),
    rationale: stringValue(row.rationale, "scene rationale", 2000) };
  if (scene.startAnchor >= scene.endAnchorExclusive || !scene.occurrenceIds.length || !scene.referenceIds.length
      || new Set(scene.occurrenceIds).size !== scene.occurrenceIds.length || new Set(scene.referenceIds).size !== scene.referenceIds.length) {
    throw new Error("Native scene requires a positive window and unique speech/reference bindings");
  }
  if (scene.mechanism === "presenter-hold" && (scene.view !== "presenter" || scene.before.length || scene.steps.length || scene.result.length)
      || scene.mechanism === "message-reveal" && (scene.view !== "presenter-illustration" || !scene.steps.length || !scene.readingHoldFrames)) {
    throw new Error("Native mechanism does not match its visible action and view");
  }
  if (JSON.stringify([...scene.before, ...scene.steps.map((item) => item.text)]) !== JSON.stringify(scene.result)) {
    throw new Error("Native result must preserve the initial objects and every authored message action");
  }
  return scene;
}

/** Reuse base clause/beat validation without persisting a historical execution projection. */
export function parseTreatmentProposalV9(value: unknown): TreatmentProposalV9 {
  const row = objectValue(value, "native proposal");
  if (row.schemaVersion !== 9 || row.colorPolicy !== "preserve") throw new Error("Native proposal requires V9 and preserved color");
  const operations = boundedList(row.operations, 32, (value): NativeSceneOperation => {
    const operation = objectValue(value, "native operation"), keys = ["type", "clauseIndex", "beatIndex", "scene"];
    exactKeys(operation, keys, keys, "native operation");
    if (operation.type !== "native-scene") throw new Error("Unsupported native operation");
    return { type: "native-scene", clauseIndex: proposalInteger(operation.clauseIndex, "clauseIndex", 127),
      beatIndex: proposalInteger(operation.beatIndex, "beatIndex", 127), scene: parseNativeShortScene(operation.scene) };
  });
  const base = parseTreatmentProposalV2({ ...row, schemaVersion: 2, operations: operations.map((item) => ({
    type: "preserve-cut", clauseIndex: item.clauseIndex, beatIndex: null, catalogKind: null,
    variables: null, grade: null, startAnchor: null, endAnchorExclusive: null,
  })) });
  return { ...base, schemaVersion: 9, colorPolicy: "preserve", operations };
}
