export type ExecutionMode = "live" | "local";
export type BrainProvider = "legacy" | "codex";

export interface CodexSettings {
  bin: string;
  model: string;
  reasoning: CodexReasoningLevel;
}

export interface ClaudeSettings {
  model: string;
}

// Operator directive (2026-07-14): the editing brain runs on Opus at maximum
// reasoning — quality over latency for video-editing decisions. Override with
// SNIPER_CLAUDE_MODEL if a cheaper/faster tier is ever wanted.
export const DEFAULT_CLAUDE_MODEL = "opus";

export const CODEX_REASONING_LEVELS = [
  "none",
  "minimal",
  "low",
  "medium",
  "high",
  "xhigh",
  "max",
  "ultra",
] as const;
export type CodexReasoningLevel = (typeof CODEX_REASONING_LEVELS)[number];

const REASONING_LEVELS = new Set<string>(CODEX_REASONING_LEVELS);

const SAFE_ENV_KEYS = new Set([
  "PATH",
  "HOME",
  "USER",
  "LOGNAME",
  "SHELL",
  "TMPDIR",
  "TMP",
  "TEMP",
  "LANG",
  "LC_ALL",
  "TERM",
  "CODEX_HOME",
  "XDG_CONFIG_HOME",
  "XDG_CACHE_HOME",
  "SSL_CERT_FILE",
  "SSL_CERT_DIR",
  "NODE_EXTRA_CA_CERTS",
  "NO_PROXY",
  "NODE_ENV",
]);

const CLAUDE_ENV_KEYS = new Set([
  ...SAFE_ENV_KEYS,
  "CLAUDE_CONFIG_DIR",
]);

function enumEnv<T extends string>(name: string, values: readonly T[], fallback: T): T {
  const raw = process.env[name]?.trim() || fallback;
  if (values.includes(raw as T)) return raw as T;
  throw new Error(`${name} must be one of: ${values.join(", ")}`);
}

function safeCliValue(name: string, fallback: string): string {
  const value = process.env[name]?.trim() || fallback;
  if (!value || value.length > 160 || /[\r\n\0]/.test(value)) {
    throw new Error(`${name} contains an invalid value`);
  }
  return value;
}

function safeClaudeModel(value: string): string {
  if (!/^[A-Za-z0-9][A-Za-z0-9._:/@+\[\]\-]{0,159}$/.test(value)) {
    throw new Error(
      "SNIPER_CLAUDE_MODEL must be a Claude alias or model identifier without whitespace or shell syntax",
    );
  }
  return value;
}

export function executionMode(): ExecutionMode {
  return enumEnv("SNIPER_EXECUTION_MODE", ["live", "local"], "live");
}

export function brainProvider(): BrainProvider {
  // Claude Code is the visible Producer editor brain by default in both modes.
  // Codex remains an explicit opt-in for controlled comparisons/fallbacks.
  return enumEnv("SNIPER_BRAIN_PROVIDER", ["legacy", "codex"], "legacy");
}

export function brainProviderLabel(provider: BrainProvider = brainProvider()): string {
  return provider === "legacy" ? `Claude Code · ${claudeSettings().model}` : "Codex";
}

export function brainModel(provider: BrainProvider = brainProvider()): string {
  return provider === "legacy" ? claudeSettings().model : codexSettings().model;
}

/**
 * Every Claude Code subprocess receives this model explicitly. Never inherit
 * the operator's desktop/CLI default, which may be a much slower model.
 */
export function claudeSettings(): ClaudeSettings {
  return {
    model: safeClaudeModel(safeCliValue("SNIPER_CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL)),
  };
}

export function claudeModelArgs(model = claudeSettings().model): ["--model", string] {
  return ["--model", model];
}

export function codexSettings(): CodexSettings {
  // The provider validates effort against the resolved remote build, not just
  // the local CLI enum. gpt-5.6-sol rejected `ultra` on 2026-07-18 while xhigh
  // remained accepted, so keep the default inside the model's live contract.
  const reasoning = safeCliValue("SNIPER_CODEX_REASONING", "xhigh");
  if (!REASONING_LEVELS.has(reasoning)) {
    throw new Error(`SNIPER_CODEX_REASONING is unsupported: ${reasoning}`);
  }
  return {
    bin: safeCliValue("SNIPER_CODEX_BIN", "codex"),
    model: safeCliValue("SNIPER_CODEX_MODEL", "gpt-5.6-sol"),
    reasoning: reasoning as CodexReasoningLevel,
  };
}

/** Validate a per-invocation override at the runtime boundary as well as in TypeScript. */
export function codexReasoningLevel(value: unknown): CodexReasoningLevel {
  if (typeof value !== "string" || !REASONING_LEVELS.has(value)) {
    throw new Error(`Codex reasoning override must be one of: ${CODEX_REASONING_LEVELS.join(", ")}`);
  }
  return value as CodexReasoningLevel;
}

/**
 * Codex subscription mode must not inherit API keys or unrelated app secrets.
 * Authentication still comes from CODEX_HOME, which --ignore-user-config keeps.
 */
type EnvSource = Readonly<Record<string, string | undefined>>;

export function codexProcessEnv(source: EnvSource = process.env): NodeJS.ProcessEnv {
  return Object.fromEntries(
    Object.entries(source).filter(([key, value]) => SAFE_ENV_KEYS.has(key) && value !== undefined),
  ) as NodeJS.ProcessEnv;
}

/**
 * Keep Claude Code's subscription/config environment, but do not expose the
 * app's Deepgram/OpenAI/database credentials to model-invoked tools.
 */
export function claudeProcessEnv(source: EnvSource = process.env): NodeJS.ProcessEnv {
  return Object.fromEntries(
    Object.entries(source).filter(
      ([key, value]) =>
        value !== undefined && (CLAUDE_ENV_KEYS.has(key) || key.startsWith("CLAUDE_CODE_")),
    ),
  ) as NodeJS.ProcessEnv;
}
