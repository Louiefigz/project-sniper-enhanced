import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import path from "node:path";
import { test } from "node:test";
import { promisify } from "node:util";
import { fakeSubscriptionCli } from "../../producer/__tests__/_subscription-fake";

const execute = promisify(execFile);
const root = path.resolve("src/app/api");
const entries = [
  ["codex", "_lib/codex-cli.ts", "runCodex({prompt:'TEST ONLY',sandbox:'read-only',timeoutMs:2000})"],
  ["claude brain", "producer/auto-edit/brain-review-process.ts", "runLegacyBrainProcess({args:['-p','TEST ONLY'],cwd:process.cwd(),timeoutMs:2000})"],
  ["Claude authoring", "producer/auto-edit/claude-authoring-process.ts", "runClaudeAuthoringProcess({dir:process.cwd(),scope:'light'},()=>{},'visual',['-p','TEST ONLY'])"],
  ["native Claude", "producer/ai-edit/palmier-native-process.ts", "runLegacyNative({args:['-p','TEST ONLY'],cwd:process.cwd(),timeoutMs:2000})"],
  ["live MCP Claude", "producer/live-build/process.ts", "runLiveBuildProcess({args:['-p','TEST ONLY','--mcp-config','TEST EXACT','--strict-mcp-config'],cwd:process.cwd(),expectedSessionId:'TEST',onEvent:()=>{}})"],
] as const;

for (const [name, relative, call] of entries) {
  test(`${name}: actual execution sink refuses API auth without an inference process`, async () => {
    const fake = fakeSubscriptionCli({ provider: name === "codex" ? "codex" : "claude", status: "Logged in using an API key PRIVATE" });
    const script = `import(${JSON.stringify(path.join(root, relative))}).then(async x=>{const m=x.default??x;
      try{await m.${call};throw Error('ADMITTED');}catch(e){process.stdout.write(JSON.stringify({error:e.message}));}})`;
    try {
      const result = await execute(process.execPath, ["--import", "tsx", "-e", script], {
        cwd: process.cwd(), env: { ...process.env, CLAUDE_BIN: fake.bin, SNIPER_CODEX_BIN: fake.bin }, timeout: 8000,
      });
      const row = JSON.parse(result.stdout); assert.match(row.error, /authentication/);
      assert.doesNotMatch(row.error, /PRIVATE|ADMITTED/);
      assert.equal(fake.calls().length, 2);
      assert.ok(fake.calls().every((r) => r.args.includes("status") || r.args.includes("--version")));
    } finally { fake.close(); }
  });
}

test("AI-edit stream: auth failure terminates, rolls back only test staging, releases once and invokes no model", async () => {
  const fake = fakeSubscriptionCli({ status: "PRIVATE API AUTH" });
  const script = `import(${JSON.stringify(path.join(root, "producer/ai-edit/edit-streams.ts"))}).then(async x=>{
    const m=x.default??x;let releases=0;const dir=${JSON.stringify(fake.root)};
    const stream=m.createAiEditStream({provider:'legacy',model:'TEST',args:['-p','TEST ONLY']},
      {dir,planPath:dir+'/test-plan.json',originalPlanText:'{}\\n',parentPlanHash:'TEST'},()=>{releases++});
    const reader=stream.getReader();let text='';for(;;){const r=await reader.read();if(r.done)break;text+=new TextDecoder().decode(r.value);}
    process.stdout.write(JSON.stringify({text,releases}));})`;
  try {
    const result = await execute(process.execPath, ["--import", "tsx", "-e", script], {
      cwd: process.cwd(), env: { ...process.env, CLAUDE_BIN: fake.bin, SNIPER_DEBUG: "0" }, timeout: 8000,
    });
    const row = JSON.parse(result.stdout); assert.match(row.text, /authentication/);
    assert.doesNotMatch(row.text, /PRIVATE|ai_done/); assert.equal(row.releases, 1);
    assert.equal(fake.calls().length, 2);
  } finally { fake.close(); }
});

test("Codex preflight never treats an API-key logged-in status as subscription-ready or reveals raw status", async () => {
  const fake = fakeSubscriptionCli({ provider: "codex", status: "Logged in using an API key PRIVATE" });
  const script = `import(${JSON.stringify(path.join(root, "_lib/codex-preflight.ts"))}).then(async x=>process.stdout.write(JSON.stringify(await(x.default??x).codexPreflight())))`;
  try {
    const result = await execute(process.execPath, ["--import", "tsx", "-e", script], {
      cwd: process.cwd(), env: { ...process.env, SNIPER_CODEX_BIN: fake.bin }, timeout: 8000,
    });
    const row = JSON.parse(result.stdout); assert.equal(row.ready, false); assert.equal(row.authenticated, false);
    assert.doesNotMatch(result.stdout, /PRIVATE/);
  } finally { fake.close(); }
});

test("runtime GET awaits rejected unknown-version preflight instead of serializing a truthy Promise", async () => {
  const fake = fakeSubscriptionCli({ provider: "codex", version: "UNKNOWN PRIVATE" });
  const script = `import(${JSON.stringify(path.join(root, "runtime/route.ts"))}).then(async x=>{
    const r=await(x.default??x).GET(new Request('http://localhost/api/runtime'));process.stdout.write(JSON.stringify(await r.json()));})`;
  try {
    const result = await execute(process.execPath, ["--import", "tsx", "-e", script], {
      cwd: process.cwd(), env: { ...process.env, SNIPER_CODEX_BIN: fake.bin, SNIPER_BRAIN_PROVIDER: "codex",
        SNIPER_EXECUTION_MODE: "live", SNIPER_TRANSCRIBE_PROVIDER: "test-only-no-preflight" }, timeout: 8000,
    });
    const row = JSON.parse(result.stdout); assert.equal(row.codex.ready, false); assert.equal(row.codex.authenticated, false);
    assert.equal(typeof row.codex.detail, "string"); assert.doesNotMatch(result.stdout, /UNKNOWN PRIVATE/);
    assert.equal(fake.calls().length, 1);
  } finally { fake.close(); }
});
