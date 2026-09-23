import assert from "node:assert/strict";
import type { EditPlan } from "../edit-plan";
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

function retiredTextChangeIsRefused(): void {
  const before = parent();
  const after = structuredClone(before);
  if (!after.graphicsTrack?.[0].spec) throw new Error("broken fixture");
  after.graphicsTrack[0].spec.text = "After";
  assert.throws(() => compileTypedCompatibilityEdit(before, after), /retired/);
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
    /retired/,
  );
}

function otherGraphicsRemainOnLegacyPath(): void {
  const before = parent();
  const rail = structuredClone(before);
  if (!rail.graphicsTrack?.[1].spec) throw new Error("broken fixture");
  rail.graphicsTrack[1].spec.title = "Updated rail";
  assert.throws(() => compileTypedCompatibilityEdit(before, rail), /retired/);

  const added = structuredClone(before);
  added.graphicsTrack?.push({
    id: "g-00000003", kind: "statement-card",
    outStart: 6, outEnd: 8, spec: { text: "New card" },
  });
  assert.throws(() => compileTypedCompatibilityEdit(before, added), /retired/);
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
    /retired/,
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
    /retired/,
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
    /retired/,
  );
}

retiredTextChangeIsRefused();
adjacentMutationCannotFallBack();
otherGraphicsRemainOnLegacyPath();
reorderedTextSwapCannotBypassTypedPath();
legacyIdlessTextTouchFailsClosed();
reorderedIdlessCardsFailClosed();
const current = { ...parent(), graphicsTrack: [{ id: "g-00000001", kind: "line-swap", outStart: 1, outEnd: 3, spec: { lineA: "Current" } }] };
assert.equal(compileTypedCompatibilityEdit(current, structuredClone(current)), null);
console.log("typed-compatibility-edit.test.ts: all assertions passed");
