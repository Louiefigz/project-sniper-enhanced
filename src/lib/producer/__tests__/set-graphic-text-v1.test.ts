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

function happyPathIsImmutableAndDeterministic(): void {
  const parent = fixture();
  const snapshot = structuredClone(parent);
  const first = applySetGraphicTextV1(parent, operation());
  const second = applySetGraphicTextV1(parent, operation());
  assert.deepEqual(parent, snapshot, "the parent is immutable");
  assert.deepEqual(first, second, "same parent plus operation is deterministic");
  assert.notEqual(first, parent);
  assert.notEqual(first.graphicsTrack, parent.graphicsTrack);
  assert.equal(first.graphicsTrack?.[0].spec?.text, "After");
  assert.equal(first.graphicsTrack?.[0].spec?.bg, "dark");
  assert.equal(first.graphicsTrack?.[1], parent.graphicsTrack?.[1]);
  assert.deepEqual(first.customSidecar, { preserved: true });
}

function compilerProvesTheSinglePathDelta(): void {
  const parent = fixture();
  const candidate = structuredClone(parent);
  if (!candidate.graphicsTrack?.[0].spec) throw new Error("broken fixture");
  candidate.graphicsTrack[0].spec.text = "Compiled copy";
  const compiled = compileSetGraphicTextV1(parent, candidate);
  assert.deepEqual(compiled, {
    schemaVersion: 1,
    operation: "SetGraphicTextV1",
    target: { lane: "graphicsTrack", id: "g-00000001" },
    text: "Compiled copy",
    expectedCurrentText: "Before",
  });
  assert.deepEqual(applySetGraphicTextV1(parent, compiled), candidate);

  const withoutSpec = fixture();
  delete withoutSpec.graphicsTrack?.[0].spec;
  const addedText = structuredClone(withoutSpec);
  if (!addedText.graphicsTrack?.[0]) throw new Error("broken fixture");
  addedText.graphicsTrack[0].spec = { text: "First copy" };
  const addition = compileSetGraphicTextV1(withoutSpec, addedText);
  assert.equal(addition.expectedCurrentText, undefined);
  assert.deepEqual(applySetGraphicTextV1(withoutSpec, addition), addedText);
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

function addressAndPreconditionFailuresAreLoud(): void {
  const missing = fixture();
  delete missing.graphicsTrack?.[0].id;
  assert.throws(() => applySetGraphicTextV1(missing, operation()), /missing or invalid stable id/);

  const duplicate = fixture();
  if (!duplicate.graphicsTrack?.[1]) throw new Error("broken fixture");
  duplicate.graphicsTrack[1].id = "g-00000001";
  assert.throws(() => applySetGraphicTextV1(duplicate, operation()), /duplicate id g-00000001/);

  assert.throws(() => applySetGraphicTextV1(fixture(), operation({
    target: { lane: "graphicsTrack", id: "g-ffffffff" },
  })), /did not match exactly once/);
  assert.throws(() => applySetGraphicTextV1(fixture(), operation({
    target: { lane: "graphicsTrack", id: "g-00000002" },
  })), /only kind=statement-card/);
  assert.throws(() => applySetGraphicTextV1(fixture(), operation({
    expectedCurrentText: "Stale copy",
  })), /precondition failed/);
  assert.throws(() => applySetGraphicTextV1(fixture(), operation({
    text: "Before",
  })), /would not change/);
}

function compilerRejectsEveryBroaderMutation(): void {
  const parent = fixture();
  const cases: Array<[string, (plan: ReturnType<typeof fixture>) => void, RegExp]> = [
    ["top-level", (plan) => { plan.planVersion = 5; }, /outside the requested scope: planVersion/],
    ["second graphic", (plan) => {
      if (!plan.graphicsTrack?.[1].spec) throw new Error("broken fixture");
      plan.graphicsTrack[1].spec.title = "Also changed";
    }, /exactly one changed graphic/],
    ["timing", (plan) => {
      if (!plan.graphicsTrack?.[0]) throw new Error("broken fixture");
      plan.graphicsTrack[0].outStart = 2;
    }, /changes more than/],
    ["kind", (plan) => {
      if (!plan.graphicsTrack?.[0]) throw new Error("broken fixture");
      plan.graphicsTrack[0].kind = "glass-rail";
    }, /targets only kind=statement-card|changes more than/],
    ["id", (plan) => {
      if (!plan.graphicsTrack?.[0]) throw new Error("broken fixture");
      plan.graphicsTrack[0].id = "g-00000003";
    }, /cannot change or reorder graphic ids/],
  ];
  for (const [, mutate, expected] of cases) {
    const candidate = structuredClone(parent);
    if (!candidate.graphicsTrack?.[0].spec) throw new Error("broken fixture");
    candidate.graphicsTrack[0].spec.text = "Changed";
    mutate(candidate);
    assert.throws(() => compileSetGraphicTextV1(parent, candidate), expected);
  }
  const added = structuredClone(parent);
  added.graphicsTrack?.push({
    id: "g-00000003", kind: "statement-card", outStart: 8, outEnd: 10,
    spec: { text: "Added" },
  });
  assert.throws(() => compileSetGraphicTextV1(parent, added), /cannot add or remove graphics/);
  assert.throws(() => compileSetGraphicTextV1(parent, structuredClone(parent)), /without changing/);
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

happyPathIsImmutableAndDeterministic();
compilerProvesTheSinglePathDelta();
strictOperationValidation();
addressAndPreconditionFailuresAreLoud();
compilerRejectsEveryBroaderMutation();
schemaMatchesRuntimeEnvelope();
console.log("set-graphic-text-v1.test.ts: all assertions passed");
