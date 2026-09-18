/** Authoring behavior only. Native layout and actual caption overlap are not qualified here. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { runPipelineScript } from "./_pipeline_dom_fixture.mjs";

const source = readFileSync(new URL("../../../templates/motion/nateherk-pipeline.js", import.meta.url), "utf8");
const copy = { eyebrow: "This stage", headlineLines: "At this stage your content system|is a folder",
  explainer: "Ideas go in and nothing ever comes back", footChip: "nothing comes back",
  nodes: "Ideas~go in|nothing~ever|comes~back", activeIndex: 2, exit: "hold", presenterFrame: false };

function withoutNativeLinks(value) {
  if (Array.isArray(value)) return value.filter((row) => row.className !== "npl-native-link").map(withoutNativeLinks);
  if (value?.className === "npl-native-cell") return withoutNativeLinks(value.children[0]);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, row]) => [key, withoutNativeLinks(row)]));
  return value;
}

test("native upper layout preserves every original authored character, node order and animation call", () => {
  const before = structuredClone(copy);
  const legacy = runPipelineScript(source, copy), upper = runPipelineScript(source, { ...copy, layout: "caption-safe-upper-v1" });
  assert.deepEqual(withoutNativeLinks(upper.snapshot), legacy.snapshot);
  assert.deepEqual(upper.snapshot["npl-chain"].children.map((cell) => cell.children.filter((child) => child.className === "npl-native-link").length), [1, 1, 0]);
  assert.ok(upper.snapshot["npl-chain"].children.every((cell) => cell.className === "npl-native-cell" && cell.children[0].className.startsWith("npl-node")));
  assert.deepEqual(upper.trace.filter((row) => row[1]?.startsWith?.("npl-native-cell:")).map((row) => row[1]),
    ["npl-native-cell:Ideasgo in", "npl-native-cell:nothingever", "npl-native-cell:comesback"]);
  assert.deepEqual(upper.trace.map((row, index) => row[1]?.startsWith?.("npl-native-cell:")
    ? [row[0], legacy.trace[index][1], ...row.slice(2)] : row), legacy.trace);
  assert.deepEqual(copy, before);
  assert.equal(upper.layout, "caption-safe-upper-v1");
  assert.deepEqual(upper.roles.map((role) => role.id).sort(), ["eyebrow", "explainer", "footnote", "headline-line-1",
    "headline-line-2", "node-1", "node-2", "node-3", "connector-1", "connector-2"].sort());
});

test("the default retains original headline, node stagger, footnote landing and hold timeline", () => {
  const result = runPipelineScript(source, copy);
  assert.equal(result.layout, "full-canvas");
  const ramps = result.trace.filter((row) => row[0] === "textRamp");
  assert.deepEqual(ramps.map((row) => row[1]), ["npl-eyebrow", "line:At this stage your content system",
    "line l2:is a folder", "npl-explainer", "npl-chain", "npl-node:Ideasgo in",
    "npl-node active:nothingever", "npl-node:comesback", "npl-foot"]);
  const times = [0.2, 0.45, 0.57, 0.69, 1.1, 1.1, 1.25, 1.4, 2];
  ramps.forEach((row, index) => assert.ok(Math.abs(row[2] - times[index]) < 1e-10));
  assert.deepEqual(result.trace.at(-1), ["seek", 0]);
});

test("default eight-node presenter and blur exit stay available while new layout rejects that class", () => {
  const input = { ...copy, nodes: Array.from({ length: 8 }, (_, index) => `${index}~label`).join("|"),
    presenterFrame: true, exit: "blur-recede" };
  const result = runPipelineScript(source, input);
  assert.equal(result.snapshot["npl-root"].className, "has-presenter");
  assert.ok(result.trace.some((row) => row[0] === "blurRecede" && row[2] === 8.85));
  assert.throws(() => runPipelineScript(source, { ...input, layout: "caption-safe-upper-v1" }), /upper layout requires/);
});

test("empty modules prune without inventing copy, while all-empty preview keeps its historical sample", () => {
  const result = runPipelineScript(source, { nodes: "1~one|2~two" });
  for (const name of ["eyebrow", "headline", "explainer", "foot"]) assert.equal(result.snapshot["npl-" + name].removed, true);
  const preview = runPipelineScript(source, {});
  assert.equal(preview.snapshot["npl-chain"].children.length, 6);
  assert.equal(preview.snapshot["npl-headline"].children[0].ownText, "The chain changed.");
});

test("explicit narration lands preserve original module order and reject malformed schedules", () => {
  const result = runPipelineScript(source, { ...copy, moduleLands: "1|3|5" });
  assert.equal(result.trace.find((row) => row[1] === "npl-chain")[2], 3);
  assert.equal(result.trace.find((row) => row[1] === "npl-foot")[2], 5);
  assert.throws(() => runPipelineScript(source, { ...copy, moduleLands: "1|3" }), /moduleLands needs/);
  assert.throws(() => runPipelineScript(source, { ...copy, moduleLands: "1|NaN|5" }), /finite times/);
});

test("unknown layout, too many nodes, invalid identity and incomplete node content reject", () => {
  const cases = [{ layout: "auto-fit" }, { nodes: "one" }, { activeIndex: 9 },
    { headlineLines: "a|b|c" }, { footAccent: "mystery" }, { nodes: "a~b|c~" }];
  for (const change of cases) assert.throws(() => runPipelineScript(source, { ...copy, ...change }));
  const seven = Array.from({ length: 7 }, (_, index) => `${index}~label`).join("|");
  assert.throws(() => runPipelineScript(source, { ...copy, nodes: seven, layout: "caption-safe-upper-v1" }), /upper layout requires/);
});

test("full-width teaching retains all copy, ordering and animation with a wider readable presentation", () => {
  for (const count of [2, 3, 6]) {
    const input = { ...copy, nodes: Array.from({length: count}, (_, i) => `${i + 1}~Node ${i + 1}`).join("|") };
    const legacy = runPipelineScript(source, input);
    const teaching = runPipelineScript(source, {...input, layout: "teaching-full-width-v1"});
    assert.deepEqual(teaching.snapshot, legacy.snapshot);
    assert.deepEqual(teaching.trace, legacy.trace);
    assert.equal(teaching.layout, "teaching-full-width-v1");
  }
  const fading = runPipelineScript(source, {...copy, layout: "teaching-full-width-v1", exit: "blur-recede"});
  assert.ok(fading.trace.some(row => row[0] === "blurRecede" && row[2] === 8.85));
});

test("full-width teaching rejects presenter holes, unsupported exits and oversized node sets", () => {
  for (const change of [{presenterFrame: true}, {presenterFrame: 0}, {exit: "guess"},
    {nodes: "1~Only one"}, {nodes: Array.from({length: 7}, (_, i) => `${i + 1}~Node`).join("|")}]) {
    assert.throws(() => runPipelineScript(source, {...copy, layout: "teaching-full-width-v1", ...change}),
      /teaching layout requires/);
  }
});
