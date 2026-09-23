import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import type { EditPlan } from "../edit-plan";
import {
  applySetGraphicTextV1,
  compileSetGraphicTextV1,
  parseSetGraphicTextV1,
  SET_GRAPHIC_TEXT_MAX_LENGTH,
  type SetGraphicTextV1,
} from "../set-graphic-text-v1";

function fixture(): EditPlan & Record<string, unknown> {
  return {
    planVersion: 4,
    target: { mode: "longform" },
    cutTrack: [{ sourceId: "source-1", start: 0, end: 12 }],
    graphicsTrack: [
      {
        id: "g-00000001",
        outStart: 1,
        outEnd: 3,
        kind: "statement-card",
        anchor: "own-screen",
        spec: { text: "Before", bg: "dark" },
        reason: "State the opening thesis clearly.",
      },
      {
        id: "g-00000002",
        outStart: 5,
        outEnd: 7,
        kind: "glass-rail",
        spec: { title: "Untouched rail" },
      },
    ],
    music: { enabled: false },
    customSidecar: { preserved: true },
  };
}

function operation(overrides: Partial<SetGraphicTextV1> = {}): unknown {
  return {
    schemaVersion: 1,
    operation: "SetGraphicTextV1",
    target: { lane: "graphicsTrack", id: "g-00000001" },
    text: "After",
    expectedCurrentText: "Before",
    ...overrides,
  };
}

function strictOperationValidation(): void {
  assert.throws(() => parseSetGraphicTextV1({
    ...(operation() as object), surprise: true,
  }), /unsupported fields: surprise/);
  const inherited = Object.create(operation() as object) as object;
  assert.throws(() => parseSetGraphicTextV1(inherited), /missing fields/);
  assert.throws(() => parseSetGraphicTextV1(operation({
    target: { lane: "graphicsTrack", id: "bad-id", extra: true } as never,
  })), /unsupported fields: extra/);
  assert.throws(() => parseSetGraphicTextV1(operation({
    target: { lane: "cuts", id: "g-00000001" } as never,
  })), /lane must be graphicsTrack/);
  assert.throws(() => parseSetGraphicTextV1(operation({
    target: { lane: "graphicsTrack", id: "bad-id" },
  })), /stable graphic id/);
  for (const text of [undefined, null, 7, {}, []]) {
    assert.throws(() => parseSetGraphicTextV1(operation({ text: text as never })), /must be a string/);
  }
  for (const text of ["", " ", "\n\t"]) {
    assert.throws(() => parseSetGraphicTextV1(operation({ text })), /must not be empty/);
  }
  assert.doesNotThrow(() => parseSetGraphicTextV1(operation({
    text: "😀".repeat(SET_GRAPHIC_TEXT_MAX_LENGTH),
  })));
  assert.throws(() => parseSetGraphicTextV1(operation({
    text: "😀".repeat(SET_GRAPHIC_TEXT_MAX_LENGTH + 1),
  })), /exceeds 1000 characters/);
}

function schemaMatchesRuntimeEnvelope(): void {
  const schemaPath = path.join(process.cwd(), "schemas/producer/set-graphic-text-v1.schema.json");
  const schema = JSON.parse(readFileSync(schemaPath, "utf8")) as {
    additionalProperties: boolean;
    properties: Record<string, Record<string, unknown>>;
  };
  assert.equal(schema.additionalProperties, false);
  assert.equal(schema.properties.schemaVersion.const, 1);
  assert.equal(schema.properties.operation.const, "SetGraphicTextV1");
  assert.equal(schema.properties.text.maxLength, SET_GRAPHIC_TEXT_MAX_LENGTH);
}

strictOperationValidation();
schemaMatchesRuntimeEnvelope();
const parent = fixture(), before = structuredClone(parent);
assert.throws(() => applySetGraphicTextV1(parent, operation()), /retired.*HyperFrames/);
assert.throws(() => compileSetGraphicTextV1(parent, structuredClone(parent)), /retired.*HyperFrames/);
assert.deepEqual(parent, before);
console.log("set-graphic-text-v1.test.ts: historical decoding and retirement assertions passed");
