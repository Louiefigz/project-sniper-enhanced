/** Real HTML/script sequence in a TEST DOM; no browser, render or native proof. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { test } from "node:test";
import { runPipelineScript } from "./_pipeline_dom_fixture.mjs";

const html = readFileSync(new URL("../../../templates/motion/compositions/module-pipeline.html", import.meta.url), "utf8");
const source = readFileSync(new URL("../../../templates/motion/module-pipeline.js", import.meta.url), "utf8");
const external = '<script src="/module-pipeline.js"></script>';

function scripts() {
  const offset = html.indexOf(external);
  assert.equal(offset, html.lastIndexOf(external));
  const before = [...html.slice(0, offset).matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)?.[1];
  const after = [...html.slice(offset + external.length).matchAll(/<script>([\s\S]*?)<\/script>/g)][0]?.[1];
  assert.ok(before?.includes("window.__timelines"), "real registry bootstrap must precede external script");
  assert.ok(after?.includes("module-pipeline"), "actual registration assertion must follow external script");
  return { before, after };
}

test("pipeline HTML bootstraps and verifies its actual external paused timeline", () => {
  const { before, after } = scripts();
  const vars = { nodes: "01~FIRST|02~SECOND", headlineLines: "TEST sequence" };
  const actual = runPipelineScript(before + source + after, vars);
  const original = runPipelineScript(source, vars);
  assert.deepEqual(actual, original);
  assert.deepEqual(actual.trace.at(-1), ["seek", 0]);
});

test("bootstrap preserves an existing sibling timeline registry", () => {
  const { before } = scripts();
  const registry = { sibling: {} }, window = { __timelines: registry };
  runInNewContext(before, { window });
  assert.equal(window.__timelines, registry);
  assert.deepEqual(Object.keys(registry), ["sibling"]);
});

test("postscript refuses missing registration and malformed or playing timelines", () => {
  const { before, after } = scripts();
  const invalid = [undefined, {}, { seek() {}, paused: () => false }, { seek() {} }];
  for (const value of invalid) {
    const window = {};
    runInNewContext(before, { window });
    window.__timelines["module-pipeline"] = value;
    assert.throws(() => runInNewContext(after, { window }), /paused timeline was not registered/);
  }
});

test("native upper layout keeps original copy and timeline after the HTML sequence", () => {
  const { before, after } = scripts();
  const vars = { layout: "caption-safe-upper-v1", nodes: "01~FIRST|02~SECOND",
    headlineLines: "TEST sequence", footChip: "TEST only", moduleLands: "0.2|1.1|2" };
  assert.deepEqual(runPipelineScript(before + source + after, vars), runPipelineScript(source, vars));
});
