/** Typed inspection on motion reviews: still frames, playback and listening are separate kinds bound to exact bytes.
 * Every record here is TEST-labelled structure only; nobody viewed or heard the synthetic clips. */
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { test, type TestContext } from "node:test";
import { assertNativeMotionReviews } from "../native-motion-review";
import { submitNativeMotionReview } from "../native-motion-review-submission";
import { assertFrameSeen, readInspection } from "../native-review-submission-shared";
import { givenBlock, inspected, motionFixture, motionObservations, rewritePacket, testRoot, writeJson,
  writeText } from "./_native-review-fixture";

function setup(t: TestContext) {
  const f = motionFixture(testRoot(t, "TEST-review-inspection-"));
  const records = path.dirname(f.packet.path), observations = path.join(records, "OBS.json");
  const output = path.join(records, "MOTION-REVIEW-v1.json");
  const regionPacket = writeJson(path.join(records, "motion-review-input.json"),
    (JSON.parse(readFileSync(f.preview, "utf8")) as { packet: unknown }).packet);
  /** Every second frame of each window: dense, but still a sampled picture review. */
  const stills = () => f.clips.map(clip => inspected("still-frames", clip, "whole",
    Array.from({ length: (clip.endFrameExclusive - clip.startFrame) / 2 }, (_, index) => clip.startFrame + 2 * index)));
  return { ...f, observations, output, regionPacket, stills, draft: () => motionObservations(f.packet.sha256, f.clips),
    write: (value: unknown) => writeJson(observations, value),
    submit: () => submitNativeMotionReview({ packet: f.packet.path, observations, output }) };
}

test("still frames never claim motion or audio: a stills-only pass approving either is refused", t => {
  const s = setup(t);
  s.write({ ...s.draft(), inspection: s.stills() });
  assert.throws(() => s.submit(), /approves motion, but frames 0–60 of .* lack normal-speed motion playback \(still frames never establish motion\)/);
  s.write({ ...s.draft(), inspection: [...s.draft().inspection, ...s.stills()], approves: ["picture", "motion", "audio"] });
  assert.throws(() => s.submit(), /approves audio, but frames 0–60 .* lack listening to the actual audio/);
  assert.equal(existsSync(s.output), false);
});

