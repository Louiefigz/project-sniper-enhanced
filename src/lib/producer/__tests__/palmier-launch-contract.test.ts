import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const source = (relative: string): string => readFileSync(path.join(process.cwd(), relative), "utf8");
const section = (code: string, start: string, end: string): string => {
  const from = code.indexOf(start);
  const to = code.indexOf(end, from + start.length);
  assert.ok(from >= 0 && to > from, `missing source section ${start}`);
  return code.slice(from, to);
};

const runtime = source("src/components/producer/use-editor-runtime.ts");
const launch = source("src/components/producer/auto-edit-launch.tsx");
const stages = source("src/components/producer/stage-actions.tsx");
const manual = source("src/components/producer/render-step.tsx");
const editor = source("src/components/producer/editor/use-plan-actions.ts");
const provider = source("src/app/api/_lib/ai-provider.ts");

const palmierOpen = runtime.indexOf("await openPalmierWorkbench(input.dir");
const jobPost = runtime.indexOf('return post("/api/producer/auto-edit"');
assert.ok(palmierOpen >= 0 && jobPost > palmierOpen,
  "the shared launcher must await Palmier before starting the auto-edit job");
assert.match(runtime, /input\.signal\?\.throwIfAborted\(\)/,
  "navigation cancellation between Palmier open and job POST must not launch work");
assert.match(runtime, /No managed Palmier workspace exists/,
  "only an actually missing workspace may trigger draft creation; other Palmier locks fail closed");
assert.match(provider, /return enumEnv\("SNIPER_BRAIN_PROVIDER", \["legacy", "codex"\], "legacy"\)/,
  "Claude Code must remain the default editor brain");
assert.match(runtime, /if \(!status\) return "Claude Code · sonnet"/,
  "the launch caption must name Claude Code and its explicit default model immediately");

for (const [label, code] of Object.entries({ launch, stages, manual, editor })) {
  assert.match(code, /launchAutoEditFromHyperframes/,
    `${label} must use the shared explicit MP4-only auto-edit launcher`);
  assert.doesNotMatch(code, /fetch\("\/api\/producer\/auto-edit"/,
    `${label} must not bypass the shared launcher`);
}

assert.match(launch, /Generate video →[\s\S]*\{brain\} · HyperFrames review/,
  "the new-edit action must show the selected brain underneath its button");
assert.match(stages, /\{c\.brain\} · HyperFrames review/,
  "continue-project actions must show the selected brain underneath their button");
assert.match(stages, /async function runControllerAutoEdit\([\s\S]*?launch = launchAutoEditFromHyperframes/,
  "fresh and saved-plan actions must keep the HyperFrames default");
assert.match(stages, /buildResumeAutoEditRequest\(status\.producerDir, status\.intent, policy, status\.run\?\.workflowPolicy\)/,
  "Resume must send its proved delivery and workflow policies explicitly, never infer new defaults in the launcher");

const actionSections = [
  ["AutoEditAction", "function ResumeEditAction"],
  ["ResumeEditAction", "function RenderPlanAction"],
  ["RenderPlanAction", "function RerenderAction"],
  ["RerenderAction", "export function StageActionButton"],
] as const;
for (const [name, end] of actionSections) {
  const code = section(stages, `function ${name}`, end);
  assert.match(code, /<LaunchAction c=\{c\}(?: caption=\{caption\})?>/,
    `${name} must visibly identify the editor and checked delivery behavior`);
  assert.match(code, /runControllerAutoEdit|resumeSavedAutoEdit|reviewSavedPlan/,
    `${name} must use the shared controller workflow`);
}

console.log("palmier-launch-contract.test.ts: all assertions passed");
