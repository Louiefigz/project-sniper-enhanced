import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { assembleNativeShortHtml, readNativeShortProject, writeNativeShortProject } from "../native-short-project";
import { nativeShortFixture, refreshNativePacingFixture } from "./_native-short-project-fixture";
import { canonicalJson, canonicalJsonSha256, fileSha256 } from "../auto-edit-hash";
import { nativeAssetUseRevisionHash } from "../native-short-asset-use";
import { nativeShortPacingReport } from "../native-short-pacing";
import { buildNativeShortProjectFiles } from "../guided-native-project";

function fixture() {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-short-project-")));
  return { directory, input: nativeShortFixture(directory), cleanup: () => rmSync(directory, { recursive: true, force: true }) };
}

test("guided adapter uses the same explicit canvas and rejects changed accepted speech", () => {
  const f = fixture();
  try {
    const canvas = f.input.canvas, accepted = { cutTrack: canvas.cuts.map(cut => ({ ...cut, sourceId: "test" })) };
    const candidate = { ...accepted, executionRoute: "native-short-v1", nativeDirection: {
      route: "native-short-v1", sourceCutHash: canonicalJsonSha256(accepted),
      frameRate: canvas.frameRate, totalFrames: canvas.totalFrames, segments: canvas.segments,
      occurrences: canvas.occurrences } };
    const visual = { candidateHash: canonicalJsonSha256(candidate), project: f.input };
    const media = [{ sourceId: "test", file: canvas.sourceFile, sha256: f.input.assets[0].sha256 }];
    const files = buildNativeShortProjectFiles(candidate, media, canvas.captionGroups, visual);
    assert.equal(files["index.html"], assembleNativeShortHtml(f.input));
    f.input.canvas.cuts[0].start = .1;
    assert.throws(() => buildNativeShortProjectFiles(candidate, media, canvas.captionGroups, visual), /changed accepted speech/);
  } finally { f.cleanup(); }
});

test("real writer and cold reader bind strategy, canonical hook, source bytes and shared canvas", () => {
  const f = fixture();
  try {
    const project = writeNativeShortProject(f.input, path.join(f.directory, "project"));
    assert.deepEqual(readNativeShortProject(project.directory), f.input);
    assert.equal(project.manifest.humanApproved, false);
    assert.match(readFileSync(path.join(project.directory, "index.html"), "utf8"), /native-title-card/);
    writeFileSync(path.join(project.directory, f.input.canvas.sourceFile), "changed staged source");
    assert.throws(() => readNativeShortProject(project.directory), /changed/);
  } finally { f.cleanup(); }
});

test("missing strategy files cannot be hidden by stripping the project manifest", () => {
  const f = fixture();
  try {
    const { directory } = writeNativeShortProject(f.input, path.join(f.directory, "project"));
    const file = path.join(directory, "PROJECT-MANIFEST.json"), manifest = JSON.parse(readFileSync(file, "utf8"));
    manifest.files = manifest.files.filter((row: { file: string }) => !row.file.endsWith(".mp4"));
    writeFileSync(file, JSON.stringify(manifest));
    assert.throws(() => readNativeShortProject(directory), /omits or duplicates/);
  } finally { f.cleanup(); }
});

test("canonical JSON key order cannot change executable motion on cold reconstruction", () => {
  const f = fixture();
  try {
    f.input.canvas.shapes = [{ id: "test-object", startFrame: 0, endFrame: 50,
      box: [20, 500, 100, 100], fill: "#ffffff", border: "#111111", borderWidth: 1, radius: 8 }];
    f.input.canvas.motion = [{ id: "test-object", startFrame: 5, durationFrames: 5,
      from: { y: 20, scale: .8, opacity: 0 }, to: { y: 0, scale: 1, opacity: 1 }, ease: "power2.out" }];
    refreshNativePacingFixture(f.input);
    assert.equal(assembleNativeShortHtml(f.input), assembleNativeShortHtml(JSON.parse(canonicalJson(f.input))));
    const { directory } = writeNativeShortProject(f.input, path.join(f.directory, "project"));
    assert.deepEqual(readNativeShortProject(directory), f.input);
  } finally { f.cleanup(); }
});

test("requested style, canonical title and source inspection cannot be silently substituted", () => {
  const f = fixture();
  try {
    const changed = structuredClone(f.input); changed.request = { selection: "requested", request: "Nate", supportingVideo: "source-first" };
    assert.throws(() => assembleNativeShortHtml(changed), /changed the requested/);
    changed.request = f.input.request; changed.strategy.supportingSearch.searchedSourceFiles = [];
    assert.throws(() => assembleNativeShortHtml(changed), /inspect the supplied source/);
    f.input.canvas.titleCard!.copy.text = "Invented new title";
    assert.throws(() => writeNativeShortProject(f.input, path.join(f.directory, "project")), /canonical selected template/);
  } finally { f.cleanup(); }
});

