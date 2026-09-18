import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import {
  brainModel,
  brainProviderLabel,
  brainProvider,
  claudeModelArgs,
  claudeProcessEnv,
  claudeSettings,
  codexSettings,
  subscriptionProvider,
} from "../../../app/api/_lib/ai-provider";
import { buildAiEditInvocation } from
  "../../../app/api/producer/ai-edit/execution";
import { buildAiEditPrompt } from
  "../../../app/api/producer/ai-edit/prompt";
import {
  authoringPermissionDenial,
  authoringStreamSessionId,
  claudeArgs,
  runAuthoring,
} from "../../../app/api/producer/auto-edit/authoring";
import { retainedClaudeSessionId } from
  "../../../app/api/producer/auto-edit/authoring-session";
import { claudeAuthoringBashPatterns } from
  "../../../app/api/producer/auto-edit/authoring-prompt";
import { claudeCutAuthoringBashPatterns } from
  "../../../app/api/producer/auto-edit/cut-authoring-prompt";
import type { AutoEditCtx } from "../../../app/api/producer/auto-edit/stream";
import { authoringReasoning } from "../../../app/api/producer/auto-edit/authoring-reasoning";
import { MODES, SCOPES } from "../intent-presets";

const ctx: AutoEditCtx = {
  dir: "/tmp/sniper job/producer",
  scope: "produced",
  intent: { mode: "longform", lanes: {} },
  planPath: "/tmp/sniper job/producer/edit_plan.json",
  manifestPath: "/tmp/sniper job/source/asset_manifest.json",
  transcriptsDir: "/tmp/sniper job/source",
  templateUsage: {
    schemaVersion: 1,
    path: "/tmp/sniper job/producer/.sniper-learning/runs/unbound/template-usage.json",
    digest: "a".repeat(64),
  },
};

delete process.env.SNIPER_CODEX_MODEL;
delete process.env.SNIPER_CODEX_REASONING;
assert.equal(codexSettings().model, "gpt-5.6-sol");
assert.equal(codexSettings().reasoning, "xhigh");

delete process.env.SNIPER_CLAUDE_MODEL;
assert.equal(claudeSettings().model, "opus");
assert.deepEqual(claudeModelArgs(), ["--model", "opus"]);
assert.equal(brainProviderLabel("legacy"), "Claude Code · opus");
process.env.SNIPER_CLAUDE_MODEL = "claude-sonnet-4-6[1m]";
assert.equal(claudeSettings().model, "claude-sonnet-4-6[1m]");
assert.deepEqual(claudeModelArgs(), ["--model", "claude-sonnet-4-6[1m]"]);
process.env.SNIPER_CLAUDE_MODEL = "--dangerous model";
assert.throws(() => claudeSettings(), /Claude alias or model identifier/);
delete process.env.SNIPER_CLAUDE_MODEL;

const boundedDir = mkdtempSync(path.join(tmpdir(), "sniper-reasoning-"));
const boundedManifest = path.join(boundedDir, "asset_manifest.json");
writeFileSync(boundedManifest, JSON.stringify({
  sources: [{ role: "primary", duration: 60.061 }],
}));
assert.deepEqual(authoringReasoning({ ...ctx, manifestPath: boundedManifest }), {
  reasoning: "high",
  basis: "bounded-source",
  sourceDurationS: 60.061,
});
assert.equal(authoringReasoning({
  ...ctx,
  intent: { mode: "short" },
  manifestPath: "/missing/manifest.json",
}).reasoning, "high");

// Claude Code is the visible editor default; Codex remains an explicit opt-in.
delete process.env.SNIPER_BRAIN_PROVIDER;
delete process.env.SNIPER_PROVIDER;
process.env.SNIPER_EXECUTION_MODE = "local";
assert.equal(brainProvider(), "legacy");
process.env.SNIPER_EXECUTION_MODE = "live";
assert.equal(brainProvider(), "legacy");
process.env.SNIPER_BRAIN_PROVIDER = "codex";
assert.equal(brainProvider(), "codex");

