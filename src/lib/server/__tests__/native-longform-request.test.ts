/** Local long-form strategy handoff with synthetic source bytes; no playback claim. */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { prepareNativeLongformRequest, checkNativeLongformRequest } from "../native-longform-request";
import { executeNativeShortCommand } from "../../../../scripts/producer/native-short";
import { longformInputPin, readLongformPacket, writeLongformPacket } from "../longform-strategy-packet";
import { longformReferenceInputs } from "../longform-reference-inputs";
import { loadReferenceStrategyLibrary } from "../reference-strategy-library";
import { LONGFORM_LIBRARY } from "../reference-library-paths";
import { pythonInterpreter, SCRIPTS_DIR } from "@/app/api/_lib/spawn-python";

function fixture() {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-longform-request-")));
  const producerDir = path.join(directory, "producer"), source = path.join(directory, "source");
  mkdirSync(producerDir); mkdirSync(source); mkdirSync(path.join(source, ".sniper-source-sets"));
  const video = path.join(source, "test.mp4"), transcript = path.join(source, "transcript.json");
  writeFileSync(video, "TEST ONLY inert bytes; 15-minute metadata is not real footage");
  writeFileSync(transcript, JSON.stringify({ words: [{ word: "Opening", start: 0, end: 1 }, { word: "ending", start: 899, end: 900 }] }));
  const receipt = path.join(source, "receipt.json"); writeFileSync(receipt, JSON.stringify({ test: "synthetic admission" }));
  const pin = longformInputPin(receipt), receiptPath = `.sniper-source-sets/${pin.sha256}.json`;
  writeFileSync(path.join(source, receiptPath), readFileSync(receipt));
  const intent = { mode: "longform", scope: "produced", lanes: { graphics: "off" }, brief: "A restrained vlog with real actions." };
  writeFileSync(path.join(directory, "project.json"), JSON.stringify({ origin: "raw", history: [], intent }));
  const manifest = { sources: [{ id: "test", path: video, sourceSha256: longformInputPin(video).sha256,
    duration: 900, resolution: [1920, 1080], fps: 30, transcriptPath: "transcript.json" }], broll: [], music: [],
    sourceSetAdmission: { schemaVersion: 1, receiptPath, receiptSha256: pin.sha256, sourceSetDigest: "a".repeat(64), entryCount: 1 } };
  writeFileSync(path.join(source, "asset_manifest.json"), JSON.stringify(manifest));
  return { directory, producerDir, source, video, transcript, intent,
    cleanup: () => rmSync(directory, { recursive: true, force: true }) };
}

test("15-minute long-form handoff reuses the complete library, catalog and original intent", async () => {
  const f = fixture();
  try {
    const result = await executeNativeShortCommand(["prepare-longform", f.producerDir]);
    assert.ok("directory" in result);
    const directory = String(result.directory), packet = readLongformPacket(directory);
    assert.deepEqual(packet.target, { mode: "longform", aspect: "16:9", width: 1920, height: 1080 });
    assert.deepEqual(packet.intent, f.intent);
    const library = JSON.parse(readFileSync(path.join(directory, "REFERENCE-LIBRARY.json"), "utf8"));
    const expected = loadReferenceStrategyLibrary(process.cwd());
    assert.equal(library.total, expected.index.total);
    assert.ok(library.references.some((row: { id: string }) => row.id === "A01"));
    assert.ok(library.references.some((row: { id: string }) => row.id === "CR07"));
    assert.ok(library.references.some((row: { id: string }) => row.id === "N27"));
    assert.ok(library.references.some((row: { id: string; sourceAspect: string }) => row.id === "LF01" && row.sourceAspect === "16:9"));
    const catalog = JSON.parse(readFileSync(path.join(directory, "CATALOG-INDEX.json"), "utf8"));
    assert.equal(catalog.total, catalog.items.length); assert.equal(catalog.limited, false);
    assert.ok(catalog.items.length > 100);
    assert.ok(catalog.items.every((row: { executionApproved: boolean }) => row.executionApproved === false));
    assert.equal(checkNativeLongformRequest(directory).renderApproved, false);
    assert.deepEqual(prepareNativeLongformRequest(f.producerDir, process.cwd()), result);
    const brief = readFileSync(path.join(directory, "AGENT-BRIEF.md"), "utf8");
    assert.match(brief, /entire proposed output/); assert.match(brief, /experimental library/);
    assert.match(brief, /preserving callbacks/); assert.match(brief, /Portrait references/);
    assert.match(brief, /lane ownership/); assert.match(brief, /existing keyframes/);
    assert.match(brief, /opening its own promise/); assert.match(brief, /screen-share-led/);
    writeFileSync(f.transcript, "changed words");
    assert.throws(() => checkNativeLongformRequest(directory), /input changed/);
  } finally { f.cleanup(); }
});

