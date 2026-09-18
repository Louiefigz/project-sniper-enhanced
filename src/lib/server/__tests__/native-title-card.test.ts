/** Real canonical-library selection and native title/caption contract boundaries. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { loadDirectorCatalog } from "../native-director-library";
import { assertHookLineBreaks, createUserTitleCopy, fillLocalHookTemplate, type LocalHookCopy, type UserTitleCopy } from "../native-hook-template";
import { NATIVE_TITLE_PALETTES, renderNativeTitleCard, titleContrast, type NativeTitleCard } from "../native-title-card";
import { buildNativeCanvas, centeredNativeCaptionView, type NativeCanvasInput } from "../native-short-composition";

const catalog = loadDirectorCatalog();
function card(): NativeTitleCard & { copy: LocalHookCopy } {
  return { copy: fillLocalHookTemplate(catalog, { anchor: "steps-toward-goal", slots: { count: "Two", goal: "a follow-up that earns trust" } }),
    lines: ["Two steps to a follow-up", "that earns trust"], palette: "white-on-slate", endFrame: 80, top: 110, fontSize: 76 };
}

test("local slot filling reads the real Director formula, retaining source identity without inference", () => {
  const copy = card().copy;
  assert.equal(copy.text, "Two steps to a follow-up that earns trust");
  assert.match(copy.template, /\[goal\]/u);
  assert.match(copy.libraryHash, /^[a-f0-9]{64}$/u);
  assert.equal(copy.scope, "local-template-fill-not-editorial-approval");
  assert.equal(fillLocalHookTemplate(catalog, { anchor: "steps-toward-goal",
    slots: { count: "Three", goal: "a clearer quote", timeframe: "one afternoon" } }).text,
  "Three steps to a clearer quote (in one afternoon)");
  assert.throws(() => fillLocalHookTemplate(catalog, { anchor: "missing", slots: {} }), /Unknown/);
  assert.throws(() => fillLocalHookTemplate(catalog, { anchor: "situation-if-you", slots: { situation: "invoice late" } }), /Missing/);
  assert.throws(() => fillLocalHookTemplate(catalog, { anchor: "steps-toward-goal", slots: { goal: "trust" } }), /Missing/);
  assert.throws(() => fillLocalHookTemplate(catalog, { anchor: "steps-toward-goal", slots: { result: "trust" } }), /Unknown/);
});

test("explicit user title preserves exact wording and truthful provenance with shared wrapping", () => {
  const text = "POV: You commented SKILL for an Ai video editor", copy = createUserTitleCopy(text);
  assert.deepEqual(copy, { text, scope: "user-supplied-title" });
  const lines = ["POV: You commented", "SKILL for an", "Ai video editor"];
  assertHookLineBreaks(copy, lines);
  assert.throws(() => assertHookLineBreaks(copy, [text.replace("Ai", "AI")]), /preserve/);
  assert.equal(createUserTitleCopy(`  ${text}  `).text, `  ${text}  `);
  const html = renderNativeTitleCard({ ...card(), copy, lines }, { frameRate: "25/1", totalFrames: 100 });
  assert.match(html, /data-title-scope="user-supplied-title"/u);
  assert.doesNotMatch(html, /data-hook-anchor|data-library-hash/u);
});

test("user title escaping does not grant HTML or canonical-template authority", () => {
  const text = `<img src=x onerror="alert(1)"> & 'ok'`, copy = createUserTitleCopy(text);
  const value = { ...card(), copy, lines: [text] }, clock = { frameRate: "25/1", totalFrames: 100 };
  const html = renderNativeTitleCard(value, clock);
  assert.match(html, /&lt;img src=x onerror=&quot;alert\(1\)&quot;&gt; &amp; &#39;ok&#39;/u);
  assert.doesNotMatch(html, /<img/u);
  for (const field of ["anchor", "template", "category", "slots", "libraryHash", "editorialApproved"]) {
    const forged = { ...copy, [field]: "fabricated" } as UserTitleCopy;
    assert.throws(() => renderNativeTitleCard({ ...value, copy: forged }, clock), /authority/);
  }
});

test("user title bounds reject nontext, controls, multiline and overlong copy", () => {
  assert.equal(createUserTitleCopy("a".repeat(120)).text.length, 120);
  const invalid = [null, undefined, 7, "", "   ", "a".repeat(121), "a\nb", "a\rb", "a\tb", "a\0b",
    "a\u0085b", "a\u2028b", "a\u2029b"];
  for (const text of invalid) assert.throws(() => createUserTitleCopy(text as string), /single-line copy/);
});

test("backed title requires copy-preserving line breaks, strong contrast and an upper position", () => {
  const value = card(), clock = { frameRate: "25/1", totalFrames: 100 };
  assertHookLineBreaks(value.copy, value.lines);
  assert.throws(() => assertHookLineBreaks(value.copy, ["A different promise"]), /preserve/);
  for (const palette of Object.keys(NATIVE_TITLE_PALETTES) as NativeTitleCard["palette"][]) {
    assert.ok(titleContrast(palette) >= 11, `${palette} keeps its documented contrast`);
    assert.match(renderNativeTitleCard({ ...value, palette }, clock), /data-duration="3.2"/u);
  }
  assert.throws(() => renderNativeTitleCard({ ...value, top: 950 }, clock), /upper position/);
  assert.throws(() => renderNativeTitleCard({ ...value, endFrame: 101 }, clock), /exact lifetime/);
});

test("native canvas includes the local title and exact word highlighting without moving speech", () => {
  const view = centeredNativeCaptionView({ startFrame: 0, endFrame: 100, top: 1080 });
  const input: NativeCanvasInput = { title: "TEST template component", frameRate: "25/1", totalFrames: 100,
    background: "#111111", sourceFile: `assets/${"a".repeat(64)}.mp4`, sourceSize: { w: 1920, h: 1080 },
    cuts: [{ start: 0, end: 4, speed: 1 }], segments: [{ startFrame: 0, endFrameExclusive: 100 }],
    pictureViews: [{ startFrame: 0, endFrame: 100, crop: [400, 0, 607.5, 1080], box: [0, 0, 1080, 1920] }],
    occurrences: [[0, 0, 0, 0, 20, "Real", 0], [1, 0, 1, 20, 40, "words", 0]], captionGroups: [[0, 1]],
    captionViews: [view], titleCard: card(), text: [], shapes: [], motion: [] };
  const html = buildNativeCanvas(input);
  assert.match(html, /data-hook-anchor="steps-toward-goal"/u);
  assert.match(html, /left:90px;top:1080px;width:900px/u);
  assert.match(html, /data-word-start-frame="20" data-word-end-frame="40"/u);
  assert.ok(html.includes('tl.set("#word-1-0",{color:"#ffffff"},1.6)'));
  input.text.push({ id: "old-hook", startFrame: 0, endFrame: 80, box: [80, 950, 920, 200],
    text: "Old hook", role: "hook", style: view.style });
  assert.throws(() => buildNativeCanvas(input), /do not stack both/u);
});
