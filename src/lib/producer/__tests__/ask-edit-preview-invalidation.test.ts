import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

function source(relative: string): string {
  return readFileSync(path.join(process.cwd(), relative), "utf8");
}

const ask = source("src/components/producer/editor/ask-claude-bar.tsx");
const surface = source("src/components/producer/editor/editor-view-sections.tsx");
const actions = source("src/components/producer/editor/use-plan-actions.ts");
const route = source("src/app/api/producer/ai-edit/route.ts");
const prepare = source("src/app/api/producer/ai-edit/prepare.ts");

assert.match(ask,
  /const editMode = res\.headers\.get\("X-Sniper-Edit-Mode"\);[\s\S]*editMode !== "palmier-native"[\s\S]*onInvalidateAuthority\(\)/,
  "plan edits must invalidate stale A/B output while Palmier-native candidates preserve the visible canonical parent",
);
assert.ok(
  ask.indexOf("onInvalidateAuthority();") < ask.indexOf("await readEventStream"),
  "a plan edit must hide stale A/B output before consuming model progress",
);
assert.match(surface,
  /onInvalidateAuthority=\{\(\) => \{[\s\S]*invalidatePreviewAuthority\(\);[\s\S]*setPalmierView\("internal"\)/,
  "Ask must revoke preview state and force the visible player back to Sniper",
);
assert.match(actions,
  /generation === previewAuthorityGeneration\.current/,
  "an older project-status response may not restore preview authority after Ask starts",
);
assert.ok(
  route.indexOf("await surgicalAuthorityFailure(dir)")
    < route.indexOf("preparePlanForAi(planPath, plan"),
  "disk/Palmier authority must be invalidated before the model-facing plan mutation starts",
);
assert.ok(
  prepare.indexOf("assertNoPromotionReconciliation(dir)")
    < prepare.indexOf("await invalidateAiEditAuthority(dir)"),
  "an unresolved CAS recovery must block before any preview authority is revoked",
);

console.log("ask-edit-preview-invalidation.test.ts: all assertions passed");
