/** Synthetic structural tests: no fixture proves visual storytelling or source truth. */
import assert from "node:assert/strict";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileSha256 } from "../auto-edit-hash";
import { nativePacingBindings } from "../native-short-pacing-observations";
import { assembleNativeShortHtml, readNativeShortProject, writeNativeShortProject } from "../native-short-project";
import { assertNativeShortStory, nativeShortStoryReport, nativeStoryRevisionHash, type NativeStoryVisualJob } from "../native-short-story";
import { executeNativeShortCommand } from "../../../../scripts/producer/native-short";
import { assetUseFixture, withAssetUse, type AssetUseFixture } from "./_native-short-asset-use-fixture";

function author(f: AssetUseFixture, kind: NativeStoryVisualJob["kind"] = "presenter-performance"): void {
  const input = f.input, pacing = input.strategy.pacing!;
  let targetId = "source-0-0", decisionId: string | null = "test-use";
  if (["real-artifact", "real-operation"].includes(kind)) {
    f.addMedia(kind === "real-operation" ? "video" : "image"); targetId = "test-insert";
    input.strategy.assetUse!.decisions[0].purpose = kind === "real-operation" ? "demonstrate" : "illustrate";
  }
  if (kind === "explanatory-comparison") {
    targetId = "comparison"; decisionId = null;
    input.canvas.shapes = [{ id: targetId, startFrame: 0, endFrame: 50, box: [50, 600, 900, 300],
      fill: "#ffffff", border: "#111111", borderWidth: 1, radius: 0 }];
    input.strategy.scenes[0].format = "comparison";
  }
  input.strategy.scenes[0].visibleIds = [...new Set(["source-0-0", targetId])];
  const old = pacing.beats[0];
  pacing.beats = [{ ...old, startFrame: 0, endFrame: 20, occurrenceIds: [0] },
    { ...old, startFrame: 20, endFrame: 50, occurrenceIds: [1] }];
  input.strategy.story = { schemaVersion: 1, revisionHash: "", viewerQuestion: "TEST why follow this explanation?",
    payoff: input.strategy.payoff, continuity: { id: "test-subject", subject: "TEST same supplied explanation" },
    beats: pacing.beats.map((beat, index) => {
      const holdIndex = kind === "presenter-performance" ? null : pacing.holds.length;
      if (holdIndex !== null) pacing.holds.push({ targetId, startFrame: beat.startFrame, endFrame: beat.endFrame,
        minimumFrames: 5, reason: "TEST authored budget, not comprehension evidence" });
      return { pacingBeatIndex: index, sceneIndex: 0, phase: index === 0 ? "setup" : "payoff", continuityId: "test-subject",
        visualJobs: [{ kind, targetId, assetDecisionId: decisionId, holdIndex,
          ...(kind === "real-operation" ? { operation: { actionFrame: beat.startFrame + 1, resultFrame: beat.startFrame + 8,
            actionObserved: "TEST synthetic action annotation", resultObserved: "TEST synthetic result annotation" } } : {}) }] };
    }) };
  Object.assign(pacing, nativePacingBindings(input)); f.refresh();
  input.strategy.story.revisionHash = nativeStoryRevisionHash(input);
}

function rebind(f: AssetUseFixture): void {
  f.input.strategy.story!.revisionHash = nativeStoryRevisionHash(f.input);
}

test("legacy absence remains explicit unplanned in reports and the actual check command", async () => {
  const f = assetUseFixture();
  try {
    const html = assembleNativeShortHtml(f.input);
    assert.equal(nativeShortStoryReport(f.input, html).status, "unplanned");
    const project = writeNativeShortProject(f.input, path.join(f.directory, "legacy")).directory;
    assert.equal(existsSync(path.join(project, "STORY-REPORT.json")), false);
    assert.equal(readNativeShortProject(project).strategy.story, undefined);
    const checked = await executeNativeShortCommand(["check", project]);
    assert.equal("story" in checked && checked.story, "unplanned");
    author(f);
    const authored = writeNativeShortProject(f.input, path.join(f.directory, "authored")).directory;
    const storyCheck = await executeNativeShortCommand(["check", authored]);
    assert.equal("story" in storyCheck && storyCheck.story, "authored-obligations-checked-awaiting-whole-story-review");
  } finally { f.cleanup(); }
});

test("presenter beats need no artificial reading hold and reports preserve semantic limits", () => withAssetUse(f => {
  author(f);
  const report = nativeShortStoryReport(f.input, assembleNativeShortHtml(f.input));
  assert.equal(report.status, "authored-obligations-structurally-checked");
  assert.equal(report.narrativeQuality, "not-established-by-structural-checks");
  assert.equal(report.sourceTruth, "not-established-by-structural-checks");
  assert.equal(report.finishedPlaybackReview, "not-performed-by-this-command");
  assert.deepEqual(report.beats.map(beat => beat.speech), ["Test", "words."]);
  assert.ok(report.beats.every(beat => beat.visualJobs[0].holdIndex === null));
}));