// The installer's SNIPER_PROVIDER and the app's SNIPER_BRAIN_PROVIDER select one
// provider for every call; either alone is enough, a disagreement is refused.
for (const [chosen, brain, expected] of [
  ["codex", undefined, "codex"], ["claude", undefined, "legacy"],
  ["codex", "codex", "codex"], ["claude", "legacy", "legacy"],
  [undefined, "legacy", "legacy"], [undefined, "codex", "codex"],
] as const) {
  if (chosen === undefined) delete process.env.SNIPER_PROVIDER; else process.env.SNIPER_PROVIDER = chosen;
  if (brain === undefined) delete process.env.SNIPER_BRAIN_PROVIDER; else process.env.SNIPER_BRAIN_PROVIDER = brain;
  assert.equal(brainProvider(), expected, `${chosen}/${brain}`);
  assert.equal(subscriptionProvider(), expected === "codex" ? "codex" : "claude");
  assert.equal(brainModel(), expected === "codex" ? codexSettings().model : claudeSettings().model);
}
for (const [chosen, brain] of [["claude", "codex"], ["codex", "legacy"]] as const) {
  process.env.SNIPER_PROVIDER = chosen; process.env.SNIPER_BRAIN_PROVIDER = brain;
  assert.throws(() => brainProvider(), /select different editor brains/);
}
process.env.SNIPER_PROVIDER = "openai";
delete process.env.SNIPER_BRAIN_PROVIDER;
assert.throws(() => brainProvider(), /SNIPER_PROVIDER must be one of: claude, codex/);
delete process.env.SNIPER_PROVIDER;
process.env.SNIPER_BRAIN_PROVIDER = "codex";

// One CLI setting per provider, validated at the boundary.
delete process.env.CLAUDE_BIN;
assert.equal(claudeSettings().bin, "claude");
process.env.CLAUDE_BIN = "/opt/sniper/runtime/cli/node_modules/.bin/claude";
assert.equal(claudeSettings().bin, "/opt/sniper/runtime/cli/node_modules/.bin/claude");
process.env.CLAUDE_BIN = "claude\n--settings";
assert.throws(() => claudeSettings(), /CLAUDE_BIN contains an invalid value/);
delete process.env.CLAUDE_BIN;

// Claude keeps only subscription/runtime configuration, never app provider keys
// and never an inherited login token (Sniper signs in through CLAUDE_CONFIG_DIR).
assert.deepEqual(
  claudeProcessEnv({
    HOME: "/Users/test",
    PATH: "/usr/bin",
    CLAUDE_CONFIG_DIR: "/Users/test/.claude",
    CLAUDE_CODE_OAUTH_TOKEN: "subscription-token",
    CLAUDE_CODE_USE_BEDROCK: "1",
    CLAUDE_CODE_USE_VERTEX: "1",
    CLAUDE_CODE_API_KEY_HELPER_TTL_MS: "1",
    CLAUDE_CODE_DISABLE_FAST_MODE: "0",
    ANTHROPIC_API_KEY: "must-not-leak",
    ANTHROPIC_AUTH_TOKEN: "must-not-leak",
    DEEPGRAM_API_KEY: "must-not-leak",
    OPENAI_API_KEY: "must-not-leak",
  }),
  {
    HOME: "/Users/test",
    PATH: "/usr/bin",
    CLAUDE_CONFIG_DIR: "/Users/test/.claude",
    CLAUDE_CODE_DISABLE_FAST_MODE: "1",
    DISABLE_AUTOUPDATER: "1",
  },
);

