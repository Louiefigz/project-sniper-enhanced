/** Paid-API auth exclusion, not a promise of zero account-level usage credits. */
export type SubscriptionProvider = "codex" | "claude";
export const SUBSCRIPTION_VERSIONS = { codex: "codex-cli 0.144.1", claude: "2.1.247 (Claude Code)" } as const;
export const CODEX_SUBSCRIPTION_CONFIG = ['-c', 'forced_login_method="chatgpt"'] as const;
export const CLAUDE_SUBSCRIPTION_SETTINGS = JSON.stringify({
  forceLoginMethod: "claudeai", fastMode: false, disableAllHooks: true,
});
const CLAUDE_CONFIG_ARGS = ["--setting-sources", "", "--settings", CLAUDE_SUBSCRIPTION_SETTINGS];
const CLAUDE_VALUE_FLAGS = new Set([
  "-p", "--print", "--model", "--effort", "--output-format", "--permission-mode",
  "--tools", "--allowedTools", "--allowed-tools", "--disallowedTools", "--disallowed-tools",
  "--add-dir", "--json-schema", "--session-id", "--resume", "-r", "--mcp-config",
  "--append-system-prompt", "--system-prompt",
]);
const CLAUDE_SWITCHES = new Set(["--verbose", "--strict-mcp-config", "--no-session-persistence", "--no-chrome"]);
const CLAUDE_STATUS_KEYS = new Set(["loggedIn", "authMethod", "apiProvider", "forcedLoginMethod",
  "subscriptionType", "analyticsDisabled", "email", "orgId", "orgName"]);
const CODEX_FIXED_CONFIG = ['forced_login_method="chatgpt"', 'model_provider="openai"',
  'web_search="disabled"', "features.apps=false", "features.hooks=false", "features.multi_agent=false"];
const CODEX_VALUE_FLAGS = new Set(["--ask-for-approval", "--disable", "--model", "--sandbox", "--add-dir", "--output-schema", "--image"]);
const CODEX_SWITCHES = new Set(["exec", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules",
  "--ephemeral", "--strict-config", "--json", "-"]);

/** Guard the reusable admission seam too: no caller-supplied provider/config bypass. */
export function codexSubscriptionArgs(args: readonly string[]): string[] {
  const seen = new Set<string>(), configs: string[] = [];
  for (let index = 0; index < args.length; index += 1) {
    const flag = args[index];
    if (CODEX_SWITCHES.has(flag)) { seen.add(flag); continue; }
    if (!CODEX_VALUE_FLAGS.has(flag) && flag !== "-c") throw new Error("Unsupported subscription-only Codex option");
    const value = args[++index];
    if (typeof value !== "string") throw new Error("Missing subscription-only Codex option value");
    if (flag === "-c") configs.push(value);
  }
  const reasoning = configs.filter((value) => /^model_reasoning_effort="(?:none|minimal|low|medium|high|xhigh|max|ultra)"$/.test(value));
  const required = ["exec", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--strict-config", "--json", "-"];
  if (required.some((flag) => !seen.has(flag)) || args.at(-1) !== "-"
      || configs.length !== CODEX_FIXED_CONFIG.length + 1 || reasoning.length !== 1
      || CODEX_FIXED_CONFIG.some((value) => configs.filter((config) => config === value).length !== 1)) {
    throw new Error("Codex requires the exact controlled subscription configuration");
  }
  return [...args];
}

/** Closed argv grammar preserves prompt/skill/MCP values without treating them as flags. */
export function claudeSubscriptionArgs(args: readonly string[]): string[] {
  let hasPrompt = false;
  for (let index = 0; index < args.length; index += 1) {
    const flag = args[index];
    if (CLAUDE_SWITCHES.has(flag)) continue;
    if (!CLAUDE_VALUE_FLAGS.has(flag) || typeof args[index + 1] !== "string") {
      throw new Error("Subscription-only Claude invocation contains an unsupported option");
    }
    if (flag === "-p" || flag === "--print") hasPrompt = true;
    index += 1;
  }
  if (!hasPrompt) throw new Error("Subscription-only Claude requires an explicit print prompt");
  return [...CLAUDE_CONFIG_ARGS, ...args];
}

/** Use exactly the same controlled settings for metadata admission and inference. */
export function subscriptionStatusArgs(provider: SubscriptionProvider): string[] {
  return provider === "codex" ? [...CODEX_SUBSCRIPTION_CONFIG, "login", "status"]
    : [...CLAUDE_CONFIG_ARGS, "auth", "status", "--json"];
}

/** No permissive 'logged in' substring: API-key logins also report logged in. */
export function assertCodexSubscription(text: string): void {
  if (text.trim() !== "Logged in using ChatGPT") {
    throw new Error("Codex requires verified ChatGPT authentication; API or unknown authentication is blocked");
  }
}

/** Pinned 2.1.247 status: 'claude.ai' alone can also mean '/login managed key'. */
export function assertClaudeSubscription(text: string): void {
  let row: Record<string, unknown>;
  try { row = JSON.parse(text); } catch { throw new Error("Claude authentication metadata is invalid"); }
  if (!row || typeof row !== "object" || Array.isArray(row) || row.loggedIn !== true
      || row.authMethod !== "claude.ai" || row.apiProvider !== "firstParty"
      || Object.hasOwn(row, "apiKeySource") || row.forcedLoginMethod !== "claudeai"
      || Object.keys(row).some((key) => !CLAUDE_STATUS_KEYS.has(key))
      || typeof row.subscriptionType !== "string"
      || !["pro", "max", "team", "enterprise"].includes(row.subscriptionType)) {
    throw new Error("Claude requires verified first-party subscription authentication; API, cloud or unknown authentication is blocked");
  }
}

/** Raw output is private and immediately discarded; errors contain no account metadata. */
export function assertSubscriptionStatus(provider: SubscriptionProvider, output: { stdout: string; stderr: string }): void {
  if (provider === "codex") return assertCodexSubscription(`${output.stdout}\n${output.stderr}`);
  if (output.stderr.trim()) throw new Error("Claude authentication emitted unexpected diagnostics");
  assertClaudeSubscription(output.stdout);
}
