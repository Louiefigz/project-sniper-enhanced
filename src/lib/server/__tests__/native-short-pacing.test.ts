/** Timing and revision tests; synthetic fixtures do not establish audience comprehension. */
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { nativeShortFixture, refreshNativePacingFixture } from "./_native-short-project-fixture";
import { assembleNativeShortHtml, readNativeShortProject, writeNativeShortProject, type NativeShortProjectInput } from "../native-short-project";
import { measureNativeShortPacing, nativePacingBindings } from "../native-short-pacing-observations";
import { nativeShortPacingReport } from "../native-short-pacing";
import { fileSha256 } from "../auto-edit-hash";

function withFixture(run: (input: NativeShortProjectInput, directory: string) => void): void {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-pacing-")));
  try { run(nativeShortFixture(directory), directory); }
  finally { rmSync(directory, { recursive: true, force: true }); }
}

test("overlapping word windows are unioned and phrase timing matches the rendered clamp", () => withFixture(input => {
  input.canvas.occurrences[0][4] = 30;
  const report = measureNativeShortPacing(input.canvas);
  assert.equal(report.speechCoverageFrames, 45);
  assert.deepEqual(report.gaps, [{ startFrame: 45, endFrame: 50 }]);
  assert.equal(report.phrases[0].endFrame, 20);
  assert.equal(report.phrases[0].durationSeconds, .8);
  assert.equal(report.wordCount, 2);
  assert.equal(report.wordsPerMinute, 60);
}));

test("identical overall speaking rates retain different pause structure without classifying energy", () => withFixture(input => {
  const continuous = measureNativeShortPacing(input.canvas);
  input.canvas.occurrences[0][4] = 5;
  input.canvas.occurrences[1][3] = 40;
  const paused = measureNativeShortPacing(input.canvas);
  assert.equal(paused.wordsPerMinute, continuous.wordsPerMinute);
  assert.equal(paused.speechCoverageFrames, 10);
  assert.equal(continuous.speechCoverageFrames, 45);
  assert.deepEqual(paused.gaps[0], { startFrame: 5, endFrame: 40 });
  assert.equal("overallRhythm" in paused, false);
  input.canvas.frameRate = "30000/1001";
  assert.ok(Math.abs(measureNativeShortPacing(input.canvas).durationSeconds - 1.6683333333) < .000001);
}));

test("speech, phrase, asset and composition revisions invalidate prior pacing", () => withFixture(input => {
  const edits: Array<(plan: NativeShortProjectInput) => void> = [
    plan => { plan.canvas.occurrences[0][5] = "Changed"; },
    plan => { plan.canvas.cuts[0].start = .02; },
    plan => { plan.canvas.captionGroups = [[0, 1]]; },
    plan => { plan.canvas.pictureViews[0].crop[0] = 510; },
    plan => { plan.assets[0].sha256 = "a".repeat(64); },
    plan => { plan.extension = { markup: "", css: "<style>.caption{opacity:0}</style>", motion: "" }; },
  ];
  for (const edit of edits) {
    const changed = structuredClone(input); edit(changed);
    assert.throws(() => assembleNativeShortHtml(changed), /Pacing plan is stale/);
  }
}));

test("new builds require pacing before touching the destination; legacy HTML remains reconstructable", () => withFixture((input, directory) => {
  const html = assembleNativeShortHtml(input);
  input.strategy.schemaVersion = 1; delete input.strategy.pacing; delete input.strategy.assetUse;
  assert.equal(assembleNativeShortHtml(input), html);
  const destination = path.join(directory, "blocked");
  assert.throws(() => writeNativeShortProject(input, destination), /version 3/);
  assert.equal(existsSync(destination), false);
  input.strategy.schemaVersion = 2;
  assert.throws(() => assembleNativeShortHtml(input), /require a script-bound pacing plan/);
}));

