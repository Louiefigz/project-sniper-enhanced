import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

function source(relative: string): string {
  return readFileSync(path.join(process.cwd(), relative), "utf8");
}

const actions = source("src/components/producer/stage-actions.tsx");
const card = source("src/components/producer/project-card.tsx");
const palmier = source("src/components/producer/project-palmier-button.tsx");
const details = source("src/components/producer/project-card-details.tsx");
const runStatus = source("src/components/producer/stage-action-status.tsx");
const recent = source("src/components/producer/recent-projects.tsx");
const activeJobs = source("src/components/producer/active-project-jobs.tsx");

assert.doesNotMatch(actions, /Finish video|Prepare again|Retry generation/);
assert.match(actions, /Resume review & QC/);
assert.match(actions, /Start render & QC/);
assert.match(actions, /Create first edit/);
const workerLabels = [...actions.matchAll(/<RenderPlanAction[^>]*label="([^"]+)"/g)]
  .map((match) => match[1]);
assert.equal(workerLabels.some((label) => /^(Review|Inspect)\b/i.test(label)), false,
  "a Review/Inspect action must never start the detached worker");
assert.match(card, /Inspect Sniper draft/,
  "the saved edit must retain a separate read-only inspection action");
assert.match(card, /Inspect unapproved render/);
assert.match(card, /onClick=\{\(\) => props\.onOpen\(status\.producerDir, p\.title\)\}/,
  "Inspect must open the saved editor view without dispatching pipeline work");
assert.match(actions, /\["generate", "render_plan", "assemble"\]\.includes\(action\)/,
  "legacy saved projects must offer intent recovery instead of a disabled resume action");
assert.match(details, /Continue without cutaways · selected/);
assert.match(details, /Generate with Higgsfield · Not connected/);
assert.match(card, /Inspect Sniper draft/);
assert.match(card, /Open Sniper progress/);
assert.match(card, /Open approved Sniper video/);
assert.match(palmier, /palmierActionLabel/);
assert.match(palmier, /\/api\/producer\/palmier\/workspace/);
assert.doesNotMatch(card, /Take control in Palmier/);
assert.match(card, /Available now/);
assert.match(card, /Working now/);
assert.match(card, /What&apos;s next/);
assert.match(card, /Safe actions/);
assert.match(card, /projectCardPresentation/,
  "continue-card guidance must come from the unified project state presentation");
assert.match(palmier, /status\.palmier\.detail/,
  "opening Palmier must expose the state model's authority explanation");
assert.match(details, /runActive \|\| rescanning/,
  "asset rescan must be disabled while a background job owns the inputs");
assert.match(details, /Stop & keep checkpoint before adding or rescanning/);
assert.match(details, /Technical progress log/);
assert.match(details, /eventTimestamp\(item\.at\)/,
  "technical progress events must display their recorded timestamps");
assert.match(details, /Technical failure details/,
  "plain-language failures must preserve their raw diagnostic behind disclosure");
assert.match(details, /Cut update receipt/);
assert.match(details, /deterministically rebased before lint and review/);
assert.doesNotMatch(runStatus, /Live log/,
  "technical run events belong in the disclosed project details, not the main card");
assert.match(recent, /Continue from the exact saved stage/);
assert.match(recent, /projects\.filter\(\(project\) => project\.exists\)/,
  "status polling must cover the full registry, not only the visible 3\/8 project slice");
assert.match(recent, /<ActiveProjectJobs/);
assert.match(activeJobs, /projects are running/);
assert.match(activeJobs, /RunProgress/);
assert.match(activeJobs, /StopRunControl/);

console.log("continue-project-copy.test.ts: all assertions passed");
