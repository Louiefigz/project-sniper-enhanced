import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
import { runStudioCommand, STUDIO_CLI } from "./process";

const require = createRequire(import.meta.url);
const interop = require("./review-attribute-interop.cjs");
const original = fs.readFileSync(STUDIO_CLI, "utf8");

function parserScope() {
  const source = interop.transformCliSource(original) as string;
  const prefix = source.slice(source.indexOf("var __create ="), source.indexOf("// ../../node_modules/.bun/@jridgewell+sourcemap-codec"))
    .replace(/^import \{ parseArgs as parseArgs\$1 \} from "util";$/mu, "var parseArgs$1 = require('node:util').parseArgs;");
  const attrs = source.slice(source.indexOf("function readAttr("), source.indexOf("function collectCompositionIds("));
  const start = source.indexOf("// invalid_variable_values_json");
  const rule = source.slice(source.indexOf("({ tags }) => {", start), source.indexOf("// invalid_composition_variables_declaration", start))
    .trim().replace(/,$/u, "");
  const scope = vm.createContext({ require, Buffer, console, process });
  vm.runInContext(`${prefix}\n${attrs}\nfunction truncateSnippet(s){return s;}\nconst rule=${rule};`, scope, { timeout: 3000 });
  return scope;
}

test("the exact pinned StaticGuard accepts serializer entities but retains malformed JSON and object checks", () => {
  const scope = parserScope();
  const valid = [String.raw`<div id="a" data-variable-values='{"text":"Literal"}'>`,
    '<div data-variable-values="{&quot;text&quot;:&quot;A &amp; B&quot;}">',
    '<div data-variable-values="{&#34;text&#34;:&#34;&#x1F600;&#34;}">'];
  for (const tag of valid) {
    scope.tag = tag;
    assert.equal(vm.runInContext("rule({tags:[{raw:tag}]}).length", scope), 0, tag);
  }
  for (const tag of ['<div data-variable-values="{bad}">', '<div data-variable-values="[]">',
    '<div data-variable-values="null">', '<div data-variable-values="{&amp;quot;text&amp;quot;:1}">']) {
    scope.tag = tag;
    assert.equal(vm.runInContext("rule({tags:[{raw:tag}]})[0].code", scope), "invalid_variable_values_json", tag);
  }
  scope.tag = '<html data-composition-variables="[{&quot;id&quot;:&quot;text&quot;}]">';
  assert.equal(vm.runInContext("JSON.parse(readJsonAttr(tag,'data-composition-variables'))[0].id", scope), "text");
  assert.equal(vm.runInContext(`readJsonAttr('<div data-other="&quot;">','data-other')`, scope), "&quot;");
});

test("load hook refuses unavailable capability, changed CLI and unexpected load format; unrelated loads are untouched", () => {
  assert.throws(() => interop.registerCliInterop(STUDIO_CLI, {}), /requires Node registerHooks/u);
  assert.throws(() => interop.transformCliSource(`${original}\n`), /exact audited CLI bytes/u);
  let hook: { load: (url: string, context: object, next: () => object) => object } | undefined;
  let deregistered = 0;
  interop.registerCliInterop(STUDIO_CLI, { registerHooks: (value: typeof hook) => {
    hook = value; return { deregister: () => { deregistered += 1; } };
  } });
  const plain = { format: "module", source: "unrelated" };
  assert.equal(hook!.load("file:///unrelated.js", {}, () => plain), plain);
  assert.throws(() => hook!.load(pathToFileURL(STUDIO_CLI).href, {}, () => ({ format: "commonjs", source: original })), /audited ESM/u);
  const corrected = hook!.load(pathToFileURL(STUDIO_CLI).href, {}, () => ({ format: "module", source: Buffer.from(original) })) as { source: string };
  assert.equal(corrected.source, interop.transformCliSource(original));
  assert.equal(deregistered, 1);
});

test("actual Node preload can load the hash-pinned CLI without modifying vendor bytes", async () => {
  const guard = path.join(process.cwd(), "src/app/api/producer/studio/review-only.cjs");
  const version = await runStudioCommand(process.execPath, ["--require", guard, STUDIO_CLI, "--version"]);
  assert.match(version, /0\.7\.33/u);
  assert.equal(fs.readFileSync(STUDIO_CLI, "utf8"), original);
});