test("declared hold cannot exceed target visibility or consume the motion interval", () => withFixture(input => {
  const hold = input.strategy.pacing!.holds[0];
  hold.minimumFrames = 26;
  assert.throws(() => assembleNativeShortHtml(input), /exceeds its executable hold/);
  hold.minimumFrames = 5; hold.endFrame = 26;
  assert.throws(() => assembleNativeShortHtml(input), /exceeds its executable hold/);
  input.canvas.text.push({ id: "result", text: "Result", role: "explanation", startFrame: 0, endFrame: 50,
    box: [100, 500, 500, 100], style: input.canvas.captionViews[0].style });
  input.canvas.motion.push({ id: "result", startFrame: 0, durationFrames: 10,
    from: { y: 0, scale: 1, opacity: 0 }, to: { y: 0, scale: 1, opacity: 1 }, ease: "power2.out" });
  refreshNativePacingFixture(input);
  input.strategy.pacing!.holds.find(row => row.targetId === "result")!.startFrame = 5;
  assert.throws(() => assembleNativeShortHtml(input), /overlaps its known motion/);
}));

test("silent beats, missing words and uncovered runtime require explicit corrections", () => withFixture(input => {
  const pacing = input.strategy.pacing!, beat = pacing.beats[0];
  beat.endFrame = 45;
  assert.throws(() => assembleNativeShortHtml(input), /omits part/);
  pacing.beats.push({ ...beat, startFrame: 45, endFrame: 50, occurrenceIds: [], rhythm: "measured" });
  assert.throws(() => assembleNativeShortHtml(input), /explicit pause/);
  pacing.beats[1].rhythm = "pause";
  assert.doesNotThrow(() => assembleNativeShortHtml(input));
  pacing.overallRhythm = "brisk";
  assert.throws(() => assembleNativeShortHtml(input), /overall rhythm contradicts/);
  pacing.overallRhythm = "varied";
  assert.doesNotThrow(() => assembleNativeShortHtml(input));
  beat.occurrenceIds = [0];
  assert.throws(() => assembleNativeShortHtml(input), /lost its actual retained speech/);
}));

test("custom inserts need viewing budgets and retain the limits of static timing checks", () => withFixture(input => {
  input.extension = { markup: '<div id="screen" class="clip" data-start="0" data-duration="2">TEST screen</div>',
    css: "", motion: "tl.set('#screen',{opacity:0},1);" };
  refreshNativePacingFixture(input);
  const html = assembleNativeShortHtml(input), report = nativeShortPacingReport(input, html);
  assert.equal(report.audienceComprehension, "not-established");
  assert.ok(report.reviewRequired.some(row => row.includes("Custom CSS/GSAP")));
  input.strategy.pacing!.holds = input.strategy.pacing!.holds.filter(row => row.targetId !== "screen");
  assert.throws(() => assembleNativeShortHtml(input), /no viewing budget for screen/);
}));

test("writer and cold reader reproduce the report and reject rehashed fabricated observations", () => withFixture((input, directory) => {
  const project = writeNativeShortProject(input, path.join(directory, "project"));
  assert.deepEqual(readNativeShortProject(project.directory), input);
  const file = path.join(project.directory, "PACING-REPORT.json");
  const report = JSON.parse(readFileSync(file, "utf8"));
  report.observations.wordsPerMinute = 999;
  writeFileSync(file, JSON.stringify(report));
  const manifestFile = path.join(project.directory, "PROJECT-MANIFEST.json");
  const manifest = JSON.parse(readFileSync(manifestFile, "utf8"));
  manifest.files.find((row: { file: string }) => row.file === "PACING-REPORT.json").sha256 = fileSha256(file);
  writeFileSync(manifestFile, JSON.stringify(manifest));
  assert.throws(() => readNativeShortProject(project.directory), /pacing report differs/);
}));

