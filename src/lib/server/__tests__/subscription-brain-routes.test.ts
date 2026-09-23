import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { chmodSync, existsSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, statSync, writeFileSync } from "node:fs";
import http from "node:http";
import type { AddressInfo } from "node:net";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { promisify } from "node:util";
import { CLAUDE_STATUS } from "../../producer/__tests__/_subscription-fake";
import { SUBSCRIPTION_VERSIONS } from "../../../app/api/_lib/subscription-policy";

/**
 * Segmenter and Clipper reach the model only through the selected subscription
 * CLI. Every scenario runs the real route/action module in a child process with
 * a local CLI stub (no provider, no credential store) and a paid-API bait:
 * ANTHROPIC_API_KEY is set and ANTHROPIC_BASE_URL points at a local listener
 * that counts requests. Any SDK client would hit that listener.
 */
const execute = promisify(execFile);
const api = path.resolve("src/app/api");
const ANSWERS: Record<string, unknown> = {
  segmenter: { segments: [{ id: 1, title: "Intro", startLine: 0, startSec: 0, endSec: 2, summary: "S" }] },
  "clipper-decisions": { decisions: [{ index: 0, action: "KEEP", trimmed_text: null },
    { index: 1, action: "REMOVE", trimmed_text: null }] },
  "clipper-validation": { all_valid: false, issues: [{ clip_index: 1, action: "REMOVE", reason: "fragment" }] },
};

interface Stub { bin: string; root: string; media: string; calls: () => Record<string, unknown>[]; close: () => void }

/** A local executable standing in for either pinned CLI; it never contacts anything. */
function stubCli(provider: "claude" | "codex", fail = false): Stub {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-brain-route-")));
  const bin = path.join(root, "cli.cjs"), log = path.join(root, "calls.jsonl"), media = path.join(root, "probe.mp4");
  writeFileSync(media, "not really video");
  const status = provider === "codex" ? "Logged in using ChatGPT" : JSON.stringify(CLAUDE_STATUS);
  writeFileSync(bin, `#!${process.execPath}
const fs=require('node:fs');const args=process.argv.slice(2);const answers=${JSON.stringify(ANSWERS)};
if(args.includes('--version')){console.log(${JSON.stringify(SUBSCRIPTION_VERSIONS[provider])});process.exit(0);}
if(args.includes('status')){process.stdout.write(${JSON.stringify(status)});process.exit(0);}
let mediaReadable=true;try{fs.readFileSync(${JSON.stringify(media)});}catch{mediaReadable=false;}
const stdin=fs.readFileSync(0,'utf8');
const schemaArg=args[args.indexOf(${JSON.stringify(provider === "codex" ? "--output-schema" : "--json-schema")})+1]||'';
const schema=Object.keys(answers).find((name)=>${provider === "codex"
    ? "schemaArg.endsWith('/'+name+'.schema.json')"
    : "JSON.stringify(answers[name])&&Object.keys(answers[name]).every((key)=>schemaArg.includes('\"'+key+'\"'))"});
fs.appendFileSync(${JSON.stringify(log)},JSON.stringify({args,stdin,schema,mediaReadable,
  apiKey:process.env.ANTHROPIC_API_KEY??null,baseUrl:process.env.ANTHROPIC_BASE_URL??null})+'\\n');
if(${fail}){process.stdout.write(${JSON.stringify(provider === "codex"
    ? JSON.stringify({ type: "turn.failed", error: { message: "usage limit reached (stub)" } })
    : JSON.stringify({ type: "result", subtype: "success", is_error: true, result: "usage limit reached (stub)" }))});process.exit(1);}
const answer=answers[schema];
process.stdout.write(${provider === "codex"
    ? "JSON.stringify({type:'item.completed',item:{type:'agent_message',text:JSON.stringify(answer)}})+'\\n'"
    : "JSON.stringify({type:'result',subtype:'success',is_error:false,result:'',structured_output:answer})"});
`);
  chmodSync(bin, 0o700);
  const calls = () => existsSync(log) ? readFileSync(log, "utf8").trim().split("\n").map((row) => JSON.parse(row)) : [];
  return { bin, root, media, calls, close: () => rmSync(root, { recursive: true, force: true }) };
}