test("supporting video must execute the selected source and exact output range", () => {
  const f = fixture();
  try {
    f.input.extension = { css: "", motion: "", markup: `<video id="support" class="clip" src="${f.input.canvas.sourceFile}" data-start="0" data-duration="1" data-media-start="4" muted></video>` };
    f.input.strategy.supportingSearch.candidates = [{ assetFile: f.input.canvas.sourceFile, sourceStart: 4, sourceEnd: 5,
      observed: "TEST source action", role: "explanation", claimLimit: "TEST illustration only", selected: true,
      reason: "TEST concrete demonstration", visibleId: "support", startFrame: 0, endFrame: 25 }];
    refreshNativePacingFixture(f.input);
    assert.doesNotThrow(() => assembleNativeShortHtml(f.input));
    f.input.extension.markup = f.input.extension.markup.replace('data-duration="1"', '');
    assert.throws(() => assembleNativeShortHtml(f.input), /executable source\/window/);
  } finally { f.cleanup(); }
});

test("cold reader rejects rehashed asset-use findings and missing report manifests", () => {
  const f = fixture();
  try {
    const { directory } = writeNativeShortProject(f.input, path.join(f.directory, "project"));
    const reportFile = path.join(directory, "ASSET-USE-REPORT.json"), manifestFile = path.join(directory, "PROJECT-MANIFEST.json");
    const report = JSON.parse(readFileSync(reportFile, "utf8")), manifest = JSON.parse(readFileSync(manifestFile, "utf8"));
    assert.equal(report.semanticReview, "not-established-by-structural-checks");
    assert.ok(report.originEvidenceFiles.some((row: { path: string }) => row.path === f.input.assets[0].origin!.path));
    report.semanticReview = "fabricated-source-verification"; writeFileSync(reportFile, JSON.stringify(report));
    manifest.files.find((row: { file: string }) => row.file === "ASSET-USE-REPORT.json").sha256 = fileSha256(reportFile);
    writeFileSync(manifestFile, JSON.stringify(manifest));
    assert.throws(() => readNativeShortProject(directory), /asset-use report differs/);
    manifest.files = manifest.files.filter((row: { file: string }) => row.file !== "ASSET-USE-REPORT.json");
    writeFileSync(manifestFile, JSON.stringify(manifest));
    assert.throws(() => readNativeShortProject(directory), /omits or duplicates/);
  } finally { f.cleanup(); }
});

test("new writer and cold reader preserve immutable origin evidence instead of stripping it", () => {
  const f = fixture();
  try {
    const { directory } = writeNativeShortProject(f.input, path.join(f.directory, "project"));
    const stripped = structuredClone(f.input); delete stripped.assets[0].origin;
    stripped.strategy.assetUse!.revisionHash = nativeAssetUseRevisionHash(stripped);
    assert.throws(() => writeNativeShortProject(stripped, path.join(f.directory, "stripped")), /immutable origin/);
    assert.equal(existsSync(path.join(f.directory, "stripped")), false);
    writeFileSync(f.input.assets[0].origin!.path, "TEST mutated immutable acquisition evidence");
    assert.throws(() => readNativeShortProject(directory), /origin evidence.*changed/);
  } finally { f.cleanup(); }
});

/** Construct historical serialized fixtures; current writer never accepts a downgraded plan. */
function legacyFixture(directory: string, version: 1 | 2): void {
  const file = path.join(directory, "SHORT-PROJECT.json"), manifestFile = path.join(directory, "PROJECT-MANIFEST.json");
  const input = JSON.parse(readFileSync(file, "utf8")), manifest = JSON.parse(readFileSync(manifestFile, "utf8"));
  input.strategy.schemaVersion = version; delete input.strategy.assetUse;
  for (const asset of input.assets) delete asset.origin;
  if (version === 1) delete input.strategy.pacing;
  writeFileSync(file, canonicalJson(input));
  const removed = ["ASSET-USE-REPORT.json", ...(version === 1 ? ["PACING-REPORT.json"] : [])];
  for (const name of removed) rmSync(path.join(directory, name));
  if (version === 2) writeFileSync(path.join(directory, "PACING-REPORT.json"), canonicalJson(nativeShortPacingReport(input, assembleNativeShortHtml(input))));
  manifest.projectHash = canonicalJsonSha256(input);
  manifest.files = manifest.files.filter((row: { file: string }) => !removed.includes(row.file))
    .map((row: { file: string }) => ({ ...row, sha256: fileSha256(path.join(directory, row.file)) }));
  writeFileSync(manifestFile, canonicalJson(manifest));
}

test("v1 and v2 frozen projects cold-read unchanged while current writer requires v3", () => {
  const f = fixture();
  try {
    const html = assembleNativeShortHtml(f.input);
    for (const version of [1, 2] as const) {
      const { directory } = writeNativeShortProject(f.input, path.join(f.directory, `legacy-${version}`));
      legacyFixture(directory, version);
      const restored = readNativeShortProject(directory);
      assert.equal(restored.strategy.schemaVersion, version); assert.equal(restored.strategy.assetUse, undefined);
      assert.equal(assembleNativeShortHtml(restored), html);
      assert.throws(() => writeNativeShortProject(restored, path.join(f.directory, `new-${version}`)), /version 3/);
      assert.equal(existsSync(path.join(f.directory, `new-${version}`)), false);
    }
  } finally { f.cleanup(); }
});