// AI-edit builds equivalent provider invocations without launching either CLI.
const editPrompt = buildAiEditPrompt(ctx.planPath, "make the hook tighter", "16:9");
const codexPrompt = buildAiEditPrompt(ctx.planPath, "make the hook tighter", "16:9", "codex");
for (const prompt of [editPrompt, codexPrompt]) {
  assert.ok(prompt.includes(`${process.cwd()}/.claude/skills/producer/SKILL.md`));
  assert.ok(prompt.includes(`${process.cwd()}/scripts/producer/docs/findings/FAILURE_LEDGER.md`));
  assert.ok(prompt.includes(`${process.cwd()}/scripts/producer/plan_lint.py`));
  assert.ok(prompt.includes("Requested lanes: cuts"));
  assert.ok(prompt.includes("fresh read-only critic"));
  assert.equal(prompt.includes("treatmentMap, captionsTrack"), false);
  assert.ok(prompt.includes("CaptionTrackV1 is renderable"));
  assert.ok(prompt.includes("controller code stamps"));
}
assert.ok(codexPrompt.includes("BEGIN_OPERATOR_REQUEST_JSON"));
assert.ok(codexPrompt.includes(JSON.stringify({
  request: "make the hook tighter", scope: { lanes: ["cuts"] },
})));
const codexEdit = buildAiEditInvocation("codex", codexPrompt, ctx.dir);
assert.equal(codexEdit.provider, "codex");
assert.equal(codexEdit.options.prompt, codexPrompt);
assert.equal(codexEdit.options.sandbox, "workspace-write");
assert.equal(codexEdit.options.cwd, ctx.dir);
assert.equal("addDirs" in codexEdit.options, false);
const stagedPlan = "/tmp/sniper-ai-edit-fixture/edit_plan.json";
const stagedCodex = buildAiEditInvocation("codex", codexPrompt, ctx.dir, stagedPlan);
assert.equal(stagedCodex.provider, "codex");
assert.equal(stagedCodex.options.cwd, "/tmp/sniper-ai-edit-fixture",
  "Codex workspace-write must be rooted at the isolated candidate");

const claudeEdit = buildAiEditInvocation("legacy", editPrompt, ctx.dir);
assert.equal(claudeEdit.provider, "legacy");
assert.equal(claudeEdit.model, "opus");
assert.equal(claudeEdit.args[claudeEdit.args.indexOf("--model") + 1], "opus");
assert.deepEqual(claudeEdit.args.slice(-2), ["--permission-mode", "acceptEdits"]);
assert.ok(claudeEdit.args.includes(ctx.dir));
assert.match(claudeEdit.args.join(" "), /allowedTools.*Edit\(.*edit_plan\.json\)/);
const stagedClaude = buildAiEditInvocation("legacy", editPrompt, ctx.dir, stagedPlan);
assert.equal(stagedClaude.provider, "legacy");
assert.ok(stagedClaude.args.includes("/tmp/sniper-ai-edit-fixture"));
assert.match(stagedClaude.args.join(" "), /Edit\(\/tmp\/sniper-ai-edit-fixture\/edit_plan\.json\)/);

