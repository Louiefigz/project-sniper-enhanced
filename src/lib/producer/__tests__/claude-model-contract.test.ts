import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

const source = (relative: string): string =>
  readFileSync(path.join(process.cwd(), relative), "utf8");

const modelAwareClaudePaths = [
  "src/app/api/producer/auto-edit/authoring.ts",
  "src/app/api/producer/auto-edit/brain-review-process.ts",
  "src/app/api/producer/ai-edit/execution.ts",
  "src/app/api/producer/ai-edit/critic.ts",
  "src/app/api/producer/ai-edit/palmier-native-runner.ts",
  "src/app/api/producer/palmier/candidate-qc/reviewer.ts",
] as const;

for (const file of modelAwareClaudePaths) {
  assert.match(
    source(file),
    /claudeModelArgs/,
    `${file} must pass the explicit Claude model instead of inheriting a desktop default`,
  );
}

// Guardrail: Opus xhigh stays on all rendered/frame critics. The candidate-QC
// vision critics (composition + editorial) must pin effort explicitly instead
// of inheriting the operator's global claude config.
assert.match(
  source("src/app/api/producer/palmier/candidate-qc/reviewer.ts"),
  /claudeModelArgs\(\), "--effort", "xhigh"/,
  "candidate-qc vision critics must pin --effort xhigh on the Claude spawn",
);

const semantics = source("scripts/producer/study/deep_semantics.py");
assert.match(semantics, /"--model", claude_model\(\)/,
  "the optional Python Claude micro-layer must use the same explicit model contract");

const runtime = source("src/app/api/runtime/route.ts");
assert.match(runtime, /model: brainModel\(provider\)/,
  "the runtime endpoint must disclose the selected Claude model");
const editorRuntime = source("src/components/producer/use-editor-runtime.ts");
assert.match(editorRuntime, /Claude Code · \$\{status\.brain\.model\}/,
  "Producer actions must show the exact configured Claude model");

console.log("claude-model-contract.test.ts: all assertions passed");