/** Counts any HTTP request that reaches the paid-API bait. */
async function paidApiBait(): Promise<{ url: string; hits: () => number; close: () => Promise<void> }> {
  let hits = 0;
  const server = http.createServer((_req, res) => { hits += 1; res.writeHead(500).end(); });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  return { url: `http://127.0.0.1:${port}`, hits: () => hits,
    close: () => new Promise((resolve) => server.close(() => resolve())) };
}

const TRANSCRIPT = [
  { start: 0, end: 1, text: "MARK-LINE-ZERO hello", words: [{ word: "hello", start: 0.1, end: 0.5 }] },
  { start: 1, end: 2, text: "MARK-LINE-ONE um so", words: [{ word: "so", start: 1.1, end: 1.4 }] },
];
const CALLS = {
  segmenter: `(await load(${JSON.stringify(path.join(api, "segmenter/segment/route.ts"))})).POST(new Request("http://localhost/x",{method:"POST",body:JSON.stringify({transcript:${JSON.stringify(TRANSCRIPT)},prompt:"MARK-USER-PROMPT"})})).then(async r=>({status:r.status,body:await r.json()}))`,
  clipper: `(await load(${JSON.stringify(path.join(api, "clipper/clip-preview/route.ts"))})).POST(new Request("http://localhost/x",{method:"POST",body:JSON.stringify({transcript:${JSON.stringify(TRANSCRIPT)},prompt:"MARK-USER-PROMPT"})})).then(async r=>({status:r.status,brain:r.headers.get("X-Sniper-Brain"),body:await r.text()}))`,
  validation: `(await load(${JSON.stringify(path.resolve("src/app/(tools)/clipper/actions/validate-assembly.ts"))})).validateAssembledOutput([{clipIndex:0,text:"MARK-CLIP-ZERO",beforeContext:null,afterContext:null},{clipIndex:1,text:"and then",beforeContext:null,afterContext:null}])`,
} as const;

async function runScenario(call: keyof typeof CALLS, env: Record<string, string>): Promise<Record<string, unknown>> {
  const script = `const load=async(file)=>{const m=await import(file);return m.default??m;};(async()=>{const out=await ${CALLS[call]};process.stdout.write("\\nRESULT "+JSON.stringify(out)+"\\n");})()`;
  const result = await execute(process.execPath, ["--import", "tsx", "-e", script], {
    cwd: process.cwd(), timeout: 30_000,
    env: { ...process.env, NEXT_PUBLIC_SNIPER_DEBUG: "0", SNIPER_DEBUG: "0", SNIPER_PROVIDER: "",
      SNIPER_BRAIN_PROVIDER: "", ...env },
  });
  const line = result.stdout.split("\n").reverse().find((row) => row.startsWith("RESULT "));
  assert.ok(line, `no result line: ${result.stdout.slice(-400)}`);
  return JSON.parse(line.slice("RESULT ".length));
}

function assertOnlyCliReachedModel(stub: Stub, bait: { hits: () => number }, marker: string): Record<string, unknown> {
  assert.equal(bait.hits(), 0, "no SDK client may contact the paid API");
  const inference = stub.calls();
  assert.equal(inference.length, 1, "exactly one inference call, no retry through another route");
  const [row] = inference;
  assert.equal(row.apiKey, null, "the CLI never inherits an API key");
  assert.equal(row.baseUrl, null, "the CLI never inherits an API base URL");
  assert.equal(row.mediaReadable, false, "the CLI runs under the OS media boundary");
  assert.match(String(row.stdin), new RegExp(marker), "the task text travels on stdin");
  return row;
}

async function withSetup(provider: "claude" | "codex", fail: boolean,
  run: (stub: Stub, env: Record<string, string>, bait: Awaited<ReturnType<typeof paidApiBait>>) => Promise<void>) {
  const stub = stubCli(provider, fail), bait = await paidApiBait();
  const env: Record<string, string> = {
    ANTHROPIC_API_KEY: "sk-ant-test-only-bait", ANTHROPIC_BASE_URL: bait.url,
    ...(provider === "codex"
      ? { SNIPER_PROVIDER: "codex", SNIPER_BRAIN_PROVIDER: "codex", SNIPER_CODEX_BIN: stub.bin, CLAUDE_BIN: "/definitely/missing/claude" }
      : { SNIPER_PROVIDER: "claude", SNIPER_BRAIN_PROVIDER: "legacy", CLAUDE_BIN: stub.bin, SNIPER_CODEX_BIN: "/definitely/missing/codex" }),
  };
  try { await run(stub, env, bait); } finally { stub.close(); await bait.close(); }
}

