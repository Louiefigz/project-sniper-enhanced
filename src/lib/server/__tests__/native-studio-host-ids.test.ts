/** TEST-only markup: which elements pinned Studio would stamp, and the byte-preserving stamp. */
import assert from "node:assert/strict";
import { mkdtempSync, realpathSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { missingStudioHostIds, assertStudioHostIds } from "../native-studio-host-ids";
import { stampStudioHostIds } from "../native-studio-host-stamp";
import { writeNativeShortProject } from "../native-short-project";
import { nativeShortFixture, refreshNativePacingFixture } from "./_native-short-project-fixture";

const COMPOSITION = `<!doctype html>
<html lang="en" data-composition-id="card" data-composition-variables='[{"id":"label","type":"string","default":"It&#39;s"}]'>
<head><meta charset="UTF-8"><title>TEST card</title></head>
<body><template>
<style>#card .label{color:#fff}</style>
<div id="card" data-composition-id="card" data-width="1080" data-height="1920"><p class="label">It's</p><svg><path d="M0 0"/></svg></div>
<script>window.__timelines = window.__timelines || {};</script>
</template><template id="unused"><div class="ignored">x</div></template><noscript><span>no</span></noscript></body></html>`;

test("the walk names every element Studio stamps and skips excluded tags and plain templates", () => {
  assert.deepEqual(missingStudioHostIds(COMPOSITION), ["div#card", "p.label", "svg", "path", "span"]);
  assert.deepEqual(missingStudioHostIds('<div id="a" class="clip"></div><script>x</script>'), ["div#a"]);
  assert.deepEqual(missingStudioHostIds('<div id="a" data-hf-id="hf-a"><img data-hf-id="hf-b"></div>'), []);
  assert.deepEqual(missingStudioHostIds('<div id="a" data-hf-id=""></div>'), ["div#a"]);
});

test("stamping only inserts ids, keeps every other byte, is idempotent and satisfies the walk", () => {
  const stamped = stampStudioHostIds(COMPOSITION);
  assert.equal(stamped.replace(/ data-hf-id="[^"]*"/gu, ""), COMPOSITION);
  assert.deepEqual(missingStudioHostIds(stamped), []);
  assert.equal(stampStudioHostIds(stamped), stamped);
  assert.match(stamped, /<div data-hf-id="hf-card" id="card"/u);
  assert.match(stamped, /data-composition-variables='\[\{"id":"label","type":"string","default":"It&#39;s"\}\]'/u);
  const ids = [...stamped.matchAll(/data-hf-id="([^"]+)"/gu)].map((match) => match[1]);
  assert.equal(new Set(ids).size, ids.length);
});

test("stamping keeps existing ids and never mints a duplicate", () => {
  const source = '<div id="x" data-hf-id="hf-x"></div><div id="x2"></div><p data-hf-id="hf-p-1"></p><p></p>';
  const stamped = stampStudioHostIds(source);
  const ids = [...stamped.matchAll(/data-hf-id="([^"]+)"/gu)].map((match) => match[1]);
  assert.deepEqual(ids, ["hf-x", "hf-x2", "hf-p-1", "hf-p-1-1"]);
});

test("only the index and mounted compositions are checked", () => {
  assert.doesNotThrow(() => assertStudioHostIds({ "BRIEF.md": "<div>not html</div>", "index.html": "<div data-hf-id=\"hf-a\"></div>" }));
  assert.throws(() => assertStudioHostIds({ "compositions/card.html": COMPOSITION }),
    /Studio would rewrite this project .*compositions\/card\.html div#card, .*svg, .*path, .*span/u);
});

test("a new native build refuses authored markup Studio would rewrite and names the element", () => {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-studio-ids-")));
  try {
    const input = nativeShortFixture(directory);
    input.extension = { markup: '<div id="annotation" class="clip" data-start="0" data-duration="2">TEST annotation</div>', css: "", motion: "" };
    refreshNativePacingFixture(input);
    assert.throws(() => writeNativeShortProject(input, path.join(directory, "unstamped")), /index\.html div#annotation/u);
    input.extension.markup = stampStudioHostIds(input.extension.markup);
    refreshNativePacingFixture(input);
    assert.ok(writeNativeShortProject(input, path.join(directory, "stamped")).manifest);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
