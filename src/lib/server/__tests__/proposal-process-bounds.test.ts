import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { chmodSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { setTimeout as delay } from "node:timers/promises";
import { test } from "node:test";

const execute = promisify(execFile);
const codexModule = path.resolve("src/app/api/_lib/codex-cli.ts");
const legacyModule = path.resolve("src/app/api/producer/auto-edit/brain-review-process.ts");

function alive(pid: number) {
  try { process.kill(pid, 0); return true; } catch (error) { if ((error as NodeJS.ErrnoException).code === "ESRCH") return false; throw error; }
}

function harness(provider: "codex" | "legacy", cap: number | undefined) {
  const modulePath = provider === "codex" ? codexModule : legacyModule;
  const invoke = provider === "codex"
    ? `m.runCodex({prompt:'TEST ONLY',sandbox:'read-only',tools:'none',timeoutMs:1000,maxOutputBytes:${cap}})`
    : `m.runLegacyBrainProcess({args:['-p','TEST ONLY'],cwd:process.cwd(),timeoutMs:1000,maxOutputBytes:${cap}})`;
  return `import(${JSON.stringify(modulePath)}).then(async mod=>{const m=mod.default??mod;try{const r=await ${invoke};process.stdout.write(JSON.stringify({ok:true,message:r.message}));}
    catch(e){process.stdout.write(JSON.stringify({ok:false,error:e.message}));}})`;
}

function stub(directory: string, provider: "codex" | "legacy", mode: "oversize" | "stderr" | "unicode") {
  const file = path.join(directory, "fake-provider.cjs"), pidFile = path.join(directory, "owned-pids.json");
  const final = provider === "codex" ? { type: "item.completed", item: { type: "agent_message", text: "😀 café" } }
    : { type: "result", result: "😀 café" };
  const source = mode === "unicode"
    ? `const b=Buffer.from(${JSON.stringify(`${JSON.stringify(final)}\n`)});let i=0;const t=setInterval(()=>{if(i===b.length){clearInterval(t);return;}process.stdout.write(b.subarray(i,++i));},1);`
    : `const fs=require('node:fs'),{spawn}=require('node:child_process');const c=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'ignore'});
      fs.writeFileSync(${JSON.stringify(pidFile)},JSON.stringify([process.pid,c.pid]));setTimeout(()=>{process.${mode === "stderr" ? "stderr" : "stdout"}.write('x'.repeat(65536));},50);setInterval(()=>{},1000);`;
  const status = provider === "codex" ? "Logged in using ChatGPT"
    : JSON.stringify({ loggedIn: true, authMethod: "claude.ai", apiProvider: "firstParty", forcedLoginMethod: "claudeai", subscriptionType: "pro" });
  const version = provider === "codex" ? "codex-cli 0.144.1" : "2.1.247 (Claude Code)";
  const metadata = `const a=process.argv.slice(2);if(a.includes('--version')){console.log(${JSON.stringify(version)});process.exit(0);}
    if(a.includes('status')){console.log(${JSON.stringify(status)});process.exit(0);}`;
  writeFileSync(file, `#!${process.execPath}\n${metadata}\n${source}\n`); chmodSync(file, 0o700);
  return { file, pidFile };
}

for (const provider of ["codex", "legacy"] as const) {
  test(`${provider} optional byte budget rejects before accumulation and stops the exact owned child group`, async () => {
    const directory = mkdtempSync(path.join(os.tmpdir(), "sniper-proposal-process-"));
    try {
      for (const mode of ["oversize", "stderr"] as const) {
        const fake = stub(directory, provider, mode);
        const result = await execute(process.execPath, ["--import", "tsx", "-e", harness(provider, 1024)], {
          cwd: process.cwd(), env: { ...process.env, SNIPER_CODEX_BIN: fake.file, CLAUDE_BIN: fake.file }, timeout: 10_000,
        });
        const parsed = JSON.parse(result.stdout); assert.equal(parsed.ok, false); assert.match(parsed.error, /1024-byte output budget/);
        const pids = JSON.parse(readFileSync(fake.pidFile, "utf8")) as number[];
        for (let turn = 0; turn < 20 && pids.some(alive); turn += 1) await delay(25);
        assert.equal(pids.some(alive), false, "no provider leader or descendant remains alive after rejection");
      }
    } finally { rmSync(directory, { recursive: true, force: true }); }
  });
  test(`${provider} bounded Unicode split across stream chunks remains exact; omitted option preserves legacy success`, async () => {
    const directory = mkdtempSync(path.join(os.tmpdir(), "sniper-proposal-unicode-"));
    try {
      const fake = stub(directory, provider, "unicode");
      for (const cap of [1024, undefined]) {
        const result = await execute(process.execPath, ["--import", "tsx", "-e", harness(provider, cap)], {
          cwd: process.cwd(), env: { ...process.env, SNIPER_CODEX_BIN: fake.file, CLAUDE_BIN: fake.file }, timeout: 10_000,
        });
        const parsed = JSON.parse(result.stdout); assert.equal(parsed.ok, true);
        if (cap !== undefined || provider === "codex") assert.equal(parsed.message, "😀 café");
        // Existing uncapped legacy decoder behavior is deliberately unchanged by this additive option.
      }
    } finally { rmSync(directory, { recursive: true, force: true }); }
  });
}
