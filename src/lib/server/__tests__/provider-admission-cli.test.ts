/**
 * The install doctor's provider check must agree with production admission.
 *
 * Each case installs a fake CLI that prints a chosen `--version` and a chosen
 * authentication status, then runs the doctor's adapter (which calls the same
 * `admitSubscriptionInvocation` as every real inference). Only a genuine
 * subscription login at the exact pinned version may report ready.
 */
import assert from "node:assert/strict";
import { chmodSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { checkProviderAdmission, selectedProvider } from "../../../../scripts/infra/provider-admission";
import { SUBSCRIPTION_VERSIONS } from "@/app/api/_lib/subscription-policy";

const CLAUDE_OK = { loggedIn: true, authMethod: "claude.ai", apiProvider: "firstParty",
  forcedLoginMethod: "claudeai", subscriptionType: "max" };

function fakeCli(dir: string, name: string, version: string, status: string, stderr = "", statusExit = 0): string {
  const file = path.join(dir, name);
  const escaped = (value: string) => value.replace(/'/gu, "'\\''");
  writeFileSync(file, `#!/bin/bash
for arg in "$@"; do
  if [ "$arg" = "--version" ]; then printf '%s\\n' '${escaped(version)}'; exit 0; fi
  if [ "$arg" = "status" ]; then
    printf '%s' '${escaped(status)}'
    ${stderr ? `printf '%s' '${escaped(stderr)}' >&2` : ""}
    exit ${statusExit}
  fi
done
exit 3
`);
  chmodSync(file, 0o755);
  return file;
}

async function check(provider: "codex" | "claude", version: string, status: string, stderr = "", statusExit = 0) {
  const dir = mkdtempSync(path.join(os.tmpdir(), "sniper-admission-"));
  const saved = { codex: process.env.SNIPER_CODEX_BIN, claude: process.env.CLAUDE_BIN };
  try {
    const bin = fakeCli(dir, provider, version, status, stderr, statusExit);
    if (provider === "codex") process.env.SNIPER_CODEX_BIN = bin; else process.env.CLAUDE_BIN = bin;
    return await checkProviderAdmission(provider);
  } finally {
    if (saved.codex === undefined) delete process.env.SNIPER_CODEX_BIN; else process.env.SNIPER_CODEX_BIN = saved.codex;
    if (saved.claude === undefined) delete process.env.CLAUDE_BIN; else process.env.CLAUDE_BIN = saved.claude;
    rmSync(dir, { recursive: true, force: true });
  }
}

async function main() {
  const codexOk = SUBSCRIPTION_VERSIONS.codex, claudeOk = SUBSCRIPTION_VERSIONS.claude;

  // Valid subscription logins at the pinned versions are the only ready states.
  assert.equal((await check("codex", codexOk, "Logged in using ChatGPT\n")).ready, true);
  assert.equal((await check("claude", claudeOk, JSON.stringify(CLAUDE_OK))).ready, true);

  // An API-key login reports "logged in" too; it must not pass.
  const apiKey = await check("codex", codexOk, "Logged in using an API key - sk-***\n");
  assert.equal(apiKey.ready, false); assert.equal(apiKey.reason, "not-signed-in-or-not-subscription");
  const claudeKey = await check("claude", claudeOk, JSON.stringify({ ...CLAUDE_OK, apiKeySource: "ANTHROPIC_API_KEY" }));
  assert.equal(claudeKey.ready, false); assert.equal(claudeKey.reason, "not-signed-in-or-not-subscription");

  // Logged out: exit 0 is not readiness.
  const loggedOut = await check("claude", claudeOk, JSON.stringify({ loggedIn: false, authMethod: "none", apiProvider: "firstParty" }));
  assert.equal(loggedOut.ready, false); assert.equal(loggedOut.reason, "not-signed-in-or-not-subscription");
  assert.equal((await check("codex", codexOk, "Not logged in\n")).ready, false);
  // The real CLIs exit 1 when signed out; that is "not signed in", not "unknown".
  const exitOne = await check("claude", claudeOk, JSON.stringify({ loggedIn: false, authMethod: "none", apiProvider: "firstParty" }), "", 1);
  assert.equal(exitOne.ready, false); assert.equal(exitOne.reason, "not-signed-in-or-not-subscription");

  // Malformed and unknown metadata fail closed.
  assert.equal((await check("claude", claudeOk, "{not json")).reason, "not-signed-in-or-not-subscription");
  assert.equal((await check("claude", claudeOk, JSON.stringify({ ...CLAUDE_OK, unexpectedKey: 1 }))).ready, false);
  assert.equal((await check("claude", claudeOk, JSON.stringify({ ...CLAUDE_OK, subscriptionType: "free" }))).ready, false);

  // Any other CLI build is refused, including a newer one.
  const newer = await check("codex", "codex-cli 0.154.0", "Logged in using ChatGPT\n");
  assert.equal(newer.ready, false); assert.equal(newer.reason, "wrong-version");
  assert.equal((await check("claude", "2.1.274 (Claude Code)", JSON.stringify(CLAUDE_OK))).reason, "wrong-version");

  // Diagnostics on stderr are refused rather than ignored.
  const noisy = await check("claude", claudeOk, JSON.stringify(CLAUDE_OK), "warning: something\n");
  assert.equal(noisy.ready, false); assert.equal(noisy.reason, "unexpected-diagnostics");

  // A missing CLI is its own reason.
  process.env.CLAUDE_BIN = "/definitely/missing/claude";
  assert.equal((await checkProviderAdmission("claude")).reason, "cli-missing");
  delete process.env.CLAUDE_BIN;

  // The doctor checks the provider the app will use, not whichever one happens to work.
  const savedBrain = process.env.SNIPER_BRAIN_PROVIDER;
  process.env.SNIPER_BRAIN_PROVIDER = "codex"; assert.equal(selectedProvider(), "codex");
  process.env.SNIPER_BRAIN_PROVIDER = "legacy"; assert.equal(selectedProvider(), "claude");
  if (savedBrain === undefined) delete process.env.SNIPER_BRAIN_PROVIDER; else process.env.SNIPER_BRAIN_PROVIDER = savedBrain;

  // No report ever carries account metadata.
  const report = await check("claude", claudeOk, JSON.stringify({ ...CLAUDE_OK, email: "person@example.com", orgName: "Org" }));
  assert.doesNotMatch(JSON.stringify(report), /person@example\.com|Org"/u);
  console.log("provider-admission-cli.test.ts: all assertions passed");
}

void main().catch((error) => { console.error(error); process.exitCode = 1; });