test("caption display revisions stale visuals while retaining speech clocks and legacy reports", () => withFixture(input => {
  const bindings = nativePacingBindings(input), before = measureNativeShortPacing(input.canvas);
  input.canvas.captionCorrections = [];
  assert.deepEqual(nativePacingBindings(input), bindings);
  assert.deepEqual(measureNativeShortPacing(input.canvas), before);
  const sourceText = input.canvas.occurrences[0][5];
  input.canvas.captionCorrections = [{ occurrenceId: 0, expectedSourceText: sourceText,
    displayText: "level is", reason: "TEST confirmed display wording" }];
  const after = nativePacingBindings(input), report = measureNativeShortPacing(input.canvas);
  assert.equal(after.timingHash, bindings.timingHash);
  assert.notEqual(after.visualHash, bindings.visualHash);
  assert.throws(() => assembleNativeShortHtml(input), /Pacing plan is stale/);
  assert.equal(report.phrases[0].text, "level is");
  assert.equal(report.phrases[0].sourceText, sourceText);
  assert.equal(report.phrases[0].displayWordCount, 2);
  assert.equal(report.wordCount, before.wordCount);
  assert.equal(report.wordsPerMinute, before.wordsPerMinute);
  assert.equal(report.phrases[0].endFrame, before.phrases[0].endFrame);
}));

test("corrected captions survive real writer/cold reader without mutating accepted source speech", () => withFixture((input, directory) => {
  const source = structuredClone(input.canvas.occurrences);
  input.canvas.captionCorrections = [{ occurrenceId: 0, expectedSourceText: source[0][5],
    displayText: "level is", reason: "TEST operator confirmed this phrase" }];
  refreshNativePacingFixture(input);
  const project = writeNativeShortProject(input, path.join(directory, "corrected"));
  const read = readNativeShortProject(project.directory);
  assert.deepEqual(read.canvas.occurrences, source);
  assert.deepEqual(read.canvas.captionCorrections, input.canvas.captionCorrections);
  assert.match(assembleNativeShortHtml(read), />level is<\/span>/u);
  input.canvas.captionCorrections[0].expectedSourceText = "changed";
  assert.throws(() => assembleNativeShortHtml(input), /stale.*source occurrence/);
}));

test("source-burned captions bind visual ownership and cold-read without claiming pixel timing", () => withFixture((input, directory) => {
  const before = nativePacingBindings(input), measured = measureNativeShortPacing(input.canvas);
  input.canvas.captionMode = "native";
  assert.deepEqual(nativePacingBindings(input), before);
  assert.deepEqual(measureNativeShortPacing(input.canvas), measured);
  input.canvas.captionMode = "source-burned";
  assert.throws(() => nativePacingBindings(input), /cannot add native caption views/);
  input.canvas.captionViews = [];
  const after = nativePacingBindings(input), observed = measureNativeShortPacing(input.canvas);
  assert.equal(after.timingHash, before.timingHash);
  assert.notEqual(after.visualHash, before.visualHash);
  assert.equal(observed.captionTimingScope, "transcript-groups-only-burned-caption-timing-unmeasured");
  assert.deepEqual(observed.phrases, measured.phrases);
  assert.throws(() => assembleNativeShortHtml(input), /Pacing plan is stale/);
  input.extension = { markup: '<div id="annotation" class="clip" data-start="0" data-duration="2">TEST annotation</div>', css: "", motion: "" };
  refreshNativePacingFixture(input);
  const project = writeNativeShortProject(input, path.join(directory, "source-burned"));
  assert.deepEqual(readNativeShortProject(project.directory), input);
  assert.match(assembleNativeShortHtml(input), /id="annotation"/u);
  assert.doesNotMatch(assembleNativeShortHtml(input), /id="(?:caption-|word-)/u);
  const report = JSON.parse(readFileSync(path.join(project.directory, "PACING-REPORT.json"), "utf8"));
  assert.ok(report.reviewRequired.some((row: string) => row.includes("actual pixels")));
  input.canvas.captionCorrections = [{ occurrenceId: 0, expectedSourceText: "Test", displayText: "Changed", reason: "TEST ignored" }];
  assert.throws(() => nativePacingBindings(input), /cannot apply native caption corrections/);
  assert.throws(() => measureNativeShortPacing(input.canvas), /cannot apply native caption corrections/);
}));
