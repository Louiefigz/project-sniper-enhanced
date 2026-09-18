import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { promisify } from "node:util";
import { textReviewPaidFeatureError } from "../../../app/api/_lib/paid-features";

/**
 * The paid features stay separately optional: Text Review needs an explicit
 * per-run opt-in plus a buyer-configured key, and Deepgram is never selected
 * by any app route. Nothing here starts Python or contacts a provider.
 */
const execute = promisify(execFile);
const read = (relative: string) => readFileSync(path.resolve(relative), "utf8");

test("Text Review refuses without explicit consent, then without a configured key", () => {
  assert.match(String(textReviewPaidFeatureError(undefined, { ANTHROPIC_API_KEY: "x" })), /optional paid feature/);
  assert.match(String(textReviewPaidFeatureError("yes", { ANTHROPIC_API_KEY: "x" })), /optional paid feature/);
  assert.match(String(textReviewPaidFeatureError(true, {})), /needs your own Anthropic API key/);
  assert.match(String(textReviewPaidFeatureError(true, { ANTHROPIC_API_KEY: "  " })), /needs your own Anthropic API key/);
  assert.equal(textReviewPaidFeatureError(true, { ANTHROPIC_API_KEY: "sk-ant-test-only" }), null);
});

test("the Text Review route checks the paid-feature gate before touching the file or Python", async () => {
  const route = path.resolve("src/app/api/frameio-review/review/route.ts");
  const script = `import(${JSON.stringify(route)}).then(async x=>{const m=x.default??x;
    const r=await m.POST(new Request("http://localhost/x",{method:"POST",body:JSON.stringify({filePath:"/definitely/missing.mp4"})}));
    process.stdout.write("\\nRESULT "+JSON.stringify({status:r.status,body:await r.json()})+"\\n");})`;
  const result = await execute(process.execPath, ["--import", "tsx", "-e", script], {
    cwd: process.cwd(), timeout: 20_000, env: { ...process.env, NEXT_PUBLIC_SNIPER_DEBUG: "0", ANTHROPIC_API_KEY: "sk-ant-test-only" },
  });
  const line = result.stdout.split("\n").find((row) => row.startsWith("RESULT "));
  assert.ok(line);
  const row = JSON.parse(line.slice(7));
  assert.equal(row.status, 400, "no consent: refused before the missing file is even checked");
  assert.match(row.body.error, /optional paid feature/);
});

test("the UI labels Text Review as paid before use and cannot start it without the opt-in", () => {
  const config = read("src/components/frameio-review/config-step.tsx");
  assert.match(config, /Optional paid feature — not part of your subscription/);
  assert.match(config, /sends still frames from this video[\s\S]*to Anthropic/);
  assert.match(config, /disabled=\{!config\.paidApiConsent\}/);
  assert.match(read("src/components/frameio-review/use-review-run.ts"), /paidApiConsent: config\.paidApiConsent/);
  assert.match(read("src/lib/frameio/types.ts"), /paidApiConsent: false/);
  assert.match(read("src/app/page.tsx"), /Optional paid add-on: it sends still frames to Anthropic on your own API key/);
});

test("the in-app privacy panel states what leaves the Mac without the retired Deepgram default", () => {
  const panel = read("src/app/page.tsx");
  const start = panel.indexOf("Where does my footage go?");
  const text = panel.slice(start, panel.indexOf("</details>", start));
  assert.match(text, /No feature of the app uploads a video or audio file/);
  assert.match(text, /still frames of each rendered edit[\s\S]*trim-only edits included/);
  assert.match(text, /not\s+enforced by the app/);
  assert.match(text, /yt-dlp[\s\S]*Chrome cookies are\s+used only when you tick/);
  assert.doesNotMatch(text, /Deepgram/);
});

test("no app route authorizes paid Deepgram transcription", () => {
  const hits: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const file = path.join(dir, name);
      if (statSync(file).isDirectory()) { if (name !== "__tests__") walk(file); continue; }
      if (/authorize-paid-asr/.test(readFileSync(file, "utf8"))) hits.push(path.relative(process.cwd(), file));
    }
  };
  walk(path.resolve("src"));
  assert.deepEqual(hits, [], "Deepgram needs --authorize-paid-asr on a direct script run; no route passes it");
});