test("long-form mode is explicit and intent changes cannot reuse an old request", () => {
  const f = fixture();
  try {
    const result = prepareNativeLongformRequest(f.producerDir, process.cwd());
    writeFileSync(path.join(f.directory, "project.json"), JSON.stringify({ origin: "raw", intent: { ...f.intent, mode: "short" } }));
    assert.throws(() => checkNativeLongformRequest(result.directory), /intent changed/);
    assert.throws(() => prepareNativeLongformRequest(f.producerDir, process.cwd()), /requires stored longform/);
  } finally { f.cleanup(); }
});

test("saved strategy documents cannot be edited under their old request identity", () => {
  const f = fixture();
  try {
    const result = prepareNativeLongformRequest(f.producerDir, process.cwd());
    writeFileSync(path.join(result.directory, "CATALOG-INDEX.json"), "{}");
    assert.throws(() => readLongformPacket(result.directory), /document changed/);
    assert.throws(() => prepareNativeLongformRequest(f.producerDir, process.cwd()), /document changed/);
  } finally { f.cleanup(); }
});

test("a newly added reference invalidates the previous complete-library packet", () => {
  const f = fixture(), repo = path.join(f.directory, "library-repo");
  try {
    for (const pin of loadReferenceStrategyLibrary(process.cwd()).inputs) {
      const destination = path.join(repo, path.relative(process.cwd(), pin.path));
      mkdirSync(path.dirname(destination), { recursive: true }); cpSync(pin.path, destination);
    }
    const prepared = prepareNativeLongformRequest(f.producerDir, repo);
    const manifest = path.join(repo, LONGFORM_LIBRARY, "manifest.json");
    const original = readFileSync(manifest, "utf8");
    const changed = JSON.parse(original);
    changed.cases.push({ id: "LF02", case_path: path.join(LONGFORM_LIBRARY, "cases/LF02.json") });
    writeFileSync(path.join(path.dirname(manifest), "cases/LF02.json"), JSON.stringify({ id: "LF02", title: "TEST additional research", beats: [] }));
    writeFileSync(manifest, JSON.stringify(changed));
    assert.throws(() => checkNativeLongformRequest(prepared.directory), /input changed|library changed/);
  } finally { f.cleanup(); }
});

function selectedReference(f: ReturnType<typeof fixture>) {
  const deepStudyPath = path.join(f.directory, "deep_study.json"), profilePath = path.join(f.directory, "style_profile.json");
  const events = Array.from({ length: 1500 }, (_, index) => ({ id: `event-${index}`, t: index * 0.6, type: "cut" }));
  writeFileSync(deepStudyPath, JSON.stringify({ video: f.video, source: { durationS: 900, width: 1920, height: 1080 },
    params: { fps: 30 }, signals: { d: [1, 2, 3] }, events, unclassifiedRuns: 2, text: { graphics: [] } }));
  writeFileSync(profilePath, JSON.stringify({ referenceId: "test-ref", source: { video: f.video, sha256: longformInputPin(f.video).sha256 } }));
  writeFileSync(path.join(f.directory, "reference.json"), JSON.stringify({ schemaVersion: 1,
    referenceId: "test-ref", mode: "longform", strategy: "mimic", targetStyle: null,
    candidateStyleName: null, decidedAt: "2026-09-16T00:00:00.000Z" }));
  return { id: "test-ref", title: "TEST full reference", mode: "longform" as const,
    dir: f.directory, profilePath, deepStudyPath, representativeFrames: [] };
}

