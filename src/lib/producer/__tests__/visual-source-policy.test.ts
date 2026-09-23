import assert from "node:assert/strict";
import { test } from "node:test";
import { COMPS_CATALOG } from "../comps-catalog";
import { CATALOG_KINDS, VISUAL_SOURCE_POLICY, VISUAL_SOURCE_POLICY_PATH, assertPlanVisualSources, assertVisualSourceSnapshot } from "../visual-source-policy";
import { INTENT_PRESETS, validateIntent } from "../intent-presets";

test("every UI catalog option is an admitted upstream port; no old preset survives", () => {
  assert.deepEqual(COMPS_CATALOG.map(row => row.kind).sort(), [...CATALOG_KINDS].sort());
  assert.equal(COMPS_CATALOG.length, 7);
  assert.ok(INTENT_PRESETS.every(row => !row.style));
  for (const kind of Object.keys(VISUAL_SOURCE_POLICY.retired)) {
    assert.throws(() => assertPlanVisualSources({ graphicsTrack: [{ kind }] }), /retired/);
  }
  assert.doesNotThrow(() => assertPlanVisualSources({ graphicsTrack: [{ kind: "count-up" }], target: { graphicsStyle: "catalog-first" } }));
});

test("an old immutable snapshot is rejected under current policy", () => {
  const current = "a".repeat(64);
  assert.throws(() => assertVisualSourceSnapshot([], current), /predates/);
  const valid = [{ path: VISUAL_SOURCE_POLICY_PATH, hash: current }];
  assert.doesNotThrow(() => assertVisualSourceSnapshot(valid, current));
  assert.throws(() => assertVisualSourceSnapshot([...valid, { path: "templates/motion/compositions/section-marker.html", hash: current }], current), /retired/);
});

test("old non-HTML preset lanes and global creator styles cannot pass", () => {
  for (const plan of [{ titleCards: [{}] }, { transitions: [{}] }, { target: { visualProfile: "retired-profile" } }, { target: { style: "retired-style" } }]) {
    assert.throws(() => assertPlanVisualSources(plan), /retired/);
  }
  assert.throws(() => validateIntent({ mode: "short", scope: "produced", style: "retired-style" }), /retired/);
  assert.doesNotThrow(() => validateIntent({ mode: "short", scope: "produced" }));
});

test("present invalid styles never silently become the catalog default", () => {
  for (const field of ["style", "visualProfile", "graphicsStyle"]) {
    for (const value of ["", null, false, {}, [], "wallpaper"]) {
      assert.throws(() => assertPlanVisualSources({ target: { [field]: value } }), /catalog-first/);
    }
  }
  for (const target of [undefined, null, {}, { graphicsStyle: "catalog-first" }]) {
    assert.doesNotThrow(() => assertPlanVisualSources({ target }));
  }
});