test("a stills-only pass is recorded as picture-only and never admits full rendering", t => {
  const s = setup(t);
  s.write({ ...s.draft(), inspection: s.stills(), approves: ["picture"] });
  const result = s.submit();
  assert.equal(result.status, "recorded-motion-review-picture-only");
  assert.equal(result.admitsFullRendering, false);
  assert.deepEqual(result.inspection.levels, { "still-frames": "sampled", "motion-playback": "none", "audio-listening": "none" });
  assert.deepEqual(result.inspection.picture, { coverage: "sampled", framesLookedAt: 90, framesReviewed: 180 });
  assert.match(result.nextStep, /full rendering needs normal-speed motion playback of every window/);
  assert.throws(() => assertNativeMotionReviews(s.output, s.regionPacket),
    /needs a current independent review for project \(its pass approves picture only/);
});

test("typed playback plus listening of every window admits full rendering and reports the audio approval", t => {
  const s = setup(t);
  s.write({ ...s.draft(), inspection: [...s.draft().inspection, ...s.clips.map(clip => inspected("audio-listening", clip))],
    approves: ["picture", "motion", "audio"], limitations: [] });
  assert.equal(s.submit().status, "recorded-independent-motion-pass");
  assert.deepEqual(assertNativeMotionReviews(s.output, s.regionPacket).inspection.audioApprovedUnits, ["project"]);
});

test("stale identity: older bytes, unbound artifacts and out-of-window frames are refused", t => {
  const s = setup(t);
  const older = { path: s.clips[0].path, sha256: "b".repeat(64) };
  s.write({ ...s.draft(), inspection: [inspected("motion-playback", older), ...s.draft().inspection.slice(1)] });
  assert.throws(() => s.submit(), /Stale inspection: inspection\[0\] names sha256 bbbbbbbbbbbb .* an older or different artifact/);
  const elsewhere = writeText(path.join(s.root, "TEST-other-preview.mp4"), "TEST bytes nobody bound");
  s.write({ ...s.draft(), inspection: [...s.draft().inspection, inspected("still-frames", { path: elsewhere, sha256: "c".repeat(64) })] });
  assert.throws(() => s.submit(), /neither frozen in the role packet nor listed in evidence/);
  s.write({ ...s.draft(), inspection: [...s.draft().inspection, inspected("still-frames", s.clips[1], { frames: [100, 200] }, [120])] });
  assert.throws(() => s.submit(), /frames 100–200 lie outside 120–180/);
  s.write({ ...s.draft(), inspection: [...s.draft().inspection, inspected("still-frames", s.clips[1], { frames: [120, 150] }, [150])] });
  assert.throws(() => s.submit(), /still sample 150 is not a program frame inside the entry's span/);
  s.write({ ...s.draft(), inspection: [...s.draft().inspection, inspected("audio-listening", s.clips[1], { seconds: [0, 2] })] });
  assert.throws(() => s.submit(), /a reviewed rendering is covered in program frames; use "whole" or frames/);
  s.write({ ...s.draft(), inspection: [...s.draft().inspection, inspected("still-frames", s.clips[1], "whole", [130, 125])] });
  assert.throws(() => s.submit(), /samples must list .* distinct ascending frames/);
  assert.equal(existsSync(s.output), false);
});

test("the reader refuses a hand-built typed row whose inspection names other bytes than its preview's clips", t => {
  const s = setup(t);
  s.write(s.draft());
  s.submit();
  const bundle = JSON.parse(readFileSync(s.output, "utf8"));
  bundle.reviews[0].inspection.entries[1].artifact.sha256 = "d".repeat(64);
  const forged = writeJson(path.join(path.dirname(s.output), "MOTION-REVIEW-forged.json"), bundle);
  assert.throws(() => assertNativeMotionReviews(forged, s.regionPacket), /Stale inspection: entry 1 covered .* as sha256 dddddddddddd/);
  bundle.reviews[0].inspection.entries = s.stills();
  writeJson(forged, bundle);
  assert.throws(() => assertNativeMotionReviews(forged, s.regionPacket), /approves motion, but .* lack normal-speed motion playback/);
});

test("implausible completion: impossible timing, notes on frames nobody inspected and approvals without a pass", t => {
  const s = setup(t);
  const fresh = rewritePacket(s.packet.path, packet => { packet.resolvedAt = new Date().toISOString(); });
  s.write({ ...motionObservations(fresh, s.clips) });
  assert.throws(() => s.submit(), /Implausible completion: the inspection claims 6\.0 s of normal-speed playback or listening \(summed over artifacts\)/);
  const issue = { code: "TEST_EXIT", severity: "major", lane: "motion", message: "TEST exit", frames: [10, 20], requiredAction: "TEST" };
  const unseen = { ...motionObservations(fresh, s.clips), verdict: "revise", approves: [], materialIssues: [issue],
    inspection: [inspected("still-frames", s.clips[0], { frames: [0, 30] }, [0, 10, 20, 29])] };
  unseen.windows[0].observations = [{ frame: 45, note: "TEST claims to describe an uninspected frame" }];
  s.write(unseen);
  assert.throws(() => s.submit(), /windows\[0\]\.observations\[0\] notes frame 45, but it was never looked at on/);
  s.write({ ...unseen, approves: ["picture"] });
  assert.throws(() => s.submit(), /A revise verdict approves nothing: approves must be \[\]/);
  assert.equal(existsSync(s.output), false);
});

test("operator verification P2: one still per window is a sampled review and supports only its exact frames", t => {
  const s = setup(t);
  const entries = s.clips.map(clip => inspected("still-frames", clip, "whole", [clip.startFrame]));
  const draft = { ...s.draft(), inspection: entries, approves: ["picture"] };
  s.write(draft);
  const result = s.submit();
  assert.equal(result.inspection.levels["still-frames"], "sampled");
  assert.deepEqual(result.inspection.picture, { coverage: "sampled", framesLookedAt: 3, framesReviewed: 180 });
  assert.equal(result.admitsFullRendering, false);
  const inspection = readInspection({ schemaVersion: 1, entries, approves: ["picture"] });
  assert.throws(() => assertFrameSeen(inspection, s.clips[0], 59, "TEST frame 59"), /frame 59, but it was never looked at on/);
  assertFrameSeen(inspection, s.clips[0], 0, "TEST sampled frame 0");
  const unseenNote = structuredClone(draft);
  unseenNote.windows[0].observations = [{ frame: 59, note: "TEST describes a frame nobody looked at" }];
  s.write(unseenNote);
  const second = path.join(path.dirname(s.output), "MOTION-REVIEW-v2.json");
  assert.throws(() => submitNativeMotionReview({ packet: s.packet.path, observations: s.observations, output: second }),
    /windows\[0\]\.observations\[0\] notes frame 59, but it was never looked at on/);
  const issue = { code: "TEST_EXIT", severity: "major", lane: "motion", message: "TEST exit", frames: [30, 60], requiredAction: "TEST" };
  s.write({ ...draft, verdict: "revise", approves: [], materialIssues: [issue] });
  assert.throws(() => submitNativeMotionReview({ packet: s.packet.path, observations: s.observations, output: second }),
    /materialIssues\[0\] locates frames 30–60, none of which was looked at/);
  assert.equal(existsSync(second), false);
});

test("operator item #6: listening alone supports no visual or motion note or claim; it supports audible ones", t => {
  const s = setup(t);
  const audio = s.clips.map(clip => inspected("audio-listening", clip));
  const base = { ...s.draft(), verdict: "revise", approves: [], inspection: audio,
    limitations: ["TEST: only audio was declared; no visual inspection"] };
  const visual = { code: "TEST_VISUAL_STALE_TITLE", severity: "major", lane: "motion", frames: [15, 30],
    message: "TEST the title stays visible after its exit", requiredAction: "TEST change the title opacity animation" };
  s.write({ ...base, windows: base.windows.map(w => ({ ...w, observations: [] })), materialIssues: [visual] });
  assert.throws(() => s.submit(), /materialIssues\[0\] locates frames 15–30, none of which was looked at \(a visual or motion claim/);
  const notes = base.windows.map(w => ({ ...w, observations: [{ frame: w.startFrame + 15, note: "TEST future graphic visible" }] }));
  const audibleIssue = { ...visual, code: "TEST_HUM", lane: "audio", message: "TEST hum under the voice",
    requiredAction: "TEST apply the hum filter" };
  s.write({ ...base, windows: notes, materialIssues: [audibleIssue] });
  assert.throws(() => s.submit(), /notes frame 15, but it was never looked at on/);
  const audible = { ...visual, code: "TEST_CLIPPED_WORD", lane: "audio", message: "TEST a word is clipped at the seam",
    requiredAction: "TEST move the cut after the word" };
  s.write({ ...base, windows: base.windows.map(w => ({ ...w, observations: [] })), materialIssues: [audible] });
  assert.equal(s.submit().status, "recorded-motion-review-requires-revision");
});

test("adversarial P3: three 2 s windows claimed 2.5 s after resolution are refused (time is summed over artifacts)", t => {
  const s = setup(t);
  const sha = rewritePacket(s.packet.path, packet => { packet.resolvedAt = new Date(Date.now() - 2500).toISOString(); });
  s.write(motionObservations(sha, s.clips));
  assert.throws(() => s.submit(), /Implausible completion: the inspection claims 6\.0 s .* but only 2\.\d s passed/);
  const future = rewritePacket(s.packet.path, packet => { packet.resolvedAt = new Date(Date.now() + 60_000).toISOString(); });
  s.write(motionObservations(future, s.clips));
  assert.throws(() => s.submit(), /Timing inconsistency: the submission time precedes the role packet's resolution time/);
  assert.equal(existsSync(s.output), false);
});

test("given content (MC-13): a proposed change never withholds approval; a departure refuses the pass", t => {
  const s = setup(t);
  const finding = { code: "TEST_GIVEN_WORD", severity: "minor", lane: "copy", message: "TEST the given title misnames the tool",
    evidence: ["TEST"], scope: "proposed-change" };
  s.write({ ...s.draft(), findings: [finding] });
  const passed = s.submit();
  assert.equal(passed.status, "recorded-independent-motion-pass");
  assert.deepEqual(passed.approvedContent, { approved: null, planChecked: false, departures: [], contradictions: [],
    proposedChanges: ["TEST_GIVEN_WORD"] });
  const issue = { code: "TEST_CHANGE_TITLE", severity: "major", lane: "copy", message: "TEST", frames: [0, 10],
    requiredAction: "TEST", scope: "proposed-change" };
  const second = path.join(path.dirname(s.output), "MOTION-REVIEW-v2.json");
  s.write({ ...s.draft(), verdict: "revise", approves: [], materialIssues: [issue] });
  assert.throws(() => submitNativeMotionReview({ packet: s.packet.path, observations: s.observations, output: second }),
    /materialIssues\[0\]\.scope must be execution or approved-content-contradiction/);
  const sha = rewritePacket(s.packet.path, packet => { packet.given = givenBlock({ captionText: { matches: false, mismatchedOccurrences: [4] } }); });
  s.write({ ...s.draft(), rolePacketSha256: sha });
  assert.throws(() => submitNativeMotionReview({ packet: s.packet.path, observations: s.observations, output: second }),
    /departs from the operator's given content \(caption text: 1 occurrence\(s\) carry other words\)/);
});
