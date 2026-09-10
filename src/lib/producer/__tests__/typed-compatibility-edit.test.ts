import assert from "node:assert/strict";
import type { EditPlan } from "../edit-plan";
import { canonicalJsonSha256 } from "../../server/auto-edit-hash";
import { compileTypedCompatibilityEdit } from
  "../../../app/api/producer/ai-edit/typed-compatibility-edit";

function parent(): EditPlan {
  return {
    planVersion: 3,
    target: { mode: "longform" },
    cutTrack: [{ sourceId: "raw", start: 0, end: 8 }],
    graphicsTrack: [{
      id: "g-00000001", kind: "statement-card",
      outStart: 1, outEnd: 3, spec: { text: "Before", bg: "blue" },
    }, {
      id: "g-00000002", kind: "glass-rail",
      outStart: 4, outEnd: 6, spec: { title: "Rail" },
    }],
  };
}

function typedTextChangeIsSelected(): void {
  const before = parent();
  const after = structuredClone(before);
  if (!after.graphicsTrack?.[0].spec) throw new Error("broken fixture");
  after.graphicsTrack[0].spec.text = "After";
  const compiled = compileTypedCompatibilityEdit(before, after);
  assert.equal(compiled?.kind, "set-graphic-text");
  assert.equal(compiled?.operation.text, "After");
  assert.equal(compiled?.operation.expectedCurrentText, "Before");
  assert.equal(compiled?.operationHash, canonicalJsonSha256(compiled?.operation));
}

function adjacentMutationCannotFallBack(): void {
  const before = parent();
  const after = structuredClone(before);
  if (!after.graphicsTrack?.[0].spec || !after.graphicsTrack[0]) {
    throw new Error("broken fixture");
  }
  after.graphicsTrack[0].spec.text = "After";
  after.graphicsTrack[0].outStart = 2;
  assert.throws(
    () => compileTypedCompatibilityEdit(before, after),
    /changes more than graphicsTrack\[id\]\.spec\.text/,
  );
}

function otherGraphicsRemainOnLegacyPath(): void {
  const before = parent();
  const rail = structuredClone(before);
  if (!rail.graphicsTrack?.[1].spec) throw new Error("broken fixture");
  rail.graphicsTrack[1].spec.title = "Updated rail";
  assert.equal(compileTypedCompatibilityEdit(before, rail), null);

  const added = structuredClone(before);
  added.graphicsTrack?.push({
    id: "g-00000003", kind: "statement-card",
    outStart: 6, outEnd: 8, spec: { text: "New card" },
  });
  assert.equal(compileTypedCompatibilityEdit(before, added), null);
}

function reorderedTextSwapCannotBypassTypedPath(): void {
  const before = parent();
  before.graphicsTrack?.push({
    id: "g-00000003", kind: "statement-card",
    outStart: 6, outEnd: 8, spec: { text: "Second" },
  });
  const after = structuredClone(before);
  if (!after.graphicsTrack) throw new Error("broken fixture");
  const first = after.graphicsTrack[0];
  const second = after.graphicsTrack[2];
  after.graphicsTrack = [
    { ...second, spec: { ...second.spec, text: "Before" } },
    after.graphicsTrack[1],
    { ...first, spec: { ...first.spec, text: "Second" } },
  ];
  assert.throws(
    () => compileTypedCompatibilityEdit(before, after),
    /cannot change or reorder graphic ids/,
  );
}

function legacyIdlessTextTouchFailsClosed(): void {
  const before = parent();
  const after = structuredClone(before);
  if (!before.graphicsTrack?.[0] || !after.graphicsTrack?.[0].spec) {
    throw new Error("broken fixture");
  }
  delete before.graphicsTrack[0].id;
  delete after.graphicsTrack[0].id;
  after.graphicsTrack[0].spec.text = "After";
  after.graphicsTrack[0].outStart = 2;
  assert.throws(
    () => compileTypedCompatibilityEdit(before, after),
    /missing or invalid stable id/,
  );
}

function reorderedIdlessCardsFailClosed(): void {
  const before = parent();
  before.graphicsTrack = [{
    kind: "statement-card", outStart: 1, outEnd: 2, spec: { text: "First" },
  }, {
    kind: "statement-card", outStart: 3, outEnd: 4, spec: { text: "Second" },
  }];
  const after = structuredClone(before);
  if (!after.graphicsTrack) throw new Error("broken fixture");
  const [first, second] = after.graphicsTrack;
  after.graphicsTrack = [
    { ...second, spec: { ...second.spec, text: "First" } },
    { ...first, spec: { ...first.spec, text: "Second" } },
  ];
  assert.throws(
    () => compileTypedCompatibilityEdit(before, after),
    /missing or invalid stable id/,
  );
}

typedTextChangeIsSelected();
adjacentMutationCannotFallBack();
otherGraphicsRemainOnLegacyPath();
reorderedTextSwapCannotBypassTypedPath();
legacyIdlessTextTouchFailsClosed();
reorderedIdlessCardsFailClosed();
console.log("typed-compatibility-edit.test.ts: all assertions passed");
