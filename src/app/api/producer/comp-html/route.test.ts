import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import vm from "node:vm";
import { createHash } from "node:crypto";
import { test } from "node:test";
import { NextRequest } from "next/server";
import { COMPS_CATALOG } from "@/lib/producer/comps-catalog";
import { GET } from "./route";
import { MOTION_DIR, readPreviewAsset, rewriteRuntimeUrls } from "./preview-assets";

function request(url: string) {
  return GET(new NextRequest(new URL(url, "http://localhost:3327")));
}

test("all 53 previews inline sandbox-safe runtimes; public asset helper retains exact byte identity", async () => {
  const assets = new Set<string>();
  const before = createHash("sha256"); const after = createHash("sha256");
  assert.equal(COMPS_CATALOG.length, 53);
  for (const comp of COMPS_CATALOG) {
    const file = path.join(MOTION_DIR, "compositions", `${comp.kind}.html`);
    before.update(fs.readFileSync(file));
    const query = new URLSearchParams({ kind: comp.kind, duration: "6", spec: JSON.stringify(comp.defaultSpec) });
    const response = await request(`/api/producer/comp-html?${query}`);
    assert.equal(response.status, 200, comp.kind);
    const html = await response.text();
    const markup = html.replace(/(<script\b[^>]*>)[\s\S]*?<\/script>/gu, "$1</script>");
    const external = [...markup.matchAll(/<(?:script|link)\b[^>]*(?:src|href)="([^"]+)"/gu)];
    assert.deepEqual(external.map((match) => match[1]), [], `${comp.kind}: no opaque-frame external runtimes`);
    assert.match(html, /data-sniper-runtime="gsap"/u);
    for (const script of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gu)) {
      assert.doesNotThrow(() => new vm.Script(script[1]), comp.kind);
    }
    // Public routes are helper coverage, NOT the opaque iframe transport.
    const mapped = rewriteRuntimeUrls(fs.readFileSync(file, "utf8"));
    const urls = [...mapped.matchAll(/<(?:script|link)\b[^>]*(?:src|href)="([^"]+)"/gu)];
    assert.ok(urls.length >= 2, comp.kind);
    for (const match of urls) {
      const url = match[1].replaceAll("&amp;", "&");
      assert.match(url, /^\/api\/producer\/comp-html\?runtime=/u, comp.kind);
      assets.add(url);
    }
    after.update(fs.readFileSync(file));
  }
  assert.equal(before.digest("hex"), after.digest("hex"), "source files remain untouched");
  assert.equal(assets.size, 7);
  const expectedFiles: Record<string, string> = {
    gsap: "vendor/gsap/gsap.min.js", splitText: "vendor/gsap/SplitText.min.js",
    drawSvg: "vendor/gsap/DrawSVGPlugin.min.js", motionTokens: "motion-tokens.js", tokens: "tokens.css",
    modulePipeline: "module-pipeline.js", agendaCaptionLayout: "agenda-caption-layout.css",
  };
  for (const url of assets) {
    const response = await request(url); const bytes = Buffer.from(await response.arrayBuffer());
    assert.equal(response.status, 200, url);
    const params = new URL(url, "http://local").searchParams;
    assert.equal(createHash("sha256").update(bytes).digest("hex"), params.get("sha"));
    assert.deepEqual(bytes, fs.readFileSync(path.join(MOTION_DIR, expectedFiles[params.get("runtime")!])));
    assert.match(response.headers.get("content-type") || "", /text\/(javascript|css)/u);
    assert.match(response.headers.get("cache-control") || "", /immutable/u);
  }
});

test("runtime allowlist and exact-byte cache binding fail closed", async () => {
  for (const key of ["../package.json", "__proto__", "constructor", "/vendor/gsap/gsap.min.js"]) {
    assert.equal((await request(`/api/producer/comp-html?runtime=${encodeURIComponent(key)}`)).status, 404);
  }
  assert.equal((await request("/api/producer/comp-html?runtime=gsap&sha=wrong")).status, 409);
  assert.equal((await request("/api/producer/comp-html?runtime=gsap")).headers.get("cache-control"), "no-cache");
  for (const query of ["asset=../package.json", "icon=../tokens.css", "asset=missing.js", "icon=missing.exe"]) {
    assert.equal((await request(`/api/producer/comp-html?${query}`)).status, 404);
  }
});

test("image selector reader rejects traversal, encoded paths, and symlink escapes", () => {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sniper-preview-assets-")));
  const assets = path.join(root, "assets"); fs.mkdirSync(assets);
  fs.mkdirSync(path.join(assets, "nested"));
  fs.writeFileSync(path.join(assets, "nested", "safe.jpeg"), "fixture");
  fs.writeFileSync(path.join(root, "outside.png"), "private");
  fs.symlinkSync(path.join(root, "outside.png"), path.join(assets, "linked.png"));
  try {
    assert.equal(readPreviewAsset(assets, "nested/safe.jpeg").toString(), "fixture");
    for (const name of ["../outside.png", "%2e%2e/outside.png", "nested/../safe.jpeg", "nested\\safe.jpeg", "linked.png", "/outside.png"]) {
      assert.throws(() => readPreviewAsset(assets, name), /Forbidden/u, name);
    }
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test("relative and root-relative selectors retain their values while exact local bytes are embedded", async () => {
  for (const [kind, key, value] of [["ui-focus-zoom", "image", "assets/sample-screen.png"],
    ["avatar-bio-card", "avatarSrc", "/assets/sample-screen.png"]]) {
    const query = new URLSearchParams({ kind, spec: JSON.stringify({ [key]: value }) });
    const html = await (await request(`/api/producer/comp-html?${query}`)).text();
    const script = html.match(/<script>([\s\S]*?)<\/script>/u)?.[1];
    assert.ok(script);
    const window = { addEventListener() {} }; vm.runInNewContext(script, { window });
    const variables = (window as unknown as { __hyperframes: { getVariables: () => Record<string, string> } }).__hyperframes.getVariables();
    assert.equal(variables[key], value);
    assert.ok(html.includes("data:image/png;base64,"), "referenced image is embedded");
    assert.ok(!html.includes("/api/producer/comp-html?asset="), "no opaque-frame local API fetch");
  }
});

test("dark-surface Elements samples match declared light accents without migrating authored specs", async () => {
  for (const [kind, key] of [["statement-card", "accent"], ["fragment-payoff", "accentColor"]]) {
    const html = fs.readFileSync(path.join(MOTION_DIR, "compositions", `${kind}.html`), "utf8");
    const declared = JSON.parse(html.match(/data-composition-variables='([\s\S]*?)'/u)![1]) as { id: string; default: unknown }[];
    const accent = declared.find((field) => field.id === key)!.default;
    assert.equal(COMPS_CATALOG.find((comp) => comp.kind === kind)!.defaultSpec[key], accent);
    const query = new URLSearchParams({ kind, spec: JSON.stringify({ [key]: "#123456" }) });
    const output = await (await request(`/api/producer/comp-html?${query}`)).text();
    assert.ok(output.includes(`"${key}":"#123456"`), "authored accent remains untouched");
  }
});
