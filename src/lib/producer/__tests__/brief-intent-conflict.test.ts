import assert from "node:assert/strict";
import { briefModeConflict, intentSelectionReady } from "../brief-intent-conflict";

assert.match(briefModeConflict("Make a polished horizontal long video", "short") ?? "", /horizontal/);
assert.match(briefModeConflict("Create a 9:16 Instagram Reel", "longform") ?? "", /vertical/);
assert.equal(briefModeConflict("Create a 60-second vertical video", "short"), null);
assert.equal(briefModeConflict("Make a long-form lesson", "longform"), null);
assert.equal(briefModeConflict("Use the vertical source inside a 16:9 layout", "short"), null,
  "mixed signals require the operator to decide; the heuristic must not guess");
assert.equal(briefModeConflict("Keep the argument concise", "short"), null);

assert.equal(intentSelectionReady({ format: false, style: false }, "", "short"), false,
  "the explanatory draft is never an implicit Short/Light decision");
assert.equal(intentSelectionReady({ format: true, style: false }, "", "short"), false);
assert.equal(intentSelectionReady({ format: true, style: true }, "Make a horizontal long video", "short"), false);
assert.equal(intentSelectionReady({ format: true, style: true }, "Keep the proof points", "longform"), true);

console.log("brief-intent-conflict.test.ts: all assertions passed");