test("comparison and real artifact jobs use actual targets and shared admission", () => {
  for (const kind of ["explanatory-comparison", "real-artifact", "real-operation"] as const) withAssetUse(f => {
    author(f, kind);
    assert.doesNotThrow(() => assembleNativeShortHtml(f.input));
    if (kind === "real-artifact") {
      f.input.strategy.assetUse!.decisions[0].selection!.essentialRegion = [2000, 0, 100, 100]; rebind(f);
      assert.throws(() => assembleNativeShortHtml(f.input), /essential region/);
    }
  });
});

test("logos and no-insert decisions cannot satisfy a real artifact obligation", () => withAssetUse(f => {
  author(f, "real-artifact");
  const decision = f.input.strategy.assetUse!.decisions[0], job = f.input.strategy.story!.beats[0].visualJobs[0];
  decision.selection!.kind = "logo"; decision.entity = { name: "TEST entity", role: "subject", canonicalIdentity: "TEST brand" }; rebind(f);
  assert.throws(() => assembleNativeShortHtml(f.input), /logo or no-insert/);
  decision.selection = null; decision.decision = "no-insert"; rebind(f);
  assert.throws(() => assertNativeShortStory(f.input, f.html()), /logo or no-insert/);
  job.assetDecisionId = null;
  assert.throws(() => assertNativeShortStory(f.input, f.html()), /logo or no-insert/);
}));

test("missing decision and substituted speech windows are rejected", () => withAssetUse(f => {
  author(f, "real-artifact");
  const job = f.input.strategy.story!.beats[0].visualJobs[0];
  job.assetDecisionId = "missing-decision";
  assert.throws(() => assembleNativeShortHtml(f.input), /missing asset-use decision/);
  job.assetDecisionId = "test-use";
  f.input.strategy.assetUse!.decisions[0].speech = { startFrame: 20, endFrame: 50, occurrenceIds: [1], text: "words." }; rebind(f);
  assert.throws(() => assembleNativeShortHtml(f.input), /retained speech interval/);
}));

test("scene, speech, pacing beat, hold and decision revisions require story reauthoring", () => withAssetUse(f => {
  author(f, "real-artifact");
  const changes = [() => { f.input.strategy.scenes[0].result = "TEST changed outcome"; },
    () => { f.input.canvas.occurrences[0][5] = "Different"; },
    () => { f.input.strategy.pacing!.beats[0].reason = "TEST changed rhythm"; },
    () => { f.input.strategy.pacing!.holds[1].minimumFrames += 1; },
    () => { f.input.strategy.assetUse!.decisions[0].claimLimit = "TEST changed claim scope"; }];
  for (const change of changes) {
    const saved = structuredClone(f.input); change();
    assert.throws(() => assertNativeShortStory(f.input, f.html()), /Story is stale/);
    Object.assign(f.input, saved);
  }
}));

test("story beats cannot omit, reorder or move outside their containing scene", () => withAssetUse(f => {
  author(f);
  const beats = f.input.strategy.story!.beats;
  beats[0].pacingBeatIndex = 1;
  assert.throws(() => assembleNativeShortHtml(f.input), /ordered pacing beat/);
  beats[0].pacingBeatIndex = 0; beats[0].sceneIndex = 99;
  assert.throws(() => assembleNativeShortHtml(f.input), /containing scene/);
  beats[0].sceneIndex = 0; beats.pop();
  assert.throws(() => assembleNativeShortHtml(f.input), /bind every pacing beat/);
}));

test("phase, continuity and selected payoff cannot be silently substituted", () => withAssetUse(f => {
  author(f);
  const story = f.input.strategy.story!;
  story.beats[0].phase = "payoff"; story.beats[1].phase = "setup";
  assert.throws(() => assembleNativeShortHtml(f.input), /develop from setup/);
  story.beats[0].phase = "setup"; story.beats[1].phase = "payoff";
  story.beats[1].continuityId = "unrelated-subject";
  assert.throws(() => assembleNativeShortHtml(f.input), /continuous subject/);
  story.beats[1].continuityId = story.continuity.id; story.payoff = "TEST different promise";
  assert.throws(() => assembleNativeShortHtml(f.input), /selected strategy payoff/);
}));

test("artifact holds must actually fit the job beat and remain readable under shared pacing", () => withAssetUse(f => {
  author(f, "real-artifact");
  const job = f.input.strategy.story!.beats[0].visualJobs[0], holdIndex = job.holdIndex!;
  job.holdIndex = null;
  assert.throws(() => assembleNativeShortHtml(f.input), /existing readable hold/);
  job.holdIndex = holdIndex + 1;
  assert.throws(() => assembleNativeShortHtml(f.input), /inside its pacing beat/);
  job.holdIndex = holdIndex; f.input.strategy.pacing!.holds[holdIndex].minimumFrames = 100; rebind(f);
  assert.throws(() => assembleNativeShortHtml(f.input), /exceeds its executable hold/);
}));