const legacyAuthoringArgs = claudeArgs(ctx);
assert.equal(legacyAuthoringArgs[legacyAuthoringArgs.indexOf("--model") + 1], "opus");
assert.equal(legacyAuthoringArgs[legacyAuthoringArgs.indexOf("--effort") + 1], "xhigh");
assert.ok(legacyAuthoringArgs.includes("--allowedTools"));
assert.ok(legacyAuthoringArgs.includes(ctx.dir));
assert.ok(legacyAuthoringArgs.includes(ctx.transcriptsDir));
const legacyPrompt = legacyAuthoringArgs[legacyAuthoringArgs.indexOf("-p") + 1];
const legacyAllowed = legacyAuthoringArgs[legacyAuthoringArgs.indexOf("--allowedTools") + 1];
assert.ok(legacyPrompt.includes(`${process.cwd()}/scripts/producer/graphics_planner.py`));
assert.ok(legacyPrompt.includes(`${process.cwd()}/scripts/producer/planner/pacing.py`));
assert.equal(legacyPrompt.includes("run graphics_planner.py"), false);
assert.ok(legacyPrompt.includes("Never prepend `cd`"));
assert.ok(legacyPrompt.includes("replace either absolute path with a relative path"));
assert.ok(legacyPrompt.includes("append `&&`, `;`, or `|`"));
assert.ok(legacyPrompt.includes("CUT AUTHORITY CHECK"));
assert.ok(legacyPrompt.includes("transcript_cut_contract.py"));
assert.ok(legacyPrompt.includes("cutTrack and cutDecisions are controller-approved and IMMUTABLE"));
assert.ok(legacyPrompt.indexOf("CUT AUTHORITY CHECK") < legacyPrompt.indexOf("3. Lanes"));
assert.ok(legacyAllowed.includes("Bash(/"), "safe absolute tokens use canonical minimal quoting");
const visualCommands = claudeAuthoringBashPatterns(ctx);
const [speechCommand] = visualCommands;
assert.ok(visualCommands.every((command) => !command.endsWith(" *")),
  "visual authoring permissions must use exact commands, never wildcard script args");
for (const command of visualCommands) {
  assert.ok(legacyAllowed.includes(`Bash(${command})`),
    `visual command missing from exact Claude allowlist: ${command}`);
}
assert.ok(speechCommand.includes("'/tmp/sniper job/"), "fixture must exercise shell quoting");
assert.ok(
  speechCommand.startsWith(`${process.cwd()}/.venv/bin/python3 ${process.cwd()}/scripts/producer/`),
  "safe interpreter and pinned script tokens must not carry redundant quotes",
);
assert.ok(
  legacyPrompt.includes(`\`\`\`bash\n${speechCommand}\n\`\`\``),
  "Claude must see the exact absolute command that its allowlist accepts",
);
assert.ok(
  legacyAllowed.includes(`Bash(${speechCommand})`),
  "the displayed command and the allowlist entry must stay byte-identical",
);
assert.ok(legacyAllowed.includes(`Edit(/${ctx.planPath})`));
assert.ok(legacyAllowed.includes(`Write(/${ctx.planPath})`));
assert.equal(legacyAllowed.includes(`Edit(${ctx.planPath})`), false);
assert.equal(legacyAllowed.includes(`Write(${ctx.planPath})`), false);
assert.equal(legacyAllowed.split(",").includes("Edit"), false);
assert.equal(legacyAllowed.split(",").includes("Write"), false);

