import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, realpathSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { setTimeout as delay } from "node:timers/promises";
import { codexProcessEnv } from "../../../app/api/_lib/ai-provider";
import { captureSubscriptionStatus, SubscriptionAuthenticationError } from "../../../app/api/_lib/subscription-status-process";
import { groupAlive, stopGroup } from "../../../app/api/producer/auto-edit/cut-preview-process";

type Mode = "valid" | "overflow" | "timeout" | "abort";
function fixture(mode: Mode) {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-auth-owned-unit-")));
  const file = path.join(root, "owned.json");
  const child = "process.on('SIGTERM',()=>{});console.log('ready');setInterval(()=>{},1000)";
  const code = `const {spawn}=require('node:child_process'),fs=require('node:fs');
    const c=spawn(process.execPath,['-e',${JSON.stringify(child)}],{stdio:['ignore','pipe','ignore']});
    c.stdout.once('data',()=>{fs.writeFileSync(${JSON.stringify(file)},JSON.stringify({leader:process.pid,child:c.pid}));
      c.stdout.destroy();c.unref();${mode === "valid" ? "console.log('Logged in using ChatGPT');"
      : mode === "overflow" ? "process.stdout.write('x'.repeat(50000));setInterval(()=>{},1000);"
      : "setInterval(()=>{},1000);"}});`;
  return { root, file, input: { bin: process.execPath, args: ["-e", code], cwd: root,
    env: codexProcessEnv(), timeoutMs: mode === "timeout" ? 400 : 2000 } };
}

function processAlive(pid: number): boolean {
  try { process.kill(pid, 0); return true; }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ESRCH") return false; throw error; }
}

async function cleanup(f: ReturnType<typeof fixture>): Promise<void> {
  try {
    const row = JSON.parse(readFileSync(f.file, "utf8"));
    if (groupAlive(row.leader)) assert.equal(await stopGroup(row.leader), true);
  } catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error; }
  rmSync(f.root, { recursive: true, force: true });
}

for (const mode of ["valid", "overflow", "timeout", "abort"] as const) {
  test(`${mode} metadata with a TERM-resistant ignored-stdio descendant rejects and observes group absence`, async () => {
    const f = fixture(mode), controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const started = performance.now();
    try {
      const work = captureSubscriptionStatus({ ...f.input, signal: controller.signal });
      if (mode === "abort") timer = setTimeout(() => controller.abort(), 400);
      await assert.rejects(work, (error: unknown) => {
        assert.ok(error instanceof SubscriptionAuthenticationError);
        assert.equal(error.cleanupVerified, true); assert.ok(error.cleanupMs >= 200);
        assert.equal(error.retryable, false); assert.doesNotMatch(error.message, /Logged in|x{10}/); return true;
      });
      const row = JSON.parse(readFileSync(f.file, "utf8"));
      assert.equal(groupAlive(row.leader), false); assert.equal(processAlive(row.child), false);
      assert.ok(performance.now() - started < 3000);
    } finally { clearTimeout(timer); await cleanup(f); }
  });
}

test("unknown process-group observation rejects with truthful cleanup state and no raw account output", async () => {
  const input = { bin: process.execPath, args: ["-e", "console.log('PRIVATE ACCOUNT RAW')"], cwd: process.cwd(),
    env: codexProcessEnv(), timeoutMs: 1000 };
  let stopped = false;
  await assert.rejects(captureSubscriptionStatus(input, {
    alive: () => { throw Object.assign(new Error("PRIVATE PROBE"), { code: "EPERM" }); },
    stop: async () => { stopped = true; return true; },
  }), (error: unknown) => {
    assert.ok(error instanceof SubscriptionAuthenticationError); assert.equal(error.cleanupVerified, false);
    assert.match(error.message, /unverified/); assert.doesNotMatch(error.message, /PRIVATE/); return true;
  });
  assert.equal(stopped, false, "do not signal a group whose observation is unknown");
});

test("a false cleanup observation never upgrades to success because a timer elapsed", async () => {
  const f = fixture("valid");
  try {
    await assert.rejects(captureSubscriptionStatus(f.input, { alive: groupAlive,
      stop: async () => { await delay(10); return false; } }), (error: unknown) => {
      assert.ok(error instanceof SubscriptionAuthenticationError); assert.equal(error.cleanupVerified, false); return true;
    });
    const row = JSON.parse(readFileSync(f.file, "utf8")); assert.equal(processAlive(row.child), true);
  } finally { await cleanup(f); }
});
