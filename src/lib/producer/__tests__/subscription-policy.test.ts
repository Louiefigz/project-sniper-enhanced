import assert from "node:assert/strict";
import { test } from "node:test";
import { assertClaudeSubscription, assertCodexSubscription, assertSubscriptionStatus,
  claudeSubscriptionArgs, codexSubscriptionArgs, CLAUDE_SUBSCRIPTION_SETTINGS, subscriptionStatusArgs } from "../../../app/api/_lib/subscription-policy";
import { buildCodexArgs } from "../../../app/api/_lib/codex-cli";
import { CLAUDE_STATUS } from "./_subscription-fake";

test("Codex admits exact ChatGPT identity, never API-key or logged-in substrings", () => {
  assertCodexSubscription("Logged in using ChatGPT\n");
  for (const value of ["Logged in using an API key", "logged in", "Logged in using ChatGPT\nAPI key", ""]) {
    assert.throws(() => assertCodexSubscription(value), /authentication/);
  }
  assert.deepEqual(subscriptionStatusArgs("codex"), ["-c", 'forced_login_method="chatgpt"', "login", "status"]);
});

test("reusable Codex admission requires controlled argv, not caller-provided model-provider overrides", () => {
  const args = buildCodexArgs({ sandbox: "read-only", timeoutMs: 2000 });
  assert.deepEqual(codexSubscriptionArgs(args), args);
  for (const extra of [["-c", 'forced_login_method="api"'], ["--config", 'model_provider="other"'], ["--oss"]]) {
    assert.throws(() => codexSubscriptionArgs([...args.slice(0, -1), ...extra, "-"]));
  }
  assert.throws(() => codexSubscriptionArgs(args.filter((a) => a !== "--ignore-user-config")));
});

test("native reference attachments pass the subscription grammar without permitting provider overrides", () => {
  const args = buildCodexArgs({ sandbox: "read-only", timeoutMs: 2000,
    imagePaths: ["/private/tmp/sniper-reference-test.png"] });
  assert.deepEqual(codexSubscriptionArgs(args), args);
  assert.throws(() => codexSubscriptionArgs([...args.slice(0, -1), "-c", 'model_provider="other"', "-"]));
  assert.throws(() => codexSubscriptionArgs([...args.slice(0, -1), "--image"]), /Missing/);
});

test("Claude rejects API, cloud, managed Console key, unknown entitlement and conflicting restriction", () => {
  assertClaudeSubscription(JSON.stringify(CLAUDE_STATUS));
  for (const patch of [{ loggedIn: false }, { apiProvider: "bedrock" }, { authMethod: "api_key" },
    { authMethod: "oauth_token" }, { apiKeySource: "/login managed key" }, { apiKeySource: null },
    { subscriptionType: null }, { subscriptionType: "unknown" }, { forcedLoginMethod: "console" }]) {
    assert.throws(() => assertClaudeSubscription(JSON.stringify({ ...CLAUDE_STATUS, ...patch })), /authentication/);
  }
  for (const text of ["null", "[]", "not json"]) assert.throws(() => assertClaudeSubscription(text));
  assert.throws(() => assertSubscriptionStatus("claude", { stdout: JSON.stringify(CLAUDE_STATUS), stderr: "private" }), /unexpected diagnostics/);
});

test("fixed settings prevent arbitrary paid-mode/config options without changing doctrine or MCP values", () => {
  const args = ["-p", "Read Skill; prompt literally mentions --settings and --bare", "--allowedTools", "Skill,Read,Bash",
    "--mcp-config", "/exact/mcp.json", "--strict-mcp-config", "--model", "opus", "--effort", "xhigh"];
  const controlled = claudeSubscriptionArgs(args);
  assert.deepEqual(controlled, ["--setting-sources", "", "--settings", CLAUDE_SUBSCRIPTION_SETTINGS, ...args]);
  assert.deepEqual(subscriptionStatusArgs("claude").slice(0, 4), controlled.slice(0, 4));
  for (const extra of [["--settings", "evil.json"], ["--setting-sources", "user"], ["--bare"], ["--fallback-model", "fast"], ["--model"]]) {
    assert.throws(() => claudeSubscriptionArgs([...args, ...extra]), /unsupported option/);
  }
  assert.throws(() => claudeSubscriptionArgs([]), /print prompt/);
});
