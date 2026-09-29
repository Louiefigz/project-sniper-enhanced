/** Typed prebuild and final-review submissions. TEST-labelled structure only; no creative review occurred. */
import assert from "node:assert/strict";
import { existsSync, linkSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { executeNativeReviewCommand } from "../../../../scripts/producer/native-review";
import { fileSha256 } from "../auto-edit-hash";
import { assertNativeFinalReview } from "../native-final-review";
import { submitNativeFinalReview } from "../native-final-review-submission";
import { submitNativePrebuildReview } from "../native-prebuild-review-submission";
import { assertNativeShortPrebuildReview, nativeShortPrebuildPlanHash } from "../native-short-prebuild-review";
import type { NativeShortProjectInput } from "../native-short-project";
import { nativeShortFixture } from "./_native-short-project-fixture";
import { AUTHOR, inspected, reviewer, rewritePacket, rolePacket, testRoot, writeJson, writeText } from "./_native-review-fixture";
import { finalSetup, planSetup } from "./_native-review-subjects";

test("a TEST plan pass is bound to the authored digest and bind-prebuild writes a build-admissible plan", async t => {
  const s = planSetup(t);
  writeJson(s.observations, s.draft());
  const result = s.submit();
  assert.equal(result.status, "recorded-independent-plan-pass");
  assert.equal(result.planHash, s.planHash);
  const record = JSON.parse(readFileSync(s.output, "utf8"));
  assert.equal(record.scope, "native-short-full-plan");
  assert.equal(record.planHash, s.planHash);
  assert.deepEqual(record.inspection, { schemaVersion: 1, entries: [], approves: [] });
  assert.deepEqual(result.inspection.levels, { "still-frames": "none", "motion-playback": "none", "audio-listening": "none" });
  const newPlan = path.join(s.records, "native-plan-v2.json");
  const bound = await executeNativeReviewCommand(["bind-prebuild", s.planFile, s.output, newPlan]) as { planHash: string };
  assert.equal(bound.planHash, s.planHash);
  const written = JSON.parse(readFileSync(newPlan, "utf8")) as NativeShortProjectInput;
  assert.deepEqual(written.prebuildReview, { path: s.output, sha256: fileSha256(s.output) });
  assert.equal(assertNativeShortPrebuildReview(written).planHash, s.planHash);
  await assert.rejects(executeNativeReviewCommand(["bind-prebuild", s.planFile, s.output, newPlan]), /already exists/);
});

test("plan submission refuses a changed plan, a packet digest mismatch and incomplete scene notes", t => {
  const s = planSetup(t);
  writeJson(s.observations, { ...s.draft(), scenes: [] });
  assert.throws(() => s.submit(), /scenes must note every one of the plan's 1 scenes/);
  const shifted = s.draft();
  shifted.scenes[0].endFrame = 49;
  writeJson(s.observations, shifted);
  assert.throws(() => s.submit(), /scenes\[0\] must be scene 0, frames 0–50/);
  const unwritten = s.draft();
  (unwritten.scenes[0] as { note: unknown }).note = null;
  writeJson(s.observations, unwritten);
  assert.throws(() => s.submit(), /scenes\[0\]\.note/);
  writeFileSync(s.planFile, readFileSync(s.planFile, "utf8").replace("TEST presenter", "TEST presenter (edited)"));
  writeJson(s.observations, s.draft());
  assert.throws(() => s.submit(), /Stale review inputs/);
  assert.equal(existsSync(s.output), false);
});

test("a plan record is refused beside a staged project, and a final record inside the export attempt", t => {
  const s = planSetup(t);
  writeJson(s.observations, s.draft());
  writeText(path.join(s.root, "clip", "PROJECT-MANIFEST.json"), "{}");
  const beside = path.join(s.root, "clip", "PREBUILD-REVIEW.json");
  assert.throws(() => submitNativePrebuildReview({ packet: s.packet.path, observations: s.observations, output: beside }),
    /must stay outside the staged project or attempt/);
  assert.equal(existsSync(beside), false);
  const f = finalSetup(t);
  writeJson(f.observations, f.draft());
  const inside = path.join(path.dirname(f.video), "FINAL-REVIEW.json");
  assert.throws(() => submitNativeFinalReview({ packet: f.packet.path, observations: f.observations, output: inside }),
    /must stay outside the staged project or attempt/);
  assert.equal(existsSync(inside), false);
});

test("a packet whose recorded plan digest disagrees with the plan's authored fields is refused", t => {
  const root = testRoot(t, "TEST-prebuild-digest-"), input = nativeShortFixture(root);
  const planFile = writeJson(path.join(root, "plan.json"), input);
  const packet = rolePacket(root, "plan-critic", { plan: { path: planFile, sha256: fileSha256(planFile)!, planHash: "d".repeat(64) } }, [planFile]);
  const observations = writeJson(path.join(root, "obs.json"), { schemaVersion: 1 });
  assert.throws(() => submitNativePrebuildReview({ packet: packet.path, observations, output: path.join(root, "R.json") }),
    /plan digest disagrees/);
});

test("a revise plan verdict is recorded but can never be bound for a build", async t => {
  const s = planSetup(t);
  writeJson(s.observations, { ...s.draft(), verdict: "revise", materialIssues: [{ code: "TEST_MISSING_PAYOFF", severity: "major",
    lane: "story", message: "TEST ending does not answer the opening.", evidence: ["scene 0"], requiredAction: "TEST retain the answer." }] });
  const result = s.submit();
  assert.equal(result.status, "recorded-plan-review-requires-revision");
  assert.equal(result.admitsBuild, false);
  await assert.rejects(executeNativeReviewCommand(["bind-prebuild", s.planFile, s.output, path.join(s.records, "p2.json")]), /must pass/);
});

test("a TEST final pass binds the checked delivery, its exact MP4 and the rendered plan digest", async t => {
  const s = finalSetup(t);
  writeJson(s.observations, s.draft());
  const result = s.submit();
  assert.equal(result.status, "recorded-independent-final-pass");
  assert.equal(result.editorialFinal, "approved");
  assert.equal(result.humanApproved, false);
  assert.deepEqual(result.inspection.levels, { "still-frames": "none", "motion-playback": "complete", "audio-listening": "complete" });
  const record = JSON.parse(readFileSync(s.output, "utf8"));
  assert.equal(record.planHash, nativeShortPrebuildPlanHash(s.plan as unknown as NativeShortProjectInput));
  assert.deepEqual(record.export.video, { path: s.video, sha256: fileSha256(s.video) });
  const checked = await executeNativeReviewCommand(["check-final", s.output]) as { status: string };
  assert.equal(checked.status, "recorded-independent-final-pass");
  writeFileSync(s.video, "TEST re-encoded bytes");
  assert.throws(() => assertNativeFinalReview(s.output), /changed/);
});

test("a delivered MP4 with a handoff hard link is bound by hash, but cannot be pinned as reader evidence", t => {
  const s = finalSetup(t);
  linkSync(s.video, path.join(s.root, "TEST handoff copy.mp4"));
  writeJson(s.observations, { ...s.draft(), evidence: [{ path: s.video }] });
  assert.throws(() => s.submit(), /cannot be bound by the review reader/);
  writeJson(s.observations, s.draft());
  assert.equal(s.submit().status, "recorded-independent-final-pass");
});

test("final submission refuses stale media, an unchecked delivery, missing events and an incomplete-playback pass", t => {
  const s = finalSetup(t);
  const partial = s.draft();
  partial.inspection = [inspected("motion-playback", s.file, { frames: [0, 150] }), inspected("audio-listening", s.file)];
  writeJson(s.observations, partial);
  assert.throws(() => s.submit(), /approves motion, but frames 0–300 of .* lack normal-speed motion playback/);
  writeJson(s.observations, { ...s.draft(), events: s.draft().events.slice(1) });
  assert.throws(() => s.submit(), /events must note every one of the packet's 3 program events/);
  writeJson(s.observations, { ...s.draft(), reviewer: reviewer(AUTHOR, "TEST-other") });
  assert.throws(() => s.submit(), /recorded author/);
  writeFileSync(s.video, "TEST changed after the packet");
  writeJson(s.observations, s.draft());
  assert.throws(() => s.submit(), /Stale review inputs/);
  assert.equal(existsSync(s.output), false);
  const u = finalSetup(t);
  writeJson(u.delivery, { ...JSON.parse(readFileSync(u.delivery, "utf8")), status: "native-short-rendered-awaiting-qc" });
  const repacked = rolePacket(u.root, "final-critic", JSON.parse(readFileSync(u.packet.path, "utf8")).subject, [u.delivery, [u.video, "linked-media"]]);
  writeJson(u.observations, { ...u.draft(), rolePacketSha256: repacked.sha256 });
  assert.throws(() => submitNativeFinalReview({ packet: repacked.path, observations: u.observations, output: u.output }),
    /checked-for-review delivery/);
});

test("a stills-only final pass is recorded but never an editorial final; stills claiming motion or audio are refused", async t => {
  const s = finalSetup(t);
  const stills = inspected("still-frames", s.file, "whole", [...Array.from({ length: 150 }, (_, index) => 2 * index), 299]);
  writeJson(s.observations, { ...s.draft(), inspection: [stills] });
  assert.throws(() => s.submit(), /approves motion, but frames 0–300 .* lack normal-speed motion playback \(still frames never establish motion\)/);
  writeJson(s.observations, { ...s.draft(), inspection: [stills], approves: ["picture", "audio"] });
  assert.throws(() => s.submit(), /approves audio, but frames 0–300 .* lack listening to the actual audio/);
  writeJson(s.observations, { ...s.draft(), inspection: [stills], approves: ["picture"] });
  const result = s.submit();
  assert.equal(result.status, "recorded-independent-rendered-pass-not-final");
  assert.equal(result.editorialFinal, "not-established");
  assert.deepEqual(result.missing, ["whole-program normal-speed motion playback", "whole-program listening"]);
  assert.deepEqual(result.inspection.picture, { coverage: "sampled", framesLookedAt: 151, framesReviewed: 300 });
  assert.match(result.nextStep, /Not an editorially approved final/);
  const checked = await executeNativeReviewCommand(["check-final", s.output]) as { editorialFinal: string; humanApproved: boolean };
  assert.deepEqual([checked.editorialFinal, checked.humanApproved], ["not-established", false]);
});

test("final stale identity and implausible completion are refused before publication", t => {
  const s = finalSetup(t);
  writeJson(s.observations, { ...s.draft(), inspection: [inspected("motion-playback", { path: s.video, sha256: "e".repeat(64) })] });
  assert.throws(() => s.submit(), /Stale inspection: inspection\[0\] names sha256 eeeeeeeeeeee/);
  const issue = { code: "TEST_SEAM", severity: "major", lane: "audio", message: "TEST seam", frames: [10, 20], requiredAction: "TEST" };
  writeJson(s.observations, { ...s.draft(), verdict: "revise", approves: [], materialIssues: [issue],
    inspection: [inspected("motion-playback", s.file, { frames: [0, 150] })], frameNotes: [{ frame: 200, note: "TEST unseen" }] });
  assert.throws(() => s.submit(), /frameNotes\[0\] notes frame 200, but it was never looked at on/);
  const packet = JSON.parse(readFileSync(s.packet.path, "utf8"));
  const fresh = rolePacket(path.join(s.root, "fresh"), "final-critic", packet.subject, [s.delivery, [s.video, "linked-media"]]);
  const rewritten = { ...JSON.parse(readFileSync(fresh.path, "utf8")), resolvedAt: new Date().toISOString() };
  const now = writeJson(fresh.path, rewritten), sha = fileSha256(now)!;
  writeJson(s.observations, { ...s.draft(), rolePacketSha256: sha });
  assert.throws(() => submitNativeFinalReview({ packet: now, observations: s.observations, output: s.output }),
    /Implausible completion: the inspection claims 10\.0 s of normal-speed playback or listening/);
  assert.equal(existsSync(s.output), false);
});

test("historical final records read as untyped declarations and a forged typed record cannot claim motion from stills", t => {
  const s = finalSetup(t);
  writeJson(s.observations, s.draft());
  s.submit();
  const { inspection: _inspection, submission: _submission, approvedContent: _approved, ...rest } = JSON.parse(readFileSync(s.output, "utf8"));
  void _inspection; void _submission; void _approved;
  const historical = writeJson(path.join(s.records, "FINAL-REVIEW-historical.json"), { ...rest, schemaVersion: 1,
    playback: { completed: true, method: "TEST declared" }, listening: { performed: true, notes: "TEST declared" } });
  const read = assertNativeFinalReview(historical);
  assert.equal(read.status, "recorded-historical-rendered-review-untyped-pass");
  assert.equal(read.editorialFinal, "not-established");
  assert.deepEqual(read.inspection, { typed: false, authenticity: "declared-not-authenticated", declaredBy: null, approves: [], picture: null,
    levels: { "still-frames": "untyped", "motion-playback": "untyped", "audio-listening": "untyped" } });
  assert.deepEqual(read.declared, { playbackCompleted: true, listeningPerformed: true });
  const forged = JSON.parse(readFileSync(s.output, "utf8"));
  forged.inspection.entries = [inspected("still-frames", s.file, "whole", [0, 144, 299])];
  const file = writeJson(path.join(s.records, "FINAL-REVIEW-forged.json"), forged);
  assert.throws(() => assertNativeFinalReview(file), /approves motion, but .* lack normal-speed motion playback/);
});

test("plan critics: a recorded author is refused, a plan never approves rendered media, and source evidence is typed", t => {
  const s = planSetup(t);
  writeJson(s.observations, { ...s.draft(), reviewer: reviewer(AUTHOR, AUTHOR) });
  assert.throws(() => s.submit(), /separate independent reviewer/);
  writeJson(s.observations, { ...s.draft(), reviewer: reviewer(AUTHOR, "TEST-other-planner") });
  assert.throws(() => s.submit(), /recorded author/);
  writeJson(s.observations, { ...s.draft(), approves: ["motion"] });
  assert.throws(() => s.submit(), /A plan review approves the plan only/);
  const still = writeText(path.join(s.root, "TEST-source-still.jpg"), "TEST still bytes");
  const file = { path: still, sha256: fileSha256(still)! };
  writeJson(s.observations, { ...s.draft(), evidence: [{ path: still }], inspection: [inspected("still-frames", file, { frames: [0, 10] })] });
  assert.throws(() => s.submit(), /frame spans are program frames of a reviewed rendering; use seconds or whole/);
  writeJson(s.observations, { ...s.draft(), evidence: [{ path: still }], inspection: [inspected("audio-listening", file, { seconds: [0, 7200] })] });
  assert.throws(() => s.submit(), /Implausible completion: the inspection claims 7200\.0 s/);
  writeJson(s.observations, { ...s.draft(), evidence: [{ path: still }], inspection: [inspected("still-frames", file)] });
  const result = s.submit();
  assert.deepEqual(result.inspection.levels, { "still-frames": "partial", "motion-playback": "none", "audio-listening": "none" });
  assert.equal(result.approvesRenderedMedia, false);
  assert.deepEqual(JSON.parse(readFileSync(s.output, "utf8")).inspection.entries[0].artifact, file);
});

test("plan critics bind large source media by the hash the packet declares; a different hash is stale", t => {
  const s = planSetup(t);
  const source = writeText(path.join(s.root, "TEST-large-source.mov"), "TEST stands in for media above the rehash limit");
  const sha = rewritePacket(s.packet.path, packet => { packet.declaredMedia = [{ key: "asset-0-source", path: source,
    declaredSha256: "a".repeat(64), bytes: 1, observation: "declared-not-rehashed", why: "TEST" }]; });
  const heard = (digest: string) => ({ ...s.draft(), rolePacketSha256: sha,
    inspection: [inspected("audio-listening", { path: source, sha256: digest }, { seconds: [82.9, 84.3] })] });
  writeJson(s.observations, heard("b".repeat(64)));
  assert.throws(() => s.submit(), /Stale inspection: inspection\[0\] names sha256 bbbbbbbbbbbb .* this review binds aaaaaaaaaaaa/);
  writeJson(s.observations, heard("a".repeat(64)));
  assert.deepEqual(s.submit().inspection.levels, { "still-frames": "none", "motion-playback": "none", "audio-listening": "partial" });
});

test("adversarial P5: a historical schema-1 block keeps its verdict in the status and is never a final", t => {
  const s = finalSetup(t);
  const issue = { code: "TEST_X", severity: "major", lane: "motion", message: "TEST", frames: [10, 20], requiredAction: "TEST" };
  writeJson(s.observations, { ...s.draft(), verdict: "block", approves: [], materialIssues: [issue] });
  s.submit();
  const { inspection: _i, submission: _s, approvedContent: _a, ...rest } = JSON.parse(readFileSync(s.output, "utf8"));
  void _i; void _s; void _a;
  const historical = writeJson(path.join(s.records, "FINAL-REVIEW-historical-block.json"), { ...rest, schemaVersion: 1,
    playback: { completed: false, method: "TEST declared" }, listening: { performed: false, notes: "TEST declared" } });
  const read = assertNativeFinalReview(historical);
  assert.deepEqual([read.status, read.verdict, read.editorialFinal],
    ["recorded-historical-rendered-review-untyped-block", "block", "not-established"]);
});

test("adversarial P6 and item 7: whole-program claims fit only the recorded interval; unseen event notes are refused", t => {
  const s = finalSetup(t);
  writeJson(s.observations, { ...s.draft(), inspection: [inspected("still-frames", s.file, "whole", [0, 144])],
    approves: ["picture"] });
  assert.throws(() => s.submit(), /events\[2\] notes frame 299, but it was never looked at on/);
  writeJson(s.observations, s.draft());
  const result = s.submit();
  assert.equal(result.editorialFinal, "approved");
  assert.equal(result.inspection.authenticity, "declared-not-authenticated");
  assert.deepEqual(result.inspection.declaredBy, { identity: "TEST synthetic critic", sessionId: "TEST-critic-session" });
  const record = JSON.parse(readFileSync(s.output, "utf8"));
  assert.ok(Date.parse(record.submission.submittedAt) - Date.parse(record.submission.packetResolvedAt) >= 10_000);
  record.submission.submittedAt = new Date(Date.parse(record.submission.packetResolvedAt) + 5000).toISOString();
  const forged = writeJson(path.join(s.records, "FINAL-REVIEW-forged-time.json"), record);
  assert.throws(() => assertNativeFinalReview(forged), /Implausible completion: the inspection claims 10\.0 s/);
});
