import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { plannerAdvicePlan } from "../guided-proposal-inputs";
import type { AcceptedGuidedCut } from "../guided-raw-treatment-store";

function fixture() {
  const target = { mode: "longform", scope: "produced", style: "overlay-rich",
    visualProfile: "retired-profile", lanes: { broll: "off" } };
  const plan = { target, cutTrack: [{ sourceId: "TEST", start: 0, end: 4 }] };
  const cut = { plan: { value: plan } } as unknown as AcceptedGuidedCut;
  const advice = { recommendedTargetFields: { graphicsStyle: "catalog-first",
    graphicsStyleRationale: "TEST choose a current catalog source" }, removeTargetFields: ["style", "visualProfile"] };
  return { cut, plan, advice };
}

test("current advisor removes both retired fields only in its isolated planner copy", () => {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-advice-contract-")));
  try {
    const { cut, plan, advice } = fixture(), before = structuredClone(plan);
    const file = plannerAdvicePlan(cut, root, advice, "stage");
    const staged = JSON.parse(readFileSync(file, "utf8"));
    assert.equal(staged.target.graphicsStyle, "catalog-first");
    assert.equal(Object.hasOwn(staged.target, "style"), false);
    assert.equal(Object.hasOwn(staged.target, "visualProfile"), false);
    assert.equal(staged.target.mode, "longform");
    assert.equal(staged.target.scope, "produced");
    assert.deepEqual(staged.target.lanes, { broll: "off" });
    assert.deepEqual(staged.cutTrack, plan.cutTrack);
    assert.deepEqual(plan, before);
    assert.equal(plannerAdvicePlan(cut, root, advice, "observe"), file);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("advice cannot erase mode, scope, source policy or arbitrary target fields", () => {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-advice-reject-")));
  try {
    const { cut, advice } = fixture();
    for (const removeTargetFields of [null, "style", ["mode"], ["scope"], ["lanes"], ["graphicsStyle"], ["unknown"]]) {
      assert.throws(() => plannerAdvicePlan(cut, root, { ...advice, removeTargetFields }, "stage"), /Invalid style-advice removals/);
      assert.deepEqual(readdirSync(root), []);
    }
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("later advice changes cannot silently replace an already staged planner input", () => {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-advice-observe-")));
  try {
    const { cut, advice } = fixture();
    const file = plannerAdvicePlan(cut, root, advice, "stage"), bytes = readFileSync(file);
    advice.recommendedTargetFields.graphicsStyleRationale = "TEST changed recommendation";
    assert.throws(() => plannerAdvicePlan(cut, root, advice, "observe"), /differs from/);
    assert.deepEqual(readFileSync(file), bytes);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
