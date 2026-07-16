import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const source = (relative: string): string => readFileSync(path.join(process.cwd(), relative), "utf8");
const routes = [
  "src/app/api/producer/save-plan/route.ts",
  "src/app/api/producer/intent/route.ts",
  "src/app/api/producer/ingest/route.ts",
  "src/app/api/producer/ai-edit/route.ts",
  "src/app/api/producer/render/route.ts",
  "src/app/api/producer/assemble/route.ts",
  "src/app/api/producer/palmier/push/route.ts",
];

for (const route of routes) {
  assert.match(source(route), /guardProjectMutation\(/, `${route} must use the shared writer lease`);
}
for (const route of [
  "src/app/api/producer/render/route.ts",
  "src/app/api/producer/assemble/route.ts",
  "src/app/api/producer/palmier/push/route.ts",
]) {
  assert.match(source(route), /assertTemplateUsageApprovalCurrent\(/,
    `${route} must reject ungoverned produced/full template reuse`);
}
assert.match(source("src/app/api/producer/save-plan/route.ts"), /clearTemplateUsageApproval\(/,
  "saving a draft must invalidate its prior template-history delivery authority");
assert.match(source("src/app/api/producer/ai-edit/finalize.ts"), /writeTemplateUsageApproval\(/,
  "surgical history authority must commit only after the critic passes and the candidate is promoted");
assert.match(source("src/app/api/producer/save-plan/transaction.ts"),
  /atomicWriteJsonSync\(filePath, plan\)/);
assert.match(source("src/app/api/producer/save-plan/transaction.ts"),
  /refitPlanTransaction\([\s\S]*deferReceiptCommit: true/,
  "GUI cut saves must stage a refit receipt before CAS promotion");
assert.match(source("src/app/api/_lib/workspace.ts"), /atomicWriteJsonSync\(projectJsonPath/);
assert.match(source("src/app/api/producer/ai-edit/execution.ts"), /sniper-ai-edit-/,
  "AI writes must remain isolated until governed promotion");
assert.match(source("src/app/api/producer/auto-edit/route.ts"), /guardProjectMutation\(/,
  "Auto Edit launch must fence concurrent mutation requests");
assert.match(source("src/app/api/producer/render/route.ts"), /finally \{[\s\S]*releaseLease\(\)/,
  "fresh render must hold the shared writer lease through process exit and QC");
assert.match(source("src/app/api/producer/assemble/route.ts"), /guarded\.lease\.release\(\)/,
  "assemble must release its shared writer lease through its idempotent teardown");
assert.match(source("src/app/api/producer/ai-edit/route.ts"),
  /classifyPalmierWorkspace\(prepared\.dir\)/,
  "plan-first edits must recheck managed Palmier authority under the writer lease");
assert.match(source("src/app/api/producer/palmier/view/recovery.ts"), /guardProjectMutation\(/,
  "quarantined-parent recovery must use the shared writer lease");
assert.match(source("src/app/api/producer/palmier/view/route.ts"),
  /palmierCandidateQcState\(dir\)\.run[\s\S]*candidateAction\.active/,
  "Palmier view activation must fail closed while any durable candidate action is active");
assert.match(source("src/components/producer/editor/candidate-qc-controls.tsx"),
  /durableAction[\s\S]*<OpenPalmierButton[\s\S]*disabled=\{busy\}/,
  "the editor must disable Open Palmier for cross-tab durable candidate actions");
assert.match(source("src/components/producer/project-palmier-button.tsx"),
  /candidateBusy[\s\S]*disabled=\{!ready \|\| opening\}/,
  "project cards must disable Palmier access for cross-tab durable candidate actions");

console.log("project-mutation-routes.test.ts: all assertions passed");
