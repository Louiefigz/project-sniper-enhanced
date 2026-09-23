import assert from "node:assert/strict";
import { mkdtempSync, realpathSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { assembleNativeShortHtml } from "../native-short-project";
import { mapPreparedMedia, preparedProjectMedia, selectedSourceRequest, type PreparedSourceResult } from "../native-selected-sources";
import { nativeShortFixture, refreshNativePacingFixture } from "./_native-short-project-fixture";
import { createUserTitleCopy } from "../native-hook-template";

function fixture() {
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "selected-sources-"))), input = nativeShortFixture(root);
  const source = input.assets.find(row => row.file === input.canvas.sourceFile)!;
  input.preparedSources = { path: path.join(root, "TEST-package.json"), sha256: "e".repeat(64) };
  const asset = (kind: string) => ({ file: `assets/${kind}.${kind === "picture" ? "mp4" : "wav"}`, path: path.join(root, kind),
    sha256: "b".repeat(64), bytes: 100, sourceOrigin: "0", sourceStart: "0", sourceEnd: "100" });
  const result: PreparedSourceResult = { schemaVersion: 1, selection: { sources: [source] },
    sections: [{ sourceFile: source.file, video: asset("picture"), audio: asset("dialogue") }] };
  return { input, result, cleanup: () => rmSync(root, { recursive: true, force: true }) };
}

test("small staged files replace every executable media URL while source and caption clocks stay unchanged", () => {
  const f = fixture();
  try {
    const before = JSON.stringify(f.input), html = assembleNativeShortHtml(f.input);
    const media = preparedProjectMedia(f.input, html, f.result);
    assert.equal(JSON.stringify(f.input), before);
    assert.ok(media.report!.mappings.some(row => row.kind === "audio"));
    assert.ok(media.report!.mappings.some(row => row.kind === "video"));
    assert.ok(!media.assets.some(row => row.file === f.input.canvas.sourceFile));
    assert.ok(media.assets.some(row => row.file === "assets/picture.mp4"));
    assert.ok(!media.html.includes(`src="${f.input.canvas.sourceFile}"`));
    assert.equal(media.html.replaceAll("assets/picture.mp4", f.input.canvas.sourceFile)
      .replaceAll("assets/dialogue.wav", f.input.canvas.sourceFile), html);
  } finally { f.cleanup(); }
});

test("duplicate views reuse one video file and a title-only revision keeps the package", () => {
  const f = fixture();
  try {
    const html = assembleNativeShortHtml(f.input), first = preparedProjectMedia(f.input, html, f.result);
    f.input.canvas.titleCard!.copy = createUserTitleCopy("A different title");
    f.input.canvas.titleCard!.lines = ["A different title"];
    refreshNativePacingFixture(f.input);
    const next = preparedProjectMedia(f.input, assembleNativeShortHtml(f.input), f.result);
    assert.notEqual(first.html, next.html);
    assert.deepEqual(first.assets, next.assets);
    assert.deepEqual(first.report, next.report);
    assert.equal(first.assets.filter(row => row.file === "assets/picture.mp4").length, 1);
  } finally { f.cleanup(); }
});

test("source offsets use the measured rational origin and retain editorial IDs", () => {
  const f = fixture();
  try {
    f.result.sections[0].video.sourceOrigin = "299/3";
    f.result.sections[0].video.sourceStart = "299/3";
    f.result.sections[0].video.sourceEnd = "110";
    const mapping = mapPreparedMedia({ id: "source-2-0", kind: "video", sourceFile: f.input.canvas.sourceFile, start: 101, end: 105 }, f.result);
    assert.equal(mapping.mediaStart, 1.333333333333);
    assert.equal(mapping.id, "source-2-0");
  } finally { f.cleanup(); }
});

test("uncovered range, missing audio, substituted original and playback aliases fail closed", () => {
  const f = fixture();
  try {
    const html = assembleNativeShortHtml(f.input);
    f.result.sections[0].video.sourceEnd = "0";
    assert.throws(() => preparedProjectMedia(f.input, html, f.result), /do not cover/);
    f.result.sections[0].video.sourceEnd = "100";
    f.result.sections[0].audio = null;
    assert.throws(() => preparedProjectMedia(f.input, html, f.result), /do not cover/);
    f.result.selection.sources[0] = { ...f.result.selection.sources[0], path: "/wrong-original.mp4" };
    assert.throws(() => preparedProjectMedia(f.input, html, f.result), /substituted/);
    assert.throws(() => selectedSourceRequest(f.input, html.replace("<video ", '<video data-playback-rate="2" ')), /speed-one/);
  } finally { f.cleanup(); }
});

test("range preparation deduplicates audio/video uses and contains only used originals", () => {
  const f = fixture();
  try {
    const request = selectedSourceRequest(f.input, assembleNativeShortHtml(f.input));
    assert.equal(request.sources.length, 1);
    assert.equal(new Set(request.ranges.map(row => JSON.stringify(row))).size, request.ranges.length);
    assert.equal(request.handleSeconds, 1);
  } finally { f.cleanup(); }
});
