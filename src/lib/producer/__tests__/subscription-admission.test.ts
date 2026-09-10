import assert from "node:assert/strict";
import { appendFileSync, existsSync } from "node:fs";
import { test } from "node:test";
import { claudeProcessEnv, codexProcessEnv } from "../../../app/api/_lib/ai-provider";
import { admitSubscriptionInvocation } from "../../../app/api/_lib/subscription-invocation";
import { buildCodexArgs } from "../../../app/api/_lib/codex-cli";
import { CLAUDE_STATUS, fakeSubscriptionCli } from "./_subscription-fake";

type Fake = ReturnType<typeof fakeSubscriptionCli>;
function request(fake: Fake, changes: { timeoutMs?: number; signal?: AbortSignal; provider?: "codex" | "claude" } = {}) {
  const provider = changes.provider ?? "claude";
  const env = provider === "codex" ? codexProcessEnv() : claudeProcessEnv({ ...process.env, ANTHROPIC_API_KEY: "TEST PRIVATE" });
  const args = provider === "codex" ? buildCodexArgs({ sandbox: "read-only", timeoutMs: 2000 }) : ["-p", "TEST ONLY"];
  return { bin: fake.bin, cwd: fake.root, args, provider, env, timeoutMs: 2000, ...changes };
}

test("admission uses one executable/environment/cwd and charges status time to the original budget", async () => {
  const fake = fakeSubscriptionCli({ delayMs: 100 });
  try {
    const admitted = await admitSubscriptionInvocation(request(fake));
    assert.ok(admitted.elapsedMs() >= 100);
    assert.ok(admitted.remainingMs() < 1900);
    assert.equal(admitted.bin, fake.bin);
    assert.equal(admitted.cwd, fake.root);
    assert.equal(admitted.env.ANTHROPIC_API_KEY, undefined);
    assert.equal(admitted.env.CLAUDE_CODE_DISABLE_FAST_MODE, "1");
    const calls = fake.calls(); assert.equal(calls.length, 2);
    assert.ok(calls.every((r) => r.cwd === fake.root && r.fast === "1" && r.secret === undefined));
    assert.deepEqual(calls[1].args.slice(0, 4), admitted.args.slice(0, 4));
    appendFileSync(fake.bin, "\n// altered executable\n");
    assert.throws(admitted.remainingMs, /changed/);
  } finally { fake.close(); }
});

test("unknown/pinned-version/API/cloud/oversize/failed statuses never admit inference or leak raw metadata", async () => {
  for (const options of [{ version: "future 99" }, { status: "PRIVATE ACCOUNT RAW" },
    { status: JSON.stringify({ ...CLAUDE_STATUS, apiKeySource: "PRIVATE API KEY" }) },
    { status: JSON.stringify({ ...CLAUDE_STATUS, apiProvider: "vertex" }) },
    { stderr: "PRIVATE ACCOUNT RAW" }, { oversize: true }, { exit: 1 }]) {
    const fake = fakeSubscriptionCli(options);
    try {
      await assert.rejects(admitSubscriptionInvocation(request(fake)), (error: Error) => {
        assert.doesNotMatch(error.message, /PRIVATE/); return true;
      });
      assert.ok(fake.calls().every((r) => r.args.includes("status") || r.args.includes("--version")));
    } finally { fake.close(); }
  }
});

test("Codex rejects API auth even though it reports logged in", async () => {
  const fake = fakeSubscriptionCli({ provider: "codex", status: "Logged in using an API key" });
  try { await assert.rejects(admitSubscriptionInvocation(request(fake, { provider: "codex" })), /ChatGPT/); }
  finally { fake.close(); }
});

test("already-cancelled invokes nothing; cancelled or expired status never receives a new deadline", async () => {
  const first = fakeSubscriptionCli(), controller = new AbortController(); controller.abort();
  try {
    await assert.rejects(admitSubscriptionInvocation(request(first, { signal: controller.signal })), /cancelled/);
    assert.equal(existsSync(`${first.root}/calls.jsonl`), false);
  } finally { first.close(); }
  for (const cancel of [false, true]) {
    const fake = fakeSubscriptionCli({ delayMs: 1500 }), active = new AbortController();
    const started = performance.now(), timer = cancel ? setTimeout(() => active.abort(), 100) : undefined;
    try {
      await assert.rejects(admitSubscriptionInvocation(request(fake, { timeoutMs: 300, signal: active.signal })), /cancelled|timed out/);
      assert.ok(performance.now() - started < 1200);
      assert.ok(fake.calls().length <= 2);
    } finally { clearTimeout(timer); fake.close(); }
  }
});
