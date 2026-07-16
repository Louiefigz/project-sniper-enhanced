import assert from "node:assert/strict";
import {
  buildSurgicalCriticPrompt,
  runSurgicalEditCritic,
  type SurgicalCriticInput,
} from "../../../app/api/producer/ai-edit/critic";

const input: SurgicalCriticInput = {
  provider: "codex",
  dir: "/tmp/sniper-edit",
  planPath: "/tmp/sniper-edit/edit_plan.json",
  manifestPath: "/tmp/sniper-edit/asset_manifest.json",
  transcriptsDir: "/tmp/sniper-edit/source",
  request: "Add a smooth transition at 0:42",
  scope: { lanes: ["motion"] },
  changedFields: ["transitions"],
};

const passing = JSON.stringify({
  schemaVersion: 1,
  stage: "plan",
  verdict: "pass",
  summary: "The transition earns its seam and respects long-form grammar.",
  materialIssues: [],
  findings: [],
});

const prompt = buildSurgicalCriticPrompt(input);
assert.match(prompt, /FRESH, INDEPENDENT SURGICAL EDIT CRITIC/);
assert.ok(prompt.includes(`${process.cwd()}/.claude/skills/producer/SKILL.md`));
assert.ok(prompt.includes(`${process.cwd()}/scripts/producer/docs/findings/FAILURE_LEDGER.md`));
assert.ok(prompt.includes(`${process.cwd()}/scripts/producer/plan_lint_motion.py`));
assert.ok(prompt.includes(`${process.cwd()}/scripts/producer/plan_lint_smooth.py`));
assert.ok(prompt.includes(`${process.cwd()}/scripts/producer/hook_contract.py`));
assert.ok(prompt.includes(`${process.cwd()}/scripts/producer/intro_transition_contract.py`));
assert.ok(prompt.includes(`${process.cwd()}/scripts/producer/operator_intent_contract.py`));

const graphicPrompt = buildSurgicalCriticPrompt({
  ...input,
  request: "Change the existing title typography",
  scope: { lanes: ["graphics"] },
  changedFields: ["graphicsTrack"],
});
assert.ok(graphicPrompt.includes(
  `${process.cwd()}/scripts/producer/graphics/template_contract.py`,
));
assert.ok(graphicPrompt.includes(`${process.cwd()}/src/lib/producer/comps-catalog.ts`));

async function codexCriticIsReadOnly(): Promise<void> {
  const review = await runSurgicalEditCritic(input, {
    codex: async (options) => {
      assert.equal(options.sandbox, "read-only");
      assert.equal(options.schema, "producer-review");
      assert.ok(options.addDirs?.includes(process.cwd()));
      return { message: passing, stderr: "", ms: 1 };
    },
  });
  assert.equal(review.verdict, "pass");
}

async function legacyCriticHasNoWriteTools(): Promise<void> {
  const review = await runSurgicalEditCritic({ ...input, provider: "legacy" }, {
    legacy: async (invocation) => {
      const toolsIndex = invocation.args.indexOf("--allowedTools");
      const modelIndex = invocation.args.indexOf("--model");
      assert.equal(invocation.args[modelIndex + 1], "opus");
      assert.equal(invocation.args[toolsIndex + 1], "Read,Glob,Grep");
      assert.equal(invocation.args.join(" ").includes("Edit("), false);
      assert.equal(invocation.args.join(" ").includes("Write("), false);
      return { message: passing, stderr: "", ms: 1 };
    },
  });
  assert.equal(review.verdict, "pass");
}

codexCriticIsReadOnly()
  .then(legacyCriticHasNoWriteTools)
  .then(() => console.log("surgical-edit-critic.test.ts: all assertions passed"))
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