test("the selected 15-minute study keeps every event, unresolved classification and evidence limit", () => {
  const f = fixture();
  try {
    const study = selectedReference(f), result = longformReferenceInputs(study);
    const saved = JSON.parse(result.files["SELECTED-REFERENCE-STUDY.json"]);
    assert.equal(saved.events.length, 1500); assert.equal(saved.events.at(-1).id, "event-1499");
    assert.equal(saved.signals, undefined); assert.equal(saved.unclassifiedRuns, 2);
    assert.equal(result.selected?.eventsTruncated, false);
    assert.equal(result.selected?.editorialStudy, "whole-video-editorial-study-required");
    assert.equal(result.selected?.verifiedMimicQualified, false);
    const decision = path.join(f.directory, "reference.json"), original = readFileSync(decision, "utf8");
    writeFileSync(decision, original.replace('"mode":"longform"', '"mode":"short"'));
    assert.throws(() => longformReferenceInputs(study), /decision changed/);
    writeFileSync(decision, original);
    writeFileSync(path.join(f.directory, "reference_style_pack.json"), JSON.stringify({ referenceId: "test-ref", provenance: { deepStudyHash: "0".repeat(64) } }));
    assert.throws(() => longformReferenceInputs(study), /stale/);
    rmSync(path.join(f.directory, "reference_style_pack.json"));
    writeFileSync(f.video, "changed reference bytes");
    assert.throws(() => longformReferenceInputs(study), /video changed/);
  } finally { f.cleanup(); }
});

function saveTestBinding(f: ReturnType<typeof fixture>, study: ReturnType<typeof selectedReference>) {
  const plan = path.join(f.directory, "plan.md"), request = path.join(f.directory, "request.json");
  const map = path.join(f.directory, "map.json"), output = path.join(f.directory, "reference_catalog_matches.json");
  writeFileSync(plan, "TEST ONLY synthetic inspection decisions for plumbing tests; no visual qualification");
  writeFileSync(request, JSON.stringify({ scope: "reference-match", format: "short", project: path.join(f.directory, "original-project"),
    references: [{ id: study.id, ...longformInputPin(study.profilePath) }], shotPlan: longformInputPin(plan),
    shots: [{ id: "shot-test", referenceId: study.id, referenceBeat: "test-beat", cue: "test cue", visualNeed: "TEST result",
      requiredBehavior: "TEST reveal count", query: "count up" }] }));
  const cli = path.join(SCRIPTS_DIR, "producer/graphics/reference_reuse_cli.py");
  execFileSync(pythonInterpreter(), [cli, "prepare", request, "--output", map]);
  const value = JSON.parse(readFileSync(map, "utf8")), shot = value.shots[0];
  const ref = shot.candidateRefs.find((ref: string) => value.candidates[ref].source.exists);
  assert.ok(ref);
  shot.inspections = [{ ref, candidateSha256: value.candidates[ref].sha256,
    observation: "TEST synthetic inspection; not a visual quality claim", fit: "usable", limitations: "TEST ONLY" }];
  shot.decision = { route: "reuse", reason: "TEST structural check", pieces: [{ ref, role: "TEST count", changes: "" }],
    prerequisites: [], execution: { adapter: "TEST no actual execution", status: "available" } };
  writeFileSync(map, JSON.stringify(value));
  execFileSync(pythonInterpreter(), [cli, "save-study", map, "--output", output]);
  return output;
}

test("saved catalog matches from a Short study reach long-form planning with original evidence", () => {
  const f = fixture();
  try {
    const study = selectedReference(f), binding = saveTestBinding(f, study);
    const result = longformReferenceInputs(study);
    assert.equal(result.selected?.catalogBindingsAvailable, true);
    const matches = JSON.parse(result.files["SELECTED-REFERENCE-MATCHES.json"]);
    assert.equal(matches.sourceFormat, "short"); assert.equal(matches.renderApproved, false);
    assert.equal(matches.matches[0].decision.route, "reuse");
    assert.ok(result.pins.some(pin => pin.path === binding));
    writeFileSync(study.profilePath, `${readFileSync(study.profilePath, "utf8")}\n`);
    assert.throws(() => longformReferenceInputs(study), /do not bind this selected reference/);
  } finally { f.cleanup(); }
});

test("packet preparation rejects conflicting snapshots and symlinked output parents", () => {
  const f = fixture();
  try {
    const pin = longformInputPin(f.video);
    const input = { producerDir: f.producerDir, request: {}, files: { "TEST.md": "test" }, pins: [pin] };
    assert.throws(() => writeLongformPacket({ ...input, pins: [pin, { ...pin, sha256: "0".repeat(64) }] }), /Conflicting/);
    const external = path.join(f.directory, "external"); mkdirSync(external);
    symlinkSync(external, path.join(f.producerDir, "native-longform"));
    assert.throws(() => writeLongformPacket(input), /canonical/);
    assert.equal(existsSync(path.join(external, "requests")), false);
  } finally { f.cleanup(); }
});
