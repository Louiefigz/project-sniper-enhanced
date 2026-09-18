import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { createElement } from "react";
import { renderToString } from "react-dom/server";
import { useGraphicEdits } from "../../../components/producer/editor/use-graphic-edits";
import { COMPS_CATALOG } from "../comps-catalog";
import type { EditPlan } from "../edit-plan";

const marker = COMPS_CATALOG.find((entry) => entry.kind === "section-marker")!;

function editor(initial: EditPlan) {
  const planRef = { current: initial };
  let edits: ReturnType<typeof useGraphicEdits> | undefined;
  function Harness() {
    // Test-only SSR capture; callbacks run afterward, never during rendering.
    // eslint-disable-next-line react-hooks/globals
    edits = useGraphicEdits({
      planRef,
      timeRef: { current: 5 },
      durationRef: { current: 20 },
      selected: "existing",
      setSelected: () => undefined,
      mutatePlan: (change) => { planRef.current = change(planRef.current); },
    });
    return null;
  }
  renderToString(createElement(Harness));
  assert.ok(edits);
  return { planRef, edits };
}

test("section-marker catalog role matches its actual alpha template", () => {
  const source = readFileSync(path.join(process.cwd(),
    "templates/motion/compositions/section-marker.html"), "utf8");
  assert.match(source, /small alpha overlay over the live head/);
  assert.match(source, /background: transparent/);
  assert.equal(marker.ownScreen, false);
});

test("actual editor insert creates free-band without migrating saved role or color", () => {
  const saved = {
    id: "existing", kind: "section-marker", anchor: "own-screen",
    outStart: 1, outEnd: 4,
    spec: { num: "Saved", line1: "Authored", line2: "Copy", accent: "#123456" },
  };
  const initial: EditPlan = { graphicsTrack: [saved] };
  const before = structuredClone(initial);
  const { planRef, edits } = editor(initial);
  edits.addGraphic(marker);
  assert.deepEqual(initial, before);
  assert.deepEqual(planRef.current.graphicsTrack?.[0], saved);
  const inserted = planRef.current.graphicsTrack?.[1];
  assert.equal(inserted?.anchor, "free-band");
  assert.deepEqual(inserted?.spec, marker.defaultSpec);
  assert.notEqual(inserted?.spec, marker.defaultSpec);
});

test("duplicating a saved marker preserves its authored anchor and color", () => {
  const saved = { id: "existing", kind: "section-marker", anchor: "own-screen",
    outStart: 1, outEnd: 4, spec: { accent: "#123456", line1: "Saved" } };
  const { planRef, edits } = editor({ graphicsTrack: [saved] });
  edits.duplicateSelected();
  const copy = planRef.current.graphicsTrack?.[1];
  assert.equal(copy?.anchor, saved.anchor);
  assert.deepEqual(copy?.spec, saved.spec);
  assert.notEqual(copy?.id, saved.id);
});