const cutArgs = claudeArgs(ctx, "cut");
assert.equal(cutArgs[cutArgs.indexOf("--effort") + 1], "xhigh");
const cutPrompt = cutArgs[cutArgs.indexOf("-p") + 1];
const cutAllowed = cutArgs[cutArgs.indexOf("--allowedTools") + 1];
const [cutSpeech, cutGate] = claudeCutAuthoringBashPatterns(ctx);
assert.ok(cutPrompt.includes("CUT EDITOR"));
assert.ok(cutPrompt.includes("--previsual"));
assert.ok(cutPrompt.includes("CUT_AUTHORING_BLOCKED permission_allowlist_mismatch"));
assert.ok(cutPrompt.includes(`"mode":"${MODES.join("|")}"`));
assert.ok(cutPrompt.includes(`"scope":"${SCOPES.join("|")}"`));
assert.equal(cutPrompt.includes('"mode":"longform|shortform"'), false);
assert.equal(cutPrompt.includes('"scope":"clean|produced"'), false);
assert.equal(cutPrompt.includes("graphics_planner.py"), false);
assert.ok(cutAllowed.includes(`Bash(${cutSpeech})`));
assert.ok(cutAllowed.includes(`Bash(${cutGate})`));
assert.equal((cutAllowed.match(/Bash\(/g) ?? []).length, 2);
assert.equal(cutAllowed.includes("Glob"), false);
assert.equal(cutAllowed.includes("Grep"), false);
assert.equal(cutArgs.includes("--safe-mode"), false);
assert.equal(cutArgs.includes("--tools"), false);
assert.ok(cutAllowed.split(",").includes("Skill(producer)"));
assert.equal(cutArgs[cutArgs.indexOf("--permission-mode") + 1], "dontAsk");
const retained = { ...ctx, brainSessionId: "session-123" };
const firstTurn = claudeArgs(retained, "cut", "start");
const resumedTurn = claudeArgs(retained, "visual", "resume");
assert.deepEqual(firstTurn.slice(firstTurn.indexOf("--session-id"),
  firstTurn.indexOf("--session-id") + 2), ["--session-id", "session-123"]);
assert.deepEqual(resumedTurn.slice(resumedTurn.indexOf("--resume"),
  resumedTurn.indexOf("--resume") + 2), ["--resume", "session-123"]);
const validSession = "5f7319ca-63c8-4f31-8938-6213ae5a6409";
assert.equal(retainedClaudeSessionId(validSession), validSession);
assert.match(retainedClaudeSessionId("2026-07-13:invalid"), /^[0-9a-f-]{36}$/i);
assert.equal(authoringStreamSessionId(JSON.stringify({
  type: "result", session_id: validSession,
})), validSession);
assert.equal(authoringStreamSessionId("not-json"), null);
assert.equal(authoringPermissionDenial(JSON.stringify({
  type: "user", message: { content: [{
    type: "tool_result", is_error: true, content: "This command requires approval",
  }] },
})), "This command requires approval");
assert.equal(authoringPermissionDenial(JSON.stringify({
  type: "user", message: { content: [{
    type: "tool_result", is_error: true, content: "ordinary command failure",
  }] },
})), null);

// Auto-edit's Codex branch receives stdin prompt options and forwards JSON events.
async function testCodexAuthoring(): Promise<void> {
  const events: Record<string, unknown>[] = [];
  let codexCalled = false;
  const authored = await runAuthoring(ctx, (event) => events.push(event), {
    provider: () => "codex",
    codex: async (options) => {
      codexCalled = true;
      assert.equal(options.sandbox, "workspace-write");
      assert.equal(options.reasoning, "xhigh");
      assert.equal(options.cwd, ctx.dir);
      assert.equal(options.addDirs, undefined);
      assert.ok(options.prompt.includes(ctx.planPath));
      assert.ok(options.prompt.includes(`${process.cwd()}/.agents/skills/producer/SKILL.md`));
      assert.ok(options.prompt.includes(`${process.cwd()}/.venv/bin/python3`));
      assert.ok(options.prompt.includes(`${process.cwd()}/scripts/producer/graphics_planner.py`));
      assert.ok(options.prompt.includes(`${process.cwd()}/scripts/producer/planner/pacing.py`));
      assert.ok(options.prompt.includes(`${ctx.dir}/graphics_proposal.json`));
      assert.equal(options.prompt.includes("run graphics_planner.py"), false);
      options.onEvent?.({ type: "item.completed", item: { type: "agent_message", text: "AUTHORED ok segments=7 graphics=3" } });
      return {
        message: "AUTHORED ok segments=7 graphics=3",
        stderr: "",
        ms: 42,
      };
    },
  });
  assert.equal(codexCalled, true);
  assert.equal(authored.provider, "codex");
  assert.deepEqual(authored.authored, { segments: 7, graphics: 3 });
  assert.deepEqual(events[0], {
    event: "authoring_reasoning_selected",
    provider: "codex",
    reasoning: "xhigh",
    basis: "configured",
    sourceDurationS: undefined,
  });
  assert.deepEqual(events[1], {
    type: "item.completed",
    item: { type: "agent_message", text: "AUTHORED ok segments=7 graphics=3" },
    event: "authoring_item.completed",
    provider: "codex",
  });
}

testCodexAuthoring()
  .then(() => console.log("producer-ai-provider.test.ts: all assertions passed"))
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
