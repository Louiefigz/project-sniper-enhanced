import { chmodSync, existsSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { SUBSCRIPTION_VERSIONS, type SubscriptionProvider } from "../../../app/api/_lib/subscription-policy";

export const CLAUDE_STATUS = { loggedIn: true, authMethod: "claude.ai", apiProvider: "firstParty",
  forcedLoginMethod: "claudeai", subscriptionType: "pro", analyticsDisabled: false };

interface FakeOptions {
  provider?: SubscriptionProvider; status?: string; version?: string;
  delayMs?: number; stderr?: string; exit?: number; oversize?: boolean;
}

/** A local fake executable only. No installed provider or credential access. */
export function fakeSubscriptionCli(options: FakeOptions = {}) {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-subscription-unit-")));
  const bin = path.join(root, "fake.cjs"), log = path.join(root, "calls.jsonl");
  const provider = options.provider ?? "claude";
  const status = options.status ?? (provider === "codex" ? "Logged in using ChatGPT" : JSON.stringify(CLAUDE_STATUS));
  const version = options.version ?? SUBSCRIPTION_VERSIONS[provider];
  const source = `#!${process.execPath}
const fs=require('node:fs');const args=process.argv.slice(2);
fs.appendFileSync(${JSON.stringify(log)},JSON.stringify({args,cwd:process.cwd(),pid:process.pid,
 fast:process.env.CLAUDE_CODE_DISABLE_FAST_MODE,secret:process.env.ANTHROPIC_API_KEY})+'\\n');
if(args.includes('--version')){console.log(${JSON.stringify(version)});process.exit(0);}
if(args.includes('status')){setTimeout(()=>{
 process.stderr.write(${JSON.stringify(options.stderr ?? "")});
 process.stdout.write(${JSON.stringify(options.oversize ? "x".repeat(40000) : status)});
 process.exitCode=${options.exit ?? 0};},${options.delayMs ?? 0});}
else{process.stdout.write(JSON.stringify({type:'result',result:'TEST ONLY'}));}
`;
  writeFileSync(bin, source); chmodSync(bin, 0o700);
  return { bin, root, calls: () => existsSync(log) ? readFileSync(log, "utf8").trim().split("\n").map((s) => JSON.parse(s)) : [],
    close: () => rmSync(root, { recursive: true, force: true }) };
}
