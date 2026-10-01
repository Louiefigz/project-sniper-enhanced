/** P2-08 speaker-picture and shared-evidence rules on synthetic TEST inputs: no project fixture, no child process
 * (`evidenceCheck.run` is replaced). A two-person source, regions [0,900] and [960,1920], seconds 100-110 at 30 fps. */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { copyFileSync, mkdirSync, mkdtempSync, realpathSync, rmSync, symlinkSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { test, type TestContext } from "node:test";
import { NativeCheckError } from "../native-check-error";
import { evidenceCheck, type SharedSpeakerFacts, type SharedSpeakerInterval } from "../native-review-shared-evidence";
import type { NativePictureView } from "../native-short-composition";
import type { NativeShortProjectInput } from "../native-short-project";
import { nativeSpeakerPictureDecisions, sealedPhraseStatus, speakerObservations, type NativeSpeakerPictureDecision,
  type SpeakerFace } from "../native-short-speaker-evidence";
import { assertNativeSharedEvidence, assertNativeSpeakerPicture, nativeSharedEvidenceMeasure, nativeSpeakerAttributionFindings,
  nativeSpeakerPictureFindings, type SpeakerObservations } from "../native-short-speaker-picture";

const SOURCE = "b".repeat(64), CLIP = { clipId: "TEST-Q1", scriptIdentity: "a".repeat(64), wordRanges: [[1000, 1019]] as [number, number][] };
const style = { size: 64, weight: 700 as const, color: "#ffffff", background: "#171923", align: "center" as const, padding: 12, radius: 8, lineHeight: 1.16 };
const RIGHT: NativePictureView = { startFrame: 0, endFrame: 300, crop: [1000, 0, 607.5, 1080], box: [0, 0, 1080, 1920] };
const LEFT: NativePictureView = { startFrame: 0, endFrame: 300, crop: [100, 0, 607.5, 1080], box: [0, 0, 1080, 1920] };
const SPLIT: NativePictureView[] = [{ startFrame: 0, endFrame: 300, crop: [0, 0, 1215, 1080], box: [0, 0, 1080, 960] },
  { startFrame: 0, endFrame: 300, crop: [705, 0, 1215, 1080], box: [0, 960, 1080, 960] }];
const face = (x: number, w = 150): SpeakerFace => ({ x, y: 300, w, h: w, score: 0.9 });
const [LEFT_FACE, RIGHT_FACE] = [face(400), face(1300)];

/** A valid 10 s plan: 20 kept words of 0.5 s (source words 1000-1019), one label cue over frames 0-149. */
function plan(views: NativePictureView[] = [RIGHT], decisions?: NativeSpeakerPictureDecision[]): NativeShortProjectInput {
  const canvas = { title: "TEST speaker picture", frameRate: "30/1", totalFrames: 300, background: "#171923", sourceSize: { w: 1920, h: 1080 },
    sourceFile: `assets/${SOURCE}.mp4`, cuts: [{ start: 100, end: 110, speed: 1 }], segments: [{ startFrame: 0, endFrameExclusive: 300 }],
    occurrences: Array.from({ length: 20 }, (_, k) => [k, 0, 1000 + k, k * 15, k * 15 + 15, `w${k}`, 0]),
    captionGroups: Array.from({ length: 20 }, (_, k) => [k]), pictureViews: views,
    captionViews: [{ startFrame: 0, endFrame: 300, box: [100, 1500, 800, 160], style }],
    text: [{ id: "label", startFrame: 0, endFrame: 150, role: "label", text: "TEST label", box: [100, 100, 880, 180], style }], shapes: [], motion: [] };
  return { canvas, assets: [{ file: canvas.sourceFile, role: "source", sha256: SOURCE }],
    ...(decisions ? { speakerPictureDecisions: decisions } : {}) } as unknown as NativeShortProjectInput;
}

/** Sampled source frames 3000-3299 (every 6th; dense in the last 1.0 s and the first 0.5 s) with the faces at each time. */
function observations(facesAt: (t: number) => SpeakerFace[], sampledUntil = 110): SpeakerObservations {
  const frames = Array.from({ length: 300 }, (_, k) => ({ frame: 3000 + k, t: Math.round((3000 + k) / 30 * 1e6) / 1e6 }))
    .filter((row) => row.t < sampledUntil).map((row) => ({ ...row, dense: row.t >= sampledUntil - 1 || row.t < 100.5 }))
    .filter((row) => row.dense || (row.frame - 3000) % 6 === 0);
  return { schemaVersion: 1, kind: "sniper-speaker-observations", rate: "30/1", scripts: [CLIP],
    source: { id: "TEST-raw-1", sourceSha256: SOURCE, transcriptSha256: "c".repeat(64) },
    words: Array.from({ length: 20 }, (_, k) => ({ sourceWord: 1000 + k, start: 100 + k / 2, end: 100.5 + k / 2 })),
    faces: frames.map((row) => ({ frame: row.frame, t: row.t, faces: facesAt(row.t) })), sampling: { frames } };
}

const interval = (startSeconds: number, endSeconds: number, speaker: string | null,
  { certainty = speaker ? "established" : "unresolved", visible = ["left", "right"] } = {}): SharedSpeakerInterval => ({ source: "TEST-raw-1",
  startSeconds, endSeconds, speaker, visible, certainty: certainty as SharedSpeakerInterval["certainty"], basis: "visual-and-stereo" });
const regions = (left: [number, number] = [0, 900]) => [{ id: "left", faceRegion: { source: "TEST-raw-1", xRange: left } },
  { id: "right", faceRegion: { source: "TEST-raw-1", xRange: [960, 1920] as [number, number] } }];
const facts = (intervals: SharedSpeakerInterval[], people = regions(), clips = [CLIP]): SharedSpeakerFacts => ({ schemaVersion: 2,
  listening: false, people, intervals, clips, observations: { path: "/TEST/result.json", sha256: "d".repeat(64), owner: "/TEST/o", ownerSha256: "e".repeat(64) } });
const both = () => [LEFT_FACE, RIGHT_FACE];
const codes = (input: NativeShortProjectInput, speakers: SharedSpeakerFacts, seen: SpeakerObservations) =>
  nativeSpeakerPictureFindings(input, speakers, seen).map((row) => `${row.code}:${row.startFrame}-${row.endFrame}${row.blocking ? "" : ":open"}`);

test("unresolved interval over a single-person crop is refused", () => {
  const unresolved = facts([interval(100, 110, null)]);
  assert.deepEqual(codes(plan(), unresolved, observations(both)), ["speaker-unresolved-picture:0-300"]);
  const claimed = plan([RIGHT], [{ startFrame: 0, endFrame: 300, kind: "two-shot", reason: "TEST a claimed two-shot" }]);
  assert.throws(() => assertNativeSpeakerPicture(claimed, unresolved, observations(both)), (error: unknown) => error instanceof NativeCheckError
    && error.code === "speaker-unresolved-picture" && /frames 0-299: unresolved interval 100-110 s: 0 frame\(s\) .* at 87 two-shot sample/u.test(error.message));
});

test("probable speaker outside the crop is refused", () => {
  assert.deepEqual(codes(plan(), facts([interval(100, 110, "left", { certainty: "probable" })]), observations(both)), ["speaker-not-in-picture:0-300"]);
  const noRegion = facts([interval(100, 110, "left", { certainty: "probable" })], regions().slice(1));
  assert.match(nativeSpeakerPictureFindings(plan(), noRegion, observations(() => [RIGHT_FACE]))[0].message, /left has no face region/u);
});

test("face leaving the crop at the end is refused unless an exit decision covers it", () => {
  const leaving = observations((t) => [LEFT_FACE, t >= 109.5 ? face(1700) : RIGHT_FACE]), right = facts([interval(100, 110, "right")]);
  assert.deepEqual(codes(plan(), right, leaving), ["subject-leaves-picture:285-300"]);
  const covered = (reason: string) => plan([RIGHT], [{ startFrame: 280, endFrame: 300, kind: "accepted-exit", reason }]);
  assert.deepEqual(codes(covered("TEST the speaker walks off by design"), right, leaving), []);
  assert.deepEqual(codes(covered("TEST nineteen chars"), right, leaving), ["subject-leaves-picture:285-300"]);
  assert.deepEqual(codes(covered("  TEST nineteen chars  "), right, leaving), ["subject-leaves-picture:285-300"], "padding is not a reason");
  assert.deepEqual(codes(plan(), right, observations((t) => [LEFT_FACE, t >= 109 ? face(1700) : RIGHT_FACE])), [],
    "SP5 anchors on a dense in-sample (P2-08); a face gone for the whole dense tail is a named limit, not an exit");
  const brief = (until: number) => observations((t) => [t >= 109.5 && t < until ? face(1700) : RIGHT_FACE]);
  assert.deepEqual(codes(plan(), right, brief(109.55)), [], "two dense samples out are not an exit");
  assert.deepEqual(codes(plan(), right, brief(109.58)), ["subject-leaves-picture:285-288"]);
  const early = observations((t) => [t >= 105 ? face(1700) : RIGHT_FACE]);
  assert.deepEqual(codes(plan(), facts([interval(100, 105, "right"), interval(105, 110, null, { visible: ["right"] })]), early)
    .filter((row) => row.startsWith("subject")), [], "a face gone before the dense tail left at non-dense samples");
  const handover = codes(plan(), facts([interval(100, 109.5, "right"), interval(109.5, 110, "left")]), leaving);
  assert.deepEqual(handover, ["speaker-not-in-picture:285-300"], "once another speaker governs, the earlier subject's absence is no exit");
  assert.deepEqual(codes(plan(), facts([interval(100, 109, "right"), interval(109, 110, null, { visible: ["right"] })]), leaving)
    .filter((row) => row.startsWith("subject")), ["subject-leaves-picture:285-300"], "without a speaker, the only person pictured is the subject");
  const shortView = plan([{ ...RIGHT, endFrame: 286 }, { ...LEFT, startFrame: 286 }]);
  assert.deepEqual(codes(shortView, facts([interval(100, 109.5, "right"), interval(109.5, 110, null, { visible: ["left"] })]), leaving)
    .filter((row) => row.startsWith("subject")), [], "a view that ends one sample after the exit starts holds no three dense samples");
});

test("two-shot decision is verified by code", () => {
  const unresolved = facts([interval(100, 110, null)]), twoShot = plan(SPLIT, [{ startFrame: 0, endFrame: 300, kind: "two-shot", reason: "TEST both" }]);
  assert.deepEqual(codes(twoShot, unresolved, observations(both)), []);
  assert.deepEqual(codes(plan(SPLIT), unresolved, observations(both)), ["speaker-unresolved-picture:0-300"], "a two-shot is declared, not guessed");
  assert.deepEqual(codes(twoShot, unresolved, observations((t) => (t >= 104 && t < 104.2 ? [RIGHT_FACE] : both()))),
    ["speaker-unresolved-picture:120-121"]);
  assert.deepEqual(codes(twoShot, facts([interval(100, 110, null, { visible: [] })]), observations(both)), ["speaker-unresolved-picture:0-300"],
    "an empty visible list verifies nothing");
  const support = plan([RIGHT], [{ startFrame: 0, endFrame: 150, kind: "supporting-visual", reason: "TEST label" },
    { startFrame: 150, endFrame: 300, kind: "two-shot", reason: "TEST split" }]);
  assert.deepEqual(codes(support, unresolved, observations(both)), ["speaker-unresolved-picture:150-300"]);
});

test("listener-reaction needs a reason", () => {
  const probable = facts([interval(100, 110, "left", { certainty: "probable" })]);
  const reacting = (reason: string, endFrame = 300) => plan([RIGHT], [{ startFrame: 0, endFrame, kind: "listener-reaction", reason }]);
  assert.deepEqual(codes(reacting("TEST the listener nods"), probable, observations(both)), []);
  assert.deepEqual(codes(reacting("TEST nineteen chars"), probable, observations(both)), ["speaker-not-in-picture:0-300"]);
  assert.deepEqual(codes(reacting("TEST the listener nods", 299), probable, observations(both)), ["speaker-not-in-picture:0-300"]);
  const visual = (endFrame: number) => plan([RIGHT], [{ startFrame: 0, endFrame, kind: "supporting-visual", reason: "TEST the label" }]);
  const early = facts([interval(100, 105, "left", { certainty: "probable" }), interval(105, 110, "right")]);
  assert.deepEqual(codes(visual(150), early, observations(both)), [], "a supporting visual over the label cue covers frames 0-149");
  assert.deepEqual(codes(visual(300), facts([interval(100, 110, "left", { certainty: "probable" })]), observations(both)), ["speaker-not-in-picture:0-300"],
    "frames 150-299 have no visual window");
});

test("probable in-crop speaker passes with a non-blocking finding", () => {
  const probable = facts([interval(100, 110, "right", { certainty: "probable" })]);
  assert.deepEqual(codes(plan(), probable, observations(both)), ["speaker-attribution-probable:0-300:open"]);
  assert.doesNotThrow(() => assertNativeSpeakerPicture(plan(), probable, observations(both)));
  assert.deepEqual(codes(plan(SPLIT), probable, observations(both)), [], "shown with the other person, not alone");
  assert.deepEqual(codes(plan(), facts([interval(100, 110, "right", { certainty: "established" })]), observations(both)), []);
});

test("uncovered retained word is refused", () => {
  const early = facts([interval(100, 107, "right")], regions(), [{ ...CLIP, wordRanges: [[1000, 1015]] }]);
  const findings = nativeSpeakerPictureFindings(plan(), early, observations(both));
  assert.deepEqual(findings.map((row) => `${row.code}:${row.startFrame}-${row.endFrame}`), ["speaker-facts-missing:210-240", "speaker-facts-missing:240-300"]);
  assert.match(findings[0].message, /source words 1014-1015 \('w14 w15'\) have their midpoints in no speaker interval/u);
  assert.match(findings[1].message, /source words 1016-1019 lie in no clip this record covers/u);
  assert.ok(findings[1].sourceSeconds[0] === 108 && Math.abs(findings[1].sourceSeconds[1] - (109 + 29 / 30)) < 1e-9);
  const edge = facts([interval(100, 106.75, "right"), interval(106.75, 110, "right")]);
  assert.deepEqual(codes(plan(), edge, observations(both)), [], "a midpoint on an interval start belongs to it (half-open)");
  const gap = facts([interval(100, 106.75, "right"), interval(106.76, 110, "right")]);
  assert.deepEqual(codes(plan(), gap, observations(both)), ["speaker-facts-missing:195-210"]);
  const other = { ...observations(both), source: { id: "TEST-raw-2", sourceSha256: "f".repeat(64), transcriptSha256: "c".repeat(64) } };
  assert.deepEqual(codes(plan(), facts([interval(100, 110, "right")]), other), ["speaker-facts-missing:0-300"]);
  assert.deepEqual(codes(plan(), { ...facts([interval(100, 110, "right")]), clips: null }, observations(both)), ["speaker-facts-missing:0-300"]);
});

test("unmapped face is refused", () => {
  const right = facts([interval(100, 110, "right")]), WIDE: NativePictureView = { ...RIGHT, crop: [800, 0, 607.5, 1080] };
  const walkIn = observations((t) => (t >= 101 && t < 102 ? [...both(), face(855)] : both()));
  assert.deepEqual(codes(plan([WIDE]), right, walkIn), ["speaker-face-unmapped:30-55"]);
  assert.deepEqual(codes(plan(), right, walkIn), [], "U-R7 (X228): the same face outside every crop is read by no rule and not judged");
  assert.deepEqual(codes(plan(), facts([interval(100, 110, "right")], regions([0, 1100])), observations(() => [face(1000, 100)])),
    ["speaker-face-unmapped:0-300", "speaker-not-in-picture:0-300"], "a centre in two regions belongs to nobody");
  assert.deepEqual(codes(plan([{ ...RIGHT, endFrame: 150 }, { ...LEFT, startFrame: 150 }]), facts([interval(100, 105, "right"),
    interval(105, 110, "left")]), observations((t) => (t < 105 ? both() : [LEFT_FACE, face(910, 40)]))), [], "beside the crop: not judged");
  assert.deepEqual(codes(plan([WIDE]), right, observations(() => [face(885), face(825)])), [],
    "region edges are inclusive: centres 960 and 900 map to right and left");
  assert.deepEqual(codes(plan([{ ...RIGHT, endFrame: 150 }]), right, observations((t) => (t < 105 ? [RIGHT_FACE] : [RIGHT_FACE, face(855)]))), [],
    "a face at an output frame no picture view shows is not judged");
});

test("in the picture means at least half of the face box inside a crop", () => {
  const right = facts([interval(100, 110, "right")]);
  for (const [x, verdict] of [[949, ["speaker-not-in-picture:0-300"]], [950, []], [951, []]] as const) {
    assert.deepEqual(codes(plan(), right, observations(() => [face(x, 100)])), verdict, `face from x ${x}`);
  }
});

test("unsampled frames are unmeasured; in an overlap the spoken word's interval governs, in silence the later one", () => {
  const late = facts([interval(100, 105, "right"), interval(105, 110, "left", { certainty: "probable" })]);
  assert.deepEqual(codes(plan(), late, observations(both, 105)), [], "frames 150-299 are unsampled, never 'face absent'");
  assert.deepEqual(codes(plan(), late, observations(both)), ["speaker-not-in-picture:150-300"]);
  // U-R4 (X228), on a record the seal accepts: word 9 [104.5, 105) has its midpoint only in A, word 10 only in B.
  const sealable = facts([interval(100, 105, "right"), interval(104.8, 110, null)]);
  const shot = plan([{ ...RIGHT, endFrame: 150 }, ...SPLIT.map((view) => ({ ...view, startFrame: 150 }))],
    [{ startFrame: 150, endFrame: 300, kind: "two-shot", reason: "TEST both people" }]);
  assert.deepEqual(codes(shot, sealable, observations(both)), [], "frames 144-149 show right finishing his own word 9");
  const silent = { ...observations(both), words: observations(both).words.map((row) => (row.sourceWord === 1009 ? { ...row, end: 104.75 } : row)) };
  assert.deepEqual(codes(shot, sealable, silent), ["speaker-unresolved-picture:144-150"], "no word spans 104.8-105 s: the later interval");
  const tie = facts([interval(100, 104.8, "right"), interval(104.8, 105, "left"), interval(104.8, 110, "right")]);
  assert.deepEqual(codes(plan(), tie, silent), [], "equal starts in silence: the later row governs, so the silent left interval shows nothing");
});

test("the box rule is two-dimensional, and a reason of exactly 20 characters counts", () => {
  const right = facts([interval(100, 110, "right")]), cropped = (height: number) => plan([{ ...RIGHT, crop: [1000, 0, 607.5, height] }]);
  assert.deepEqual(codes(cropped(349), right, observations(() => [face(1300, 100)])), ["speaker-not-in-picture:0-300"], "49 % vertically");
  assert.deepEqual(codes(cropped(350), right, observations(() => [face(1300, 100)])), [], "50 % vertically");
  const reacting = plan([RIGHT], [{ startFrame: 0, endFrame: 300, kind: "listener-reaction", reason: "TEST twenty chars ok" }]);
  assert.deepEqual(codes(reacting, facts([interval(100, 110, "left", { certainty: "probable" })]), observations(both)), []);
});

test("samples from a gap between two cuts are shown by neither cut", () => {
  const input = plan(), canvas = input.canvas, kept = [0, 1, 2, 3, 4, 5, 6, 7, 12, 13, 14, 15, 16, 17, 18, 19];
  Object.assign(canvas, { totalFrames: 240, cuts: [{ start: 100, end: 104, speed: 1 }, { start: 106, end: 110, speed: 1 }],
    segments: [{ startFrame: 0, endFrameExclusive: 120 }, { startFrame: 120, endFrameExclusive: 240 }],
    pictureViews: [{ ...RIGHT, endFrame: 240 }], captionGroups: kept.map((_, id) => [id]),
    occurrences: kept.map((k, id) => [id, k < 8 ? 0 : 1, 1000 + k, id * 15, id * 15 + 15, `w${k}`, 0]) });
  const gapFace = observations((t) => (t >= 104 && t < 106 ? [...both(), face(1000, 100)] : both()));
  assert.deepEqual(codes(input, facts([interval(100, 110, "right")], regions([0, 1100])), gapFace), []);
  assert.deepEqual(codes(input, facts([interval(100, 103, "right")]), observations(both)), ["speaker-facts-missing:90-120", "speaker-facts-missing:120-240"],
    "a run of uncovered words never spans a cut");
});

test("decisions, observation records, record files and source rows are validated, never assumed", (t) => {
  const decision = (row: Record<string, unknown>) => plan([RIGHT], [{ startFrame: 0, endFrame: 300, kind: "two-shot", reason: "TEST", ...row } as never]);
  assert.equal(nativeSpeakerPictureDecisions(decision({})).length, 1);
  for (const row of [{ endFrame: 301 }, { startFrame: 300 }, { startFrame: -1 }, { kind: "wide-shot" }, { reason: "" }, { reason: "x".repeat(1001) }, { extra: 1 }]) {
    assert.throws(() => nativeSpeakerPictureDecisions(decision(row)), /speakerPictureDecisions\[0\]/u, JSON.stringify(row));
  }
  const many = (count: number) => plan([RIGHT], Array.from({ length: count }, () => ({ startFrame: 0, endFrame: 1, kind: "two-shot" as const, reason: "TEST" })));
  assert.equal(nativeSpeakerPictureDecisions(many(256)).length, 256);
  assert.throws(() => nativeSpeakerPictureDecisions(many(257)), /at most 256/u);
  const seen = observations(both);
  assert.equal(speakerObservations(seen).faces.length, seen.faces.length);
  assert.throws(() => nativeSpeakerPictureFindings(plan(), facts([interval(100, 110, "right")]), { ...seen, words: seen.words.filter((row) => row.sourceWord !== 1003) }),
    /Speaker observations lack covered source word 1003; the record and its coverage disagree/u);
  const broken: Array<[(value: Record<string, unknown>) => void, RegExp]> = [
    [(value) => { (value.faces as unknown[]).pop(); }, /face rows and sampled frames differ/u],
    [(value) => { (value.faces as Array<{ t: number }>)[3].t += 0.01; }, /face rows and sampled frames differ/u],
    [(value) => { (value.sampling as { frames: Array<{ dense: unknown }> }).frames[0].dense = "yes"; }, /dense must be true or false/u],
    [(value) => { (value.faces as Array<{ faces: Array<{ w: number }> }>)[0].faces[0].w = 0; }, /has no area/u],
    [(value) => { value.kind = "TEST-other"; }, /not a schema-1 sniper-speaker-observations record/u]];
  for (const [change, text] of broken) {
    const value = JSON.parse(JSON.stringify(seen)) as Record<string, unknown>;
    change(value);
    assert.throws(() => speakerObservations(value), text);
  }
  const linked = sealed(t, (record) => { record.captionPhrases = []; });
  copyFileSync(linked.file, `${linked.file}.TEST-copy`); unlinkSync(linked.file); symlinkSync(`${linked.file}.TEST-copy`, linked.file);
  assert.throws(() => assertNativeSharedEvidence({ ...plan(), sharedEvidence: linked.binding }), /is not a regular file of at most 16 MiB/u);
  const twice = sealed(t, (record) => { record.captionPhrases = []; record.sources = [{ id: "TEST-raw-1", sourceSha256: SOURCE },
    { id: "TEST-raw-1b", sourceSha256: SOURCE }]; });
  assert.throws(() => assertNativeSharedEvidence({ ...plan(), sharedEvidence: twice.binding }), /shared evidence describes sources/u);
  const phrase = { source: "TEST-raw-1", sourceWordIndexes: [1005, 1006] as [number, number], display: "Butter Cuts", decidedBy: "operator" as const };
  const swapped = plan().canvas;
  [swapped.occurrences[6][2], swapped.occurrences[7][2]] = [1007, 1006];
  assert.equal(sealedPhraseStatus({ ...swapped, captionProtectedPhrases: [[5, 6]] }, phrase), "dropped", "kept but not adjacent");
  assert.equal(sealedPhraseStatus({ ...plan().canvas, captionProtectedPhrases: [[5, 6]] }, phrase), "kept");
});

test("the refusal names the first blocking code and lists every blocking finding", () => {
  const input = plan(), speakers = facts([interval(100, 107, "left")]);
  assert.throws(() => assertNativeSpeakerPicture(input, speakers, observations(both)), (error: unknown) => error instanceof NativeCheckError
    && error.code === "speaker-facts-missing" && error.message.startsWith("[speaker-facts-missing] Speaker picture contradicts the sealed speaker facts: "
      + "speaker-facts-missing frames 210-299: retained source words 1014-1019") && error.message.includes("; speaker-not-in-picture frames 0-209: "));
});

/** Seal a TEST record and its observations under a temporary folder and answer the engine check with them. */
function sealed(t: TestContext, change: (record: Record<string, unknown>) => void = () => {}, seen = observations(both)) {
  const directory = realpathSync(mkdtempSync(path.join(tmpdir(), "TEST-speaker-picture-")));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const write = (file: string, value: unknown) => { mkdirSync(path.dirname(file), { recursive: true }); writeFileSync(file, JSON.stringify(value));
    return createHash("sha256").update(JSON.stringify(value)).digest("hex"); };
  const resultFile = path.join(directory, "inspection", "result.json"), reference = { path: resultFile, sha256: write(resultFile, seen),
    owner: path.join(directory, "inspection", "inspection.render.json"), ownerSha256: "e".repeat(64) };
  const record: Record<string, unknown> = { kind: "sniper-shared-source-evidence", schemaVersion: 2, sources: [{ id: "TEST-raw-1", sourceSha256: SOURCE }],
    speakers: { listening: false, people: regions(), intervals: [interval(100, 110, "right")] },
    captionPhrases: [{ source: "TEST-raw-1", sourceWordIndexes: [1005, 1006], display: "Butter Cuts", decidedBy: "operator" }],
    coverage: { batch: "TEST-batch", clips: [CLIP], observations: { reference, faceCoverage: [] } } };
  change(record);
  const file = path.join(directory, "shared-evidence-v3.json"), binding = { path: file, sha256: write(file, record), contentSha256: "9".repeat(64), version: 3 };
  t.mock.method(evidenceCheck, "run", () => ({ status: "shared-evidence-current", ...binding }));
  return { binding, file, resultFile };
}

test("a bound record is re-checked, read at the checked bytes and its protected phrases enforced", (t) => {
  const kept = { ...plan(), canvas: { ...plan().canvas, captionProtectedPhrases: [[5, 6]], captionGroups: [[0], [1], [2], [3], [4], [5, 6],
    ...Array.from({ length: 13 }, (_, k) => [k + 7])] } } as NativeShortProjectInput;
  const { binding } = sealed(t);
  assert.doesNotThrow(() => assertNativeSharedEvidence({ ...kept, sharedEvidence: binding }));
  assert.throws(() => assertNativeSharedEvidence({ ...plan(), sharedEvidence: binding }), (error: unknown) => error instanceof NativeCheckError
    && error.message === "[protected-phrase-dropped] Plan drops protected caption phrase 'Butter Cuts' (source words 1005-1006) sealed in shared evidence v3");
  const longer = { ...kept, canvas: { ...kept.canvas, captionProtectedPhrases: [[5, 6, 7]], captionGroups: [[0], [1], [2], [3], [4], [5, 6, 7],
    ...Array.from({ length: 12 }, (_, k) => [k + 8])] } } as NativeShortProjectInput;
  assert.throws(() => assertNativeSharedEvidence({ ...longer, sharedEvidence: binding }), /protected-phrase-dropped/u, "a longer entry is not the phrase");
  const partly = sealed(t, (record) => { (record.captionPhrases as Array<{ sourceWordIndexes: number[] }>)[0].sourceWordIndexes = [1018, 1021]; });
  assert.throws(() => assertNativeSharedEvidence({ ...plan(), sharedEvidence: partly.binding }), (error: unknown) => error instanceof NativeCheckError
    && error.message === "[protected-phrase-partly-retained] protected phrase 'Butter Cuts' is only partly retained (source words 1018-1021)");
  const elsewhere = sealed(t, (record) => { record.captionPhrases = [{ source: "TEST-raw-2", sourceWordIndexes: [1005, 1006], display: "Other",
    decidedBy: "operator" }, { source: "TEST-raw-1", sourceWordIndexes: [2000, 2001], display: "Unkept", decidedBy: "operator" }]; });
  assert.doesNotThrow(() => assertNativeSharedEvidence({ ...plan(), sharedEvidence: elsewhere.binding }), "another source, or no word kept (E-C6)");
  writeFileSync(elsewhere.file, "{}");
  assert.throws(() => assertNativeSharedEvidence({ ...plan(), sharedEvidence: elsewhere.binding }), /Shared evidence .* differs from its recorded sha256/u);
});

test("an absent, foreign, uncovered or stale binding is never a pass", (t) => {
  t.mock.method(evidenceCheck, "run", () => { throw new Error("TEST the check must not run"); });
  assert.doesNotThrow(() => assertNativeSharedEvidence(plan()), "a plan without sharedEvidence builds as before");
  assert.deepEqual(nativeSharedEvidenceMeasure(plan()), { speakerPicture: null, protectedPhrases: null });
  assert.throws(() => assertNativeSharedEvidence(plan([RIGHT], [])), (error: unknown) => error instanceof NativeCheckError
    && error.code === "shared-evidence-unbound", "decisions without a binding (X229)");
  const v1 = sealed(t, (record) => { record.schemaVersion = 1; delete record.coverage; delete record.captionPhrases; });
  assert.throws(() => assertNativeSharedEvidence({ ...plan(), sharedEvidence: v1.binding }), (error: unknown) => error instanceof NativeCheckError
    && error.code === "speaker-facts-missing" && /v3 \(schema 1\) seals no speaker coverage/u.test(error.message));
  const foreign = sealed(t, (record) => { record.sources = [{ id: "TEST-raw-2", sourceSha256: "f".repeat(64) }]; });
  assert.throws(() => assertNativeSharedEvidence({ ...plan(), sharedEvidence: foreign.binding }),
    new RegExp(`shared evidence describes sources \\["${"f".repeat(64)}"\\], not this plan's source ${SOURCE}`, "u"));
  const moved = sealed(t);
  t.mock.method(evidenceCheck, "run", () => ({ status: "shared-evidence-current", ...moved.binding, sha256: "0".repeat(64) }));
  assert.throws(() => assertNativeSharedEvidence({ ...plan(), sharedEvidence: moved.binding }), (error: unknown) => error instanceof NativeCheckError
    && error.code === "stale-evidence" && /no longer current/u.test(error.message));
  const seen = sealed(t, (record) => { record.captionPhrases = []; });
  writeFileSync(seen.resultFile, "{}");
  assert.throws(() => assertNativeSharedEvidence({ ...plan(), sharedEvidence: seen.binding }), /Speaker observations .* differs from its recorded sha256/u);
});

test("measure lists findings without throwing, and a probable speaker alone is an open draft finding", (t) => {
  const { binding } = sealed(t, (record) => { (record.speakers as { intervals: unknown[] }).intervals = [interval(100, 105, "left", { certainty: "probable" }),
    interval(105, 110, "right", { certainty: "probable" })]; record.captionPhrases = []; });
  const measured = nativeSharedEvidenceMeasure({ ...plan(), sharedEvidence: binding });
  assert.deepEqual(measured.speakerPicture!.map((row) => [row.code, row.blocking]),
    [["speaker-not-in-picture", true], ["speaker-attribution-probable", false]]);
  assert.deepEqual(measured.protectedPhrases, []);
  assert.throws(() => assertNativeSharedEvidence({ ...plan(), sharedEvidence: binding }), /speaker-not-in-picture frames 0-149/u);
  const open = nativeSpeakerAttributionFindings({ ...plan(), sharedEvidence: binding });
  assert.deepEqual(open.map((row) => [row.code, row.source]), [["SPEAKER-ATTRIBUTION-PROBABLE", "shared-evidence"]]);
  assert.match(open[0].message, /^frames 150-299: probable speaker right is shown alone at \d+ sampled frame/u);
  assert.deepEqual(nativeSpeakerAttributionFindings(plan()), []);
});
