import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

function source(relative: string): string {
  return readFileSync(path.join(process.cwd(), relative), "utf8");
}

const sections = source("src/components/producer/editor/editor-view-sections.tsx");
const actions = source("src/components/producer/editor/use-plan-actions.ts");
const timeline = source("src/components/producer/editor/timeline.tsx");

assert.match(sections, /Show Palmier export/);
assert.match(sections, /final\.palmier\.mp4/);
assert.match(sections, /Unapproved Sniper review copy/);
assert.match(sections, /showPlanLanes=\{!palmier && !palmierPrimary\}/,
  "managed Palmier projects keep Sniper as a lightweight read-only preview");
assert.match(sections, /locked=\{editor\.planState\.editingLocked \|\| palmier\}/);
assert.match(actions, /artifact === "palmier"/);
assert.match(actions, /final\.palmier\.mp4/);
assert.match(timeline, /read-only reference preview · make timeline changes in Palmier or use Ask AI/);
assert.match(timeline, /sel && showPlanLanes && !p\.locked/);

const player = source("src/components/producer/editor/player-pane.tsx");
assert.match(player, /previewAuthority === "unapproved"/);
assert.match(player, /Unapproved review copy/);

console.log("editor-artifact-consistency.test.ts: all assertions passed");
