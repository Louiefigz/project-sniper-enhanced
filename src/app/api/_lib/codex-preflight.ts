import { spawnSync } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";
import { codexProcessEnv, codexSettings } from "./ai-provider";

export interface CodexPreflight {
  ready: boolean;
  version: string | null;
  authenticated: boolean;
  targetSyntaxSupported: boolean;
  detail: string | null;
}

interface CommandResult {
  ok: boolean;
  text: string;
}

function run(args: string[], env = codexProcessEnv()): CommandResult {
  const { bin } = codexSettings();
  const result = spawnSync(bin, args, { env, encoding: "utf8", timeout: 10_000 });
  const text = `${result.stdout ?? ""}\n${result.stderr ?? ""}`.trim();
  return { ok: result.status === 0 && !result.error, text };
}

function version(): string | null {
  const result = run(["--version"]);
  return result.ok ? result.text.split("\n").find((line) => line.includes("codex-cli")) ?? result.text : null;
}

function targetSyntax(): CommandResult {
  const settings = codexSettings();
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "sniper-codex-preflight-"));
  try {
    return run(
      ["-c", `model_reasoning_effort=${JSON.stringify(settings.reasoning)}`, "features", "list"],
      { ...codexProcessEnv(), CODEX_HOME: home },
    );
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
}

function authStatus(): CommandResult {
  return run(["-c", 'model_reasoning_effort="xhigh"', "login", "status"]);
}

function failureDetail(target: CommandResult, auth: CommandResult): string | null {
  if (!target.ok) return target.text.slice(-600) || "Installed Codex CLI does not accept the target reasoning level";
  if (!auth.ok) return auth.text.slice(-600) || "Codex subscription login was not found";
  if (!/logged in/i.test(auth.text)) return "Codex subscription login was not found";
  return null;
}

export function codexPreflight(): CodexPreflight {
  const target = targetSyntax();
  const auth = authStatus();
  const authenticated = auth.ok && /logged in/i.test(auth.text);
  return {
    ready: target.ok && authenticated,
    version: version(),
    authenticated,
    targetSyntaxSupported: target.ok,
    detail: failureDetail(target, auth),
  };
}