test("real operations require demonstrate purpose, video, ordered frames and readable result", () => withAssetUse(f => {
  author(f, "real-operation");
  const decision = f.input.strategy.assetUse!.decisions[0], job = f.input.strategy.story!.beats[0].visualJobs[0];
  decision.purpose = "identify"; rebind(f);
  assert.throws(() => assembleNativeShortHtml(f.input), /demonstration decision/);
  decision.purpose = "demonstrate"; rebind(f);
  job.operation!.resultFrame = job.operation!.actionFrame;
  assert.throws(() => assembleNativeShortHtml(f.input), /ordered action\/result/);
  job.operation!.resultFrame = 20;
  assert.throws(() => assembleNativeShortHtml(f.input), /readable result hold/);
  job.operation!.resultFrame = 19;
  assert.throws(() => assembleNativeShortHtml(f.input), /readable result hold/);
  delete job.operation;
  assert.throws(() => assembleNativeShortHtml(f.input), /story operation must be an object/);
}));

test("still and contextual artifact cannot masquerade as performed operations", () => withAssetUse(f => {
  author(f, "real-artifact");
  const job = f.input.strategy.story!.beats[0].visualJobs[0];
  job.operation = { actionFrame: 1, resultFrame: 10, actionObserved: "TEST scroll", resultObserved: "TEST page" };
  assert.throws(() => assembleNativeShortHtml(f.input), /Only a real-operation/);
  job.kind = "real-operation"; f.input.strategy.assetUse!.decisions[0].purpose = "demonstrate"; rebind(f);
  assert.throws(() => assembleNativeShortHtml(f.input), /actual video or web recording/);
}));

test("optional story report is immutable and cold reader rejects fabricated review labels", () => withAssetUse(f => {
  author(f, "real-artifact");
  const { directory } = writeNativeShortProject(f.input, path.join(f.directory, "story"));
  assert.deepEqual(readNativeShortProject(directory), f.input);
  const reportFile = path.join(directory, "STORY-REPORT.json"), manifestFile = path.join(directory, "PROJECT-MANIFEST.json");
  const report = JSON.parse(readFileSync(reportFile, "utf8")), manifest = JSON.parse(readFileSync(manifestFile, "utf8"));
  report.narrativeQuality = "fabricated-story-approval"; writeFileSync(reportFile, JSON.stringify(report));
  manifest.files.find((row: { file: string }) => row.file === "STORY-REPORT.json").sha256 = fileSha256(reportFile);
  writeFileSync(manifestFile, JSON.stringify(manifest));
  assert.throws(() => readNativeShortProject(directory), /story report differs/);
  manifest.files = manifest.files.filter((row: { file: string }) => row.file !== "STORY-REPORT.json");
  writeFileSync(manifestFile, JSON.stringify(manifest));
  assert.throws(() => readNativeShortProject(directory), /omits or duplicates/);
}));

test("unsupported verification flags are rejected rather than treated as story approval", () => withAssetUse(f => {
  author(f);
  Object.assign(f.input.strategy.story!, { editorialApproved: true });
  assert.throws(() => assembleNativeShortHtml(f.input), /unsupported fields.*editorialApproved/);
}));

test("title cards, primary presenter views and missing targets cannot substitute for comparison graphics", () => withAssetUse(f => {
  author(f, "explanatory-comparison");
  const job = f.input.strategy.story!.beats[0].visualJobs[0], scene = f.input.strategy.scenes[0];
  scene.visibleIds.push("native-title-card"); job.targetId = "native-title-card";
  const hold = f.input.strategy.pacing!.holds[job.holdIndex!]; hold.targetId = job.targetId;
  Object.assign(f.input.strategy.pacing!, nativePacingBindings(f.input)); f.refresh(); rebind(f);
  assert.throws(() => assembleNativeShortHtml(f.input), /actual graphic/);
  job.targetId = "source-0-0"; hold.targetId = job.targetId; rebind(f);
  assert.throws(() => assembleNativeShortHtml(f.input), /actual graphic/);
  job.targetId = "comparison"; hold.targetId = job.targetId; scene.format = "presenter";
  Object.assign(f.input.strategy.pacing!, nativePacingBindings(f.input)); f.refresh(); rebind(f);
  assert.throws(() => assembleNativeShortHtml(f.input), /explanatory comparison/);
  job.targetId = "missing-target";
  assert.throws(() => assembleNativeShortHtml(f.input), /executable target/);
}));
