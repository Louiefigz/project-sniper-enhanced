/** Typed motion-review submission: canonical paths, stale inputs, verdict consistency, independence and typed
 * inspection. Every record here is TEST-labelled structure only; nobody viewed or heard the synthetic clips. */
import assert from "node:assert/strict";
import { existsSync, linkSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { test, type TestContext } from "node:test";
import { executeNativeReviewCommand } from "../../../../scripts/producer/native-review";
import { fileSha256 } from "../auto-edit-hash";
import { assertNativeMotionReviews } from "../native-motion-review";
import { submitNativeMotionReview } from "../native-motion-review-submission";
import { AUTHOR, CRITIC, inspected, motionFixture, motionObservations, reviewer, rolePacket, testRoot, typedRecordParts,
  writeJson, writeText } from "./_native-review-fixture";

function setup(t: TestContext) {
  const f = motionFixture(testRoot(t));
  const records = path.dirname(f.packet.path);
  const observations = path.join(records, "MOTION-REVIEW-v1-OBSERVATIONS.json"), output = path.join(records, "MOTION-REVIEW-v1.json");
  const regionPacket = writeJson(path.join(records, "motion-review-input.json"),
    (JSON.parse(readFileSync(f.preview, "utf8")) as { packet: unknown }).packet);
  const draft = () => motionObservations(f.packet.sha256, f.clips);
  const write = (value: unknown) => writeJson(observations, value);
  const submit = () => submitNativeMotionReview({ packet: f.packet.path, observations, output });
  return { ...f, records, observations, output, regionPacket, draft, write, submit };
}

test("a complete TEST pass is bound to the exact preview and admitted by the unchanged reader", t => {
  const s = setup(t);
  s.write(s.draft());
  const result = s.submit();
  assert.equal(result.status, "recorded-independent-motion-pass");
  assert.equal(result.admitsFullRendering, true);
  assert.deepEqual(result.units, { project: "a".repeat(64) });
  const record = JSON.parse(readFileSync(s.output, "utf8"));
  assert.equal(record.reviews.length, 1);
  assert.deepEqual(record.reviews[0].preview, { path: s.preview, sha256: fileSha256(s.preview) });
  assert.deepEqual(record.reviews[0].evidence.map((row: { path: string }) => row.path), [s.observations, s.packet.path]);
  assert.match(record.reviews[0].review.findings[0].code, /^REVIEW_LIMITATION_1$/);
  assert.deepEqual(record.reviews[0].inspection.approves, ["picture", "motion"]);
  assert.deepEqual(record.reviews[0].inspection.entries.map((row: { artifact: { sha256: string } }) => row.artifact.sha256),
    s.clips.map(clip => clip.sha256));
  assert.deepEqual(result.inspection.levels, { "still-frames": "none", "motion-playback": "complete", "audio-listening": "none" });
  const admitted = assertNativeMotionReviews(s.output, s.regionPacket);
  assert.equal(admitted.status, "recorded-independent-motion-pass");
  assert.deepEqual(admitted.inspection, { authenticity: "declared-not-authenticated", typedRows: 1, untypedRows: 0,
    testFixtureRows: 0, audioApprovedUnits: [] });
  assert.deepEqual(Object.keys(record.reviews[0].submission).sort(),
    ["authenticity", "packetResolvedAt", "role", "rolePacket", "schemaVersion", "submittedAt", "timing"]);
  assert.deepEqual(record.reviews[0].submission.rolePacket, { path: s.packet.path, sha256: s.packet.sha256 });
  assert.ok(result.timings.totalMs >= 0);
  assert.equal(readdirCandidates(s.records).length, 0);
});

function readdirCandidates(directory: string): string[] {
  return readdirSync(directory).filter(name => name.endsWith(".candidate"));
}

test("observed failure: a packet reached through a symlinked ancestor is refused by the reader but canonicalized by the helper", t => {
  const s = setup(t);
  const alias = path.join(path.dirname(s.root), `${path.basename(s.root)}-alias`);
  symlinkSync(s.root, alias, "dir");
  t.after(() => rmSync(alias, { force: true }));
  const viaAlias = (file: string) => path.join(alias, path.relative(s.root, file));
  s.write(s.draft());
  const result = submitNativeMotionReview({ packet: viaAlias(s.packet.path), observations: viaAlias(s.observations), output: viaAlias(s.output) });
  assert.equal(result.status, "recorded-independent-motion-pass");
  assert.deepEqual(result.canonicalized.map(row => row.input), ["packet", "observations", "output"]);
  assert.equal(result.record.path, s.output);
  const evidence = JSON.parse(readFileSync(s.output, "utf8")).reviews[0].evidence.map((row: { path: string }) => row.path);
  assert.ok(evidence.every((file: string) => file.startsWith(`${s.root}/`)));
  assert.throws(() => assertNativeMotionReviews(s.output, viaAlias(s.regionPacket)), /not canonical and real/);
  assert.equal(assertNativeMotionReviews(s.output, s.regionPacket).status, "recorded-independent-motion-pass");
});

test("observed failure: the macOS temporary directory (/var/folders) is canonicalized, never used as a record path", { skip: process.platform !== "darwin" }, t => {
  const s = setup(t);
  const raw = mkdtempSync(path.join(tmpdir(), "TEST-review-var-"));
  t.after(() => rmSync(raw, { recursive: true, force: true }));
  assert.notEqual(realpathSync(raw), raw, "macOS tmpdir is expected to sit behind the /var symlink");
  const observations = writeJson(path.join(raw, "observations.json"), s.draft()), output = path.join(raw, "MOTION-REVIEW.json");
  const packetCopy = writeJson(path.join(raw, "packet.json"), JSON.parse(readFileSync(s.regionPacket, "utf8")));
  const result = submitNativeMotionReview({ packet: s.packet.path, observations, output });
  assert.equal(result.record.path, path.join(realpathSync(raw), "MOTION-REVIEW.json"));
  assert.deepEqual(result.canonicalized.map(row => row.input), ["observations", "output"]);
  assert.throws(() => assertNativeMotionReviews(result.record.path, packetCopy), /cut preview artifact directory is not canonical and real/);
  assert.equal(assertNativeMotionReviews(result.record.path, realpathSync(packetCopy)).status, "recorded-independent-motion-pass");
});

test("relative paths from the working directory resolve to canonical records through the CLI", async t => {
  const s = setup(t);
  s.write(s.draft());
  const previous = process.cwd();
  process.chdir(s.records);
  t.after(() => process.chdir(previous));
  const result = await executeNativeReviewCommand(["submit-motion", path.basename(s.packet.path),
    "./MOTION-REVIEW-v1-OBSERVATIONS.json", "MOTION-REVIEW-v1.json"]) as { record: { path: string } };
  assert.equal(result.record.path, s.output);
});

test("the CLI dispatches only its own operations, never inherited object keys", async () => {
  for (const operation of ["toString", "constructor", "__proto__", "hasOwnProperty"]) {
    await assert.rejects(executeNativeReviewCommand([operation, "a", "b", "c"]), /Usage: native-review.ts/, operation);
  }
});

test("outputs are never overwritten, never written through a dangling link and need an existing directory", t => {
  const s = setup(t);
  s.write(s.draft());
  writeText(s.output, "TEST existing record");
  assert.throws(() => s.submit(), /already exists/);
  rmSync(s.output);
  symlinkSync(path.join(s.root, "TEST-missing-target.json"), s.output);
  assert.throws(() => s.submit(), /already exists/);
  rmSync(s.output);
  assert.throws(() => submitNativeMotionReview({ packet: s.packet.path, observations: s.observations,
    output: path.join(s.root, "no-such-directory", "MOTION-REVIEW.json") }), /directory does not exist/);
});

test("records never land inside the reviewed project, the preview attempt or any staged project", t => {
  const s = setup(t);
  s.write(s.draft());
  const staged = path.join(s.root, "other-project");
  writeText(path.join(staged, "PROJECT-MANIFEST.json"), "{}");
  mkdirSync(path.join(staged, "nested"));
  for (const directory of [s.project, s.attempt, path.join(staged, "nested")]) {
    const output = path.join(directory, "MOTION-REVIEW.json");
    assert.throws(() => submitNativeMotionReview({ packet: s.packet.path, observations: s.observations, output }),
      /must stay outside the staged project or attempt/, directory);
    assert.equal(existsSync(output), false, directory);
  }
});

test("stale inputs are refused: a changed clip, preview record or governing instruction publishes nothing", t => {
  for (const change of ["clip", "preview", "instruction"] as const) {
    const s = setup(t);
    s.write(s.draft());
    if (change === "clip") writeFileSync(s.clips[1].path, "TEST replaced clip bytes");
    if (change === "preview") writeFileSync(s.preview, readFileSync(s.preview, "utf8").replace("\"priorPreview\": null", "\"priorPreview\": null "));
    if (change === "instruction") writeFileSync(s.packet.instruction, "# TEST instructions\nChanged governing text.\n");
    assert.throws(() => s.submit(), /Stale review inputs/, change);
    assert.equal(existsSync(s.output), false, change);
  }
});

test("observations must belong to this packet, exist and be completely authored", t => {
  const s = setup(t);
  assert.throws(() => s.submit(), /Observations file does not exist/);
  s.write({ ...s.draft(), rolePacketSha256: "b".repeat(64) });
  assert.throws(() => s.submit(), /different role packet/);
  const unfilled = s.draft();
  (unfilled.coverage as Record<string, unknown>).feasibility = null;
  s.write(unfilled);
  assert.throws(() => s.submit(), /feasibility/);
  s.write({ ...s.draft(), verdict: null });
  assert.throws(() => s.submit(), /verdict must be pass, revise or block/);
  const noNotes = s.draft();
  noNotes.windows[1].observations = [];
  s.write(noNotes);
  assert.throws(() => s.submit(), /windows\[1\] was inspected: it needs frame-numbered observations/);
  s.write({ ...s.draft(), schemaVersion: 1 });
  assert.throws(() => s.submit(), /schema 2; re-resolve the role packet/);
  const outside = s.draft();
  outside.windows[0].observations = [{ frame: 200, note: "TEST" }];
  s.write(outside);
  assert.throws(() => s.submit(), /outside the window/);
  const shifted = s.draft();
  shifted.windows[2].startFrame = 239;
  s.write(shifted);
  assert.throws(() => s.submit(), /windows\[2\] must be frames 240–300/);
  s.write({ ...s.draft(), windows: s.draft().windows.slice(0, 2) });
  assert.throws(() => s.submit(), /all 3 preview windows/);
  s.write({ ...s.draft(), limitations: [] });
  assert.throws(() => s.submit(), /audio not covered on every reviewed frame: state what was not done in limitations/);
  assert.equal(existsSync(s.output), false);
});

test("a verdict inconsistent with the critic's own findings or playback is refused", t => {
  const s = setup(t);
  const issue = { code: "TEST_TITLE_EXIT", severity: "major", lane: "motion", message: "TEST title leaves late.",
    frames: [130, 150], requiredAction: "TEST shorten the hold." };
  s.write({ ...s.draft(), materialIssues: [issue] });
  assert.throws(() => s.submit(), /Verdict pass is inconsistent with 1 material issue/);
  s.write({ ...s.draft(), verdict: "revise" });
  assert.throws(() => s.submit(), /Verdict revise needs at least one material issue/);
  const partial = s.draft();
  partial.inspection = partial.inspection.slice(0, 2);
  partial.windows[2].observations = [];
  s.write(partial);
  assert.throws(() => s.submit(), /approves picture, but frames 240–300 of .* lack still-frame inspection or motion playback/);
  s.write({ ...s.draft(), approves: ["motion"] });
  assert.throws(() => s.submit(), /A pass must approve picture/);
  const { frames: _frames, ...unlocated } = issue;
  void _frames;
  s.write({ ...s.draft(), verdict: "block", materialIssues: [unlocated] });
  assert.throws(() => s.submit(), /needs frames/);
  assert.equal(existsSync(s.output), false);
});

test("the critic cannot be a recorded author and must name the recorded planner", t => {
  const s = setup(t);
  s.write({ ...s.draft(), reviewer: reviewer(AUTHOR, AUTHOR) });
  assert.throws(() => s.submit(), /separate independent reviewer/);
  s.write({ ...s.draft(), reviewer: reviewer(AUTHOR, "TEST-other-planner") });
  assert.throws(() => s.submit(), /recorded author/);
  s.write({ ...s.draft(), reviewer: reviewer(CRITIC, "TEST-other-planner") });
  assert.throws(() => s.submit(), /plannerSessionId must name the recorded author/);
  s.write({ ...s.draft(), reviewer: { ...reviewer(), independent: false } });
  assert.throws(() => s.submit(), /independent/);
  assert.equal(existsSync(s.output), false);
});

test("a revise verdict is recorded with its located repair but can never admit full rendering", t => {
  const s = setup(t);
  s.write({ ...s.draft(), verdict: "revise", approves: [], materialIssues: [{ code: "TEST_CAPTION_OVERLAP", severity: "major", lane: "layout",
    message: "TEST caption overlaps the diagram label.", frames: [140, 170], evidence: ["TEST note"],
    requiredAction: "TEST move the label up 40 px." }] });
  const result = s.submit();
  assert.equal(result.status, "recorded-motion-review-requires-revision");
  assert.equal(result.admitsFullRendering, false);
  const issue = JSON.parse(readFileSync(s.output, "utf8")).reviews[0].review.materialIssues[0];
  assert.deepEqual(issue.evidence, ["frames 140–170 (4.667–5.667 s)", "TEST note"]);
  assert.throws(() => assertNativeMotionReviews(s.output, s.regionPacket), /unresolved material findings/);
});

test("critic evidence is canonical, single-link and hash-checked", t => {
  const s = setup(t);
  const note = writeText(path.join(s.root, "TEST-note.md"), "TEST review note");
  const linked = writeText(path.join(s.root, "TEST-linked.jpg"), "TEST still");
  linkSync(linked, path.join(s.root, "TEST-linked-second-name.jpg"));
  s.write({ ...s.draft(), evidence: [{ path: linked }] });
  assert.throws(() => s.submit(), /cannot be bound by the review reader/);
  s.write({ ...s.draft(), evidence: [{ path: note, sha256: "c".repeat(64) }] });
  assert.throws(() => s.submit(), /changed after the critic recorded its hash/);
  s.write({ ...s.draft(), evidence: Array.from({ length: 31 }, (_, index) => ({ path: writeText(path.join(s.root, `TEST-e${index}.txt`), `TEST ${index}`) })) });
  assert.throws(() => s.submit(), /At most 30 evidence files/);
  s.write({ ...s.draft(), evidence: [{ path: note, sha256: fileSha256(note)! }] });
  assert.equal(s.submit().status, "recorded-independent-motion-pass");
});

test("motion evidence inside the engine is refused because the exporter would pin it into unit hashes", t => {
  const s = setup(t);
  const inPacketRepository = writeText(path.join(s.root, "scripts", "TEST-helper.py"), "# TEST");
  const inThisRepository = path.join(process.cwd(), "src", "lib", "server", "native-review-packet.ts");
  for (const file of [inPacketRepository, inThisRepository]) {
    s.write({ ...s.draft(), evidence: [{ path: file }] });
    assert.throws(() => s.submit(), /inside the engine/, file);
  }
  assert.equal(existsSync(s.output), false);
});

test("reused units need their retained current review rows; supplied rows are carried verbatim", t => {
  const root = testRoot(t), project = path.join(root, "clip", "native-v2");
  mkdirSync(project, { recursive: true });
  const units = [{ id: "a", startFrame: 0, endFrame: 150, hash: "1".repeat(64) }, { id: "b", startFrame: 150, endFrame: 300, hash: "2".repeat(64) }];
  const preview = (name: string, changed: string[], hashB: string) => {
    const clip = writeText(path.join(root, "clip", name, "core.mp4"), `TEST ${name}`);
    return writeJson(path.join(root, "clip", name, "motion-previews.json"), { status: "native-motion-previews-complete",
      packet: { project, canvas: { frameRate: "30/1", totalFrames: 300 }, units: [units[0], { ...units[1], hash: hashB }] },
      clips: [{ startFrame: 90, endFrameExclusive: 300, path: clip, sha256: fileSha256(clip)! }],
      changedUnits: changed, reusedUnits: changed.length === 1 ? ["a"] : [] });
  };
  const older = preview("preview-v1", ["a", "b"], "3".repeat(64)), current = preview("preview-v2", ["b"], units[1].hash);
  const olderClip = JSON.parse(readFileSync(older, "utf8")).clips[0];
  const untypedRow = { reviewer: reviewer("TEST-earlier-critic"), coverage: motionObservations("0".repeat(64), []).coverage,
    evidence: [{ path: older, sha256: fileSha256(older)! }], review: { schemaVersion: 1, stage: "plan", verdict: "pass",
      summary: "TEST earlier structural row", materialIssues: [], findings: [] },
    units: { a: units[0].hash, b: "3".repeat(64) }, preview: { path: older, sha256: fileSha256(older)! }, assessment: "TEST" };
  const inspection = { schemaVersion: 1, entries: [inspected("motion-playback", olderClip)], approves: ["picture", "motion"] };
  const parts = typedRecordParts(root, "motion-critic", { reviewer: untypedRow.reviewer, verdict: "pass", inspection },
    { preview: untypedRow.preview });
  const prior = writeJson(path.join(root, "records", "MOTION-REVIEW-v1.json"), { schemaVersion: 1, reviews: [{ ...untypedRow,
    evidence: [...parts.evidence, ...untypedRow.evidence], inspection, submission: parts.submission,
    approvedContent: parts.approvedContent }] });
  const historical = writeJson(path.join(root, "records", "MOTION-REVIEW-historical.json"), { schemaVersion: 1, reviews: [untypedRow] });
  const clip = JSON.parse(readFileSync(current, "utf8")).clips[0];
  const subject = (retention: object) => ({ project, frameRate: "30/1", totalFrames: 300, preview: { path: current, sha256: fileSha256(current)! },
    windows: [clip], units, changedUnits: ["b"], reusedUnits: ["a"], retention });
  const missing = rolePacket(root, "motion-critic", subject({ reusedUnits: ["a"], record: null, rows: [], missingUnits: ["a"] }), [current, clip.path]);
  const observations = writeJson(path.join(root, "records", "obs.json"), motionObservations(missing.sha256, [clip]));
  assert.throws(() => submitNativeMotionReview({ packet: missing.path, observations, output: path.join(root, "records", "R1.json") }),
    /reuses units a without a retained current review/);
  rmSync(missing.path);
  const untyped = rolePacket(root, "motion-critic", subject({ reusedUnits: ["a"], record: { path: historical,
    sha256: fileSha256(historical)! }, rows: [0], missingUnits: [] }), [current, clip.path, historical]);
  writeJson(observations, motionObservations(untyped.sha256, [clip]));
  assert.throws(() => submitNativeMotionReview({ packet: untyped.path, observations, output: path.join(root, "records", "R0.json") }),
    /Retained review 0 is not a passing independent typed motion review/);
  rmSync(untyped.path);
  const kept = rolePacket(root, "motion-critic", subject({ reusedUnits: ["a"], record: { path: prior, sha256: fileSha256(prior)! },
    rows: [0], missingUnits: [] }), [current, clip.path, prior]);
  writeJson(observations, motionObservations(kept.sha256, [clip]));
  const result = submitNativeMotionReview({ packet: kept.path, observations, output: path.join(root, "records", "R2.json") });
  assert.equal(result.status, "recorded-independent-motion-pass");
  assert.equal(result.retainedRows, 1);
  const bundle = JSON.parse(readFileSync(path.join(root, "records", "R2.json"), "utf8"));
  assert.deepEqual(bundle.reviews[0], JSON.parse(readFileSync(prior, "utf8")).reviews[0]);
  const authored = writeJson(path.join(root, "records", "MOTION-REVIEW-by-author.json"), { schemaVersion: 1, reviews: [{
    ...JSON.parse(readFileSync(prior, "utf8")).reviews[0], reviewer: reviewer(AUTHOR, "TEST-other-planner") }] });
  rmSync(kept.path);
  const byAuthor = rolePacket(root, "motion-critic", subject({ reusedUnits: ["a"], record: { path: authored,
    sha256: fileSha256(authored)! }, rows: [0], missingUnits: [] }), [current, clip.path, authored]);
  writeJson(observations, motionObservations(byAuthor.sha256, [clip]));
  assert.throws(() => submitNativeMotionReview({ packet: byAuthor.path, observations, output: path.join(root, "records", "R3.json") }),
    /Retained review 0 is not a passing independent typed motion review/);
  writeJson(observations, { ...motionObservations(byAuthor.sha256, [clip]), verdict: "revise", approves: [], materialIssues: [{
    code: "TEST_FINDING", severity: "major", lane: "motion", message: "TEST finding", frames: [100, 110],
    requiredAction: "TEST repair" }] });
  const findings = submitNativeMotionReview({ packet: byAuthor.path, observations, output: path.join(root, "records", "R4.json") });
  assert.equal(findings.admitsFullRendering, false);
  assert.equal(JSON.parse(readFileSync(path.join(root, "records", "R4.json"), "utf8")).reviews.length, 1);
});