const claudeCall = (row: Record<string, unknown>) => {
  const args = row.args as string[];
  assert.deepEqual(args.slice(0, 2), ["--setting-sources", ""], "no user/project/local settings");
  assert.equal(args[args.indexOf("--tools") + 1], "", "no tools");
  assert.ok(args.includes("-p") && args.includes("--strict-mcp-config") && args.includes("--no-session-persistence"));
  assert.equal(args[args.indexOf("--model") + 1], "opus", "the configured Claude model");
};

for (const call of Object.keys(CALLS) as (keyof typeof CALLS)[]) {
  test(`${call}: Claude route spawns the subscription CLI, never an SDK client, even with ANTHROPIC_API_KEY set`, async () => {
    await withSetup("claude", false, async (stub, env, bait) => {
      const out = await runScenario(call, env);
      const row = assertOnlyCliReachedModel(stub, bait, call === "validation" ? "MARK-CLIP-ZERO" : "MARK-LINE-ONE");
      claudeCall(row);
      if (call === "segmenter") {
        assert.equal(out.status, 200);
        assert.deepEqual((out.body as Record<string, unknown>).brain, { provider: "legacy", model: "opus" });
      } else if (call === "clipper") {
        assert.equal(out.status, 200); assert.equal(out.brain, "legacy:opus");
        assert.match(String(out.body), /"REMOVE"/);
      } else assert.deepEqual(out, { removeClips: [1], flagClips: [] });
    });
  });

  test(`${call}: Codex route uses the tool-less Codex adapter`, async () => {
    await withSetup("codex", false, async (stub, env, bait) => {
      const out = await runScenario(call, env);
      const row = assertOnlyCliReachedModel(stub, bait, call === "validation" ? "MARK-CLIP-ZERO" : "MARK-LINE-ONE");
      const args = row.args as string[];
      assert.ok(args.includes("exec") && args.includes("--ignore-user-config") && args.at(-1) === "-");
      assert.ok(args.includes("shell_tool"), "Codex runs with its tools disabled");
      assert.equal(args[args.indexOf("--model") + 1], "gpt-5.6-sol");
      if (call === "segmenter") assert.deepEqual((out.body as Record<string, unknown>).brain, { provider: "codex", model: "gpt-5.6-sol" });
      else if (call === "clipper") assert.equal(out.brain, "codex:gpt-5.6-sol");
      else assert.deepEqual(out, { removeClips: [1], flagClips: [] });
    });
  });

  test(`${call}: a failing CLI is reported as a failure with no fallback`, async () => {
    for (const provider of ["claude", "codex"] as const) {
      await withSetup(provider, true, async (stub, env, bait) => {
        const out = await runScenario(call, env);
        assertOnlyCliReachedModel(stub, bait, call === "validation" ? "MARK-CLIP-ZERO" : "MARK-LINE-ONE");
        if (call === "validation") assert.deepEqual(out, { removeClips: [], flagClips: [] });
        else {
          assert.equal(out.status, 502);
          assert.match(JSON.stringify(out.body), /usage limit reached \(stub\)/);
        }
      });
    }
  });
}

test("disagreeing provider settings are refused before any CLI starts", async () => {
  await withSetup("claude", false, async (stub, env, bait) => {
    const out = await runScenario("segmenter", { ...env, SNIPER_BRAIN_PROVIDER: "codex" });
    assert.equal(out.status, 502);
    assert.match(JSON.stringify(out.body), /select different editor brains/);
    assert.equal(stub.calls().length, 0); assert.equal(bait.hits(), 0);
  });
});

test("no application source constructs or imports the Anthropic SDK", () => {
  const offenders: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const file = path.join(dir, name);
      if (statSync(file).isDirectory()) { if (name !== "node_modules") walk(file); continue; }
      if (!/\.(ts|tsx|mjs|js)$/.test(name) || name === "subscription-brain-routes.test.ts") continue;
      const text = readFileSync(file, "utf8");
      if (/@anthropic-ai\/sdk|new Anthropic\(/.test(text)) offenders.push(path.relative(process.cwd(), file));
    }
  };
  walk(path.resolve("src"));
  assert.deepEqual(offenders, []);
});
