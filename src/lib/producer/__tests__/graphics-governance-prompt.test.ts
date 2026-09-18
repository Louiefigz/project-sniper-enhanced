import assert from "node:assert/strict";
import { test } from "node:test";

import { buildAuthoringPrompt } from
  "../../../app/api/producer/auto-edit/authoring-prompt";
import type { AutoEditCtx } from
  "../../../app/api/producer/auto-edit/stream";
import { visualStorytellingInstructions } from "../visual-storytelling";

function context(scope: AutoEditCtx["scope"] = "produced"): AutoEditCtx {
  return {
    dir: "/tmp/sniper-graphics-governance/producer",
    scope,
    intent: { mode: "longform", lanes: {} },
    planPath: "/tmp/sniper-graphics-governance/producer/edit_plan.json",
    manifestPath: "/tmp/sniper-graphics-governance/source/asset_manifest.json",
    transcriptsDir: "/tmp/sniper-graphics-governance/source",
    templateUsage: {
      schemaVersion: 1,
      path: "/tmp/sniper-graphics-governance/producer/.sniper-learning/runs/unbound/template-usage.json",
      digest: "a".repeat(64),
    },
  };
}

test("produced longform prompt governs style, semantic decisions, and floors", () => {
  const prompt = buildAuthoringPrompt(context(), "codex");
  const style = prompt.indexOf("GRAPHICS STYLE AUTHORITY");
  const planner = prompt.indexOf("3. Lanes");
  assert.ok(style >= 0 && style < planner,
    "style choice and rationale must be persisted before the planner step");
  for (const expected of [
    "target.graphicsStyle",
    "target.graphicsStyleRationale",
    "introSemanticBeats in full",
    "decisionRequired=true",
    "plan.graphicsDecisions row per beatId",
    "compatibleKinds",
    "compatibleKinds contains only forms that can survive the current deterministic gates",
    "compatibleKinds order is NOT catalog rank",
    "preferredKind is the transcript semantics' explicit anatomy preference",
    "formAllocation",
    "deterministic maximum-distinct semantic-preference witness",
    "selectionReason explains why its anatomy fits this beat better than preferredKind",
    "maximumFeasibleDistinctKinds",
    "fails avoidable reuse with a replacement witness",
    "alternativesConsidered",
    "selectionReason",
    "semanticBeatId equals beatId",
    "minimumGraphicHoldS",
    "extend outEnd or start earlier within output bounds",
    "omit decision.graphicId",
    "Never reuse one graphic for two beats",
    "complete resolvedAssets",
    "AT LEAST 4 unique first-minute graphic bindings",
    "this is a floor, not a target",
    "additional strong beats earn treatment",
    'decision="omit" is invalid for a required beat',
    "When the b-roll lane is off, EVERY required beat MUST be a bound graphic",
    "credibility beat MUST be a bound credibility graphic",
    "Duplicate beatId rows are invalid and bind nothing",
    "explicit insufficient-transcript-beats evidence",
    "capped at 8 by 180s",
    "template-usage.json",
    "overusedKinds",
    "underused alternatives in alternativesConsidered",
    "reuseReason quoting this beat's transcript evidence",
    "template_usage_contract.py",
    "TRANSITION DELIVERABLE",
    "author at least one real transitions[] event on an eligible internal intro seam",
    "INTRO SEAM MAP",
    "resolve EVERY internal cut seam",
    "transitionRationale={decision:\"clean-hook\"",
  ]) assert.ok(prompt.includes(expected), expected);
});

test("waived transitions do not demand a transition deliverable", () => {
  const waived = context();
  waived.intent = { mode: "longform", lanes: { transitions: "off" } };
  const prompt = buildAuthoringPrompt(waived, "codex");
  assert.equal(prompt.includes("TRANSITION DELIVERABLE"), false);
  assert.equal(prompt.includes("INTRO SEAM MAP"), false);
});

test("waived or inactive graphics do not demand graphic governance", () => {
  const waived = context();
  waived.intent = { mode: "longform", lanes: { graphics: "off" } };
  for (const ctx of [waived, context("light")]) {
    const prompt = buildAuthoringPrompt(ctx, "codex");
    assert.equal(prompt.includes("GRAPHICS STYLE AUTHORITY"), false);
    assert.equal(prompt.includes("INTRO SEMANTIC DECISIONS"), false);
  }
});

test("short and long writers share explanatory decisions while preserving format and lanes", () => {
  for (const mode of ["short", "longform"] as const) {
    const ctx = context();
    ctx.intent = { mode, lanes: { broll: "off" } };
    const prompt = buildAuthoringPrompt(ctx, "codex");
    const direction = visualStorytellingInstructions(mode);
    assert.ok(prompt.includes(direction));
    assert.equal(prompt.split("VISUAL EXPLANATION — shared directing standard v1.").length, 2);
    assert.match(direction, /exact spoken cue → viewer's question → visible object\/detail/);
    assert.match(direction, /circled, underlined, spotlighted or enlarged/);
    assert.match(direction, /macro layout count is not an editorial quality score/);
    assert.match(prompt, /Per-lane directives/);
    assert.ok(direction.includes(mode === "short" ? "SHORT FORMAT ADAPTATION" : "LONG-FORM ADAPTATION"));
    assert.ok(!direction.includes(mode === "short" ? "LONG-FORM ADAPTATION" : "SHORT FORMAT ADAPTATION"));
  }
  assert.throws(() => visualStorytellingInstructions("portrait"), /stored short or longform/);
  const old = context(); delete old.intent;
  assert.throws(() => buildAuthoringPrompt(old), /stored operator intent requires mode/);
});

test("both formats carry standing coverage, source variety and continuity into every review stage", () => {
  for (const mode of ["short", "longform"] as const) {
    for (const stage of ["author", "plan-review", "rendered-review"] as const) {
      const direction = visualStorytellingInstructions(mode, stage);
      for (const phrase of [
        "complete retained message, including later business arguments and the ending",
        "original source identity, exact source interval and handles",
        "spoken problem, condition and decision relationship",
        "transition duration, easing, source-clock continuity",
        "exact logo/product focus and a settled readable hold",
        "options, not compulsory formats",
        "disabled/operator-owned lanes",
      ]) assert.ok(direction.includes(phrase), `${mode}/${stage}: ${phrase}`);
      if (stage === "author") continue;
      assert.match(direction, /material issue/);
      assert.match(direction, /exact cue|current candidate/);
    }
  }
  const outputReview = visualStorytellingInstructions("longform", "rendered-review");
  assert.match(outputReview, /Stills cannot clear a motion defect/);
  assert.match(outputReview, /Do not transfer approval from an earlier encode/);
  assert.match(visualStorytellingInstructions("short"), /UPSTREAM READINESS/);
  assert.match(visualStorytellingInstructions("longform", "plan-review"),
    /Route material gaps to revision before rendering/);
});
