import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

function source(relative: string): string {
  return readFileSync(path.join(process.cwd(), relative), "utf8");
}

const editor = source("src/components/producer/editor/use-plan-actions.ts");
const stages = source("src/components/producer/stage-actions.tsx");
const manual = source("src/components/producer/render-step.tsx");
const launcher = source("src/components/producer/use-editor-runtime.ts");
const surface = source("src/components/producer/editor/editor-view-sections.tsx");
const timeline = source("src/components/producer/editor/timeline.tsx");

for (const [label, code] of Object.entries({ editor, stages, manual })) {
  assert.doesNotMatch(code, /\/api\/producer\/(?:assemble|render)["']/,
    `${label} must not bypass controller QC through a direct render route`);
  assert.match(code, /launchAutoEditFromHyperframes/,
    `${label} must enter the deterministic controller through the HyperFrames launcher`);
  assert.match(code, /reviewSavedPlan:\s*true/,
    `${label} must review the current saved plan instead of re-authoring it`);
}
assert.match(launcher, /\/api\/producer\/auto-edit/,
  "the launcher must enter the deterministic auto-edit controller");

assert.ok(
  manual.indexOf("/api/producer/save-plan") < manual.indexOf("launchAutoEditFromHyperframes({"),
  "manual JSON must be saved before its review-only controller launch",
);
assert.match(surface, /\["current", "unapproved"\]\.includes[\s\S]*\? editor\.paths\.videoPath : undefined/,
  "current and explicitly unapproved review copies may be inspected, while stale video stays hidden");
assert.match(timeline, /const visiblePeaks = p\.videoPath \? peaks : \[\]/,
  "removing stale video authority must also hide its cached waveform");

console.log("gui-render-authority.test.ts: all assertions passed");
