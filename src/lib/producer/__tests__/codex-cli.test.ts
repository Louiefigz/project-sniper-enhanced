import assert from "node:assert/strict";
import { agentMessage, buildCodexArgs } from "../../../app/api/_lib/codex-cli";
import { codexProcessEnv } from "../../../app/api/_lib/ai-provider";

process.env.SNIPER_CODEX_MODEL = "gpt-5.6";
process.env.SNIPER_CODEX_REASONING = "xhigh";

{
  const args = buildCodexArgs({
    sandbox: "read-only",
    timeoutMs: 10_000,
    schema: "segmenter",
    addDirs: ["/tmp/job with spaces"],
  });
  assert.ok(args.includes("--ignore-user-config"));
  assert.ok(args.includes("--ignore-rules"));
  assert.ok(args.includes("--skip-git-repo-check"));
  assert.ok(args.includes("read-only"));
  assert.ok(args.includes("/tmp/job with spaces"), "argv keeps paths as one value");
  assert.equal(args.at(-1), "-", "prompt is read from stdin, not exposed in argv");
  assert.ok(args.some((arg) => arg.endsWith("schemas/codex/segmenter.schema.json")));
  assert.deepEqual(
    args.filter((arg) => arg.startsWith("model_reasoning_effort=")),
    ['model_reasoning_effort="xhigh"'],
    "no override preserves the validated global default",
  );
}

{
  const args = buildCodexArgs({
    sandbox: "read-only", timeoutMs: 10_000, tools: "none",
  });
  for (const feature of [
    "shell_tool", "unified_exec", "code_mode_host", "computer_use",
    "browser_use", "in_app_browser", "workspace_dependencies",
  ]) {
    const index = args.indexOf(feature);
    assert.ok(index > 0 && args[index - 1] === "--disable", `${feature} must be disabled`);
  }
  assert.ok(!args.includes("--add-dir"));
}

{
  const args = buildCodexArgs({
    sandbox: "read-only",
    timeoutMs: 10_000,
    reasoning: "high",
  });
  assert.deepEqual(
    args.filter((arg) => arg.startsWith("model_reasoning_effort=")),
    ['model_reasoning_effort="high"'],
    "one invocation may lower effort without changing the global setting",
  );
  assert.throws(
    () => buildCodexArgs({
      sandbox: "read-only",
      timeoutMs: 10_000,
      reasoning: "turbo" as "high",
    }),
    /Codex reasoning override must be one of/,
  );
}

{
  const env = codexProcessEnv({
    HOME: "/Users/test",
    PATH: "/usr/bin",
    CODEX_HOME: "/Users/test/.codex",
    OPENAI_API_KEY: "must-not-leak",
    DEEPGRAM_API_KEY: "must-not-leak",
    DATABASE_URL: "must-not-leak",
  });
  assert.deepEqual(env, {
    HOME: "/Users/test",
    PATH: "/usr/bin",
    CODEX_HOME: "/Users/test/.codex",
  });
}

assert.equal(
  agentMessage({ type: "item.completed", item: { type: "agent_message", text: "done" } }),
  "done",
);
assert.equal(agentMessage({ type: "item.started", item: { type: "command_execution" } }), null);

console.log("codex-cli.test.ts: all assertions passed");
