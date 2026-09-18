/** Synthetic receipt admission only; no test fixture claims actual independent creative review. */
import assert from "node:assert/strict";
import { existsSync, linkSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, truncateSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { test, type TestContext } from "node:test";
import { canonicalJson, canonicalJsonSha256, fileSha256 } from "../auto-edit-hash";
import { assertNativeShortPrebuildReview, nativeShortPrebuildPlanHash, type NativePrebuildReview } from "../native-short-prebuild-review";
import { readNativeShortProject, writeNativeShortProject, type NativeShortProjectInput } from "../native-short-project";
import { executeNativeShortCommand } from "../../../../scripts/producer/native-short";
import { nativeShortFixture } from "./_native-short-project-fixture";

function fixture(t: TestContext) {
  const directory = realpathSync(mkdtempSync(path.join(tmpdir(), "TEST-prebuild-review-")));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const input = nativeShortFixture(directory), destination = path.join(directory, "project");
  return { directory, input, destination };
}

function reviseReceipt(input: NativeShortProjectInput, change: (review: NativePrebuildReview) => void): void {
  const file = input.prebuildReview!.path, review = JSON.parse(readFileSync(file, "utf8"));
  change(review); writeFileSync(file, canonicalJson(review));
  input.prebuildReview!.sha256 = fileSha256(file)!;
}

test("missing review rejects before HTML, prepared media, destination creation and CLI preparation", async t => {
  const f = fixture(t); delete f.input.prebuildReview;
  f.input.extension = { markup: "<script>TEST must never assemble</script>", css: "", motion: "" };
  f.input.preparedSources = { path: path.join(f.directory, "must-not-read.json"), sha256: "a".repeat(64) };
  assert.throws(() => writeNativeShortProject(f.input, f.destination), /separate current independent full-plan/);
  assert.equal(existsSync(f.destination), false);
  const file = path.join(f.directory, "plan.json"); writeFileSync(file, canonicalJson(f.input));
  await assert.rejects(executeNativeShortCommand(["build", file, f.destination]), /separate current independent full-plan/);
  assert.equal(existsSync(`${f.destination}.sources`), false);
  await assert.rejects(executeNativeShortCommand(["prepare-media", file, f.destination]), /unsupported script/);
  assert.equal(existsSync(f.destination), false);
});

test("asset, cue, crop, transition, scene, audio and expectation revisions stale the review before staging", t => {
  const f = fixture(t);
  const changes: Array<(input: NativeShortProjectInput) => void> = [
    input => { input.assets.reverse(); },
    input => { input.assets[0].sha256 = "a".repeat(64); },
    input => { input.assets[0].path = "/TEST/source-that-must-not-be-read.mp4"; },
    input => { input.canvas.occurrences[0][5] = "Changed"; },
    input => { input.canvas.pictureViews[0].crop[0] += 1; },
    input => { input.extension = { markup: "", css: "", motion: 'tl.to("#source-0-0",{opacity:0},1);' }; },
    input => { input.strategy.scenes[0].exitReason = "TEST changed transition motivation"; },
    input => { input.audioFinishing = { schemaVersion: 1, rationale: "TEST changed audio", audioGain: [{ outStart: 0, outEnd: 2, dB: -1 }] }; },
    input => { input.expectations = [{ frame: 1, id: "source-0-0", property: "opacity", equals: "1" }]; },
  ];
  for (const change of changes) {
    const changed = structuredClone(f.input); change(changed);
    assert.throws(() => writeNativeShortProject(changed, f.destination), /prebuild review is stale/);
    assert.equal(existsSync(f.destination), false);
  }
});

test("receipt requires full-plan assessments, separate reviewer provenance and existing plan/pass semantics", t => {
  const mutations: Array<(review: NativePrebuildReview) => void> = [
    review => { review.scope = "director-opening" as NativePrebuildReview["scope"]; },
    review => { delete (review.coverage as Partial<NativePrebuildReview["coverage"]>).feasibility; },
    review => { review.reviewer.sessionId = review.reviewer.plannerSessionId; },
    review => { Object.assign(review.reviewer, { independent: false }); },
    review => { review.review.stage = "cut"; },
    review => { review.review.verdict = "revise"; review.review.materialIssues = [{ code: "TEST_ISSUE", severity: "major",
      lane: "plan", message: "TEST unresolved issue", evidence: ["TEST synthetic"], requiredAction: "TEST revise" }]; },
    review => { Object.assign(review, { approvalBypass: true }); },
  ];
  for (const change of mutations) {
    const f = fixture(t); reviseReceipt(f.input, change);
    assert.throws(() => writeNativeShortProject(f.input, f.destination));
    assert.equal(existsSync(f.destination), false);
  }
});

test("a recorded pass with minor findings publishes its receipt and cold reads without human approval", t => {
  const f = fixture(t);
  reviseReceipt(f.input, review => { review.review.findings.push({ code: "TEST_MINOR", severity: "minor", lane: "plan",
    message: "TEST optional improvement", evidence: ["TEST synthetic evidence"] }); });
  const built = writeNativeShortProject(f.input, f.destination);
  assert.deepEqual(readNativeShortProject(built.directory), f.input);
  assert.equal(built.manifest.humanApproved, false);
  assert.equal(built.manifest.prebuildReview.independence, "reviewer-declared-not-authenticated");
  assert.ok(built.manifest.files.some(row => row.file === "PREBUILD-REVIEW.json"));
});

test("receipt and evidence bytes remain required after review and publication", t => {
  const f = fixture(t), review = assertNativeShortPrebuildReview(f.input);
  writeNativeShortProject(f.input, f.destination);
  writeFileSync(review.evidence[0].path, "TEST changed reviewer evidence");
  assert.throws(() => readNativeShortProject(f.destination), /review evidence changed/);
  assert.throws(() => writeNativeShortProject(f.input, path.join(f.directory, "changed")), /review evidence changed/);
  writeFileSync(f.input.prebuildReview!.path, "{}");
  assert.throws(() => assertNativeShortPrebuildReview(f.input), /review receipt changed/);
});

test("rehashing a substituted sidecar or dropping its manifest entry cannot fabricate approval", t => {
  const f = fixture(t); writeNativeShortProject(f.input, f.destination);
  const manifestFile = path.join(f.destination, "PROJECT-MANIFEST.json"), sidecar = path.join(f.destination, "PREBUILD-REVIEW.json");
  const manifest = JSON.parse(readFileSync(manifestFile, "utf8"));
  const receipt = JSON.parse(readFileSync(sidecar, "utf8")); receipt.reviewer.identity = "TEST substituted critic";
  writeFileSync(sidecar, canonicalJson(receipt));
  manifest.files.find((row: { file: string }) => row.file === "PREBUILD-REVIEW.json").sha256 = fileSha256(sidecar);
  writeFileSync(manifestFile, canonicalJson(manifest));
  assert.throws(() => readNativeShortProject(f.destination), /review publication differs/);
  manifest.files = manifest.files.filter((row: { file: string }) => row.file !== "PREBUILD-REVIEW.json");
  writeFileSync(manifestFile, canonicalJson(manifest));
  assert.throws(() => readNativeShortProject(f.destination), /omits or duplicates/);
});

test("historical v3 without a review cold reads as unreviewed and cannot be rebuilt", async t => {
  const f = fixture(t); writeNativeShortProject(f.input, f.destination);
  const file = path.join(f.destination, "SHORT-PROJECT.json"), manifestFile = path.join(f.destination, "PROJECT-MANIFEST.json");
  const manifest = JSON.parse(readFileSync(manifestFile, "utf8"));
  delete f.input.prebuildReview; delete manifest.prebuildReview;
  writeFileSync(file, canonicalJson(f.input)); rmSync(path.join(f.destination, "PREBUILD-REVIEW.json"));
  manifest.projectHash = canonicalJsonSha256(f.input);
  manifest.files = manifest.files.filter((row: { file: string }) => row.file !== "PREBUILD-REVIEW.json")
    .map((row: { file: string }) => ({ ...row, sha256: fileSha256(path.join(f.destination, row.file)) }));
  writeFileSync(manifestFile, canonicalJson(manifest));
  const restored = readNativeShortProject(f.destination); assert.equal(restored.prebuildReview, undefined);
  const checked = await executeNativeShortCommand(["check", f.destination]);
  assert.equal("prebuildReview" in checked && checked.prebuildReview, "legacy-unreviewed");
  await assert.rejects(executeNativeShortCommand(["check-export", f.destination]), /requires.*prebuild review/);
  assert.throws(() => writeNativeShortProject(restored, path.join(f.directory, "new")), /requires.*prebuild review/);
});

test("Long export uses the same complete independent review semantics and exact project digest", async t => {
  const f = fixture(t), hash = "a".repeat(64);
  reviseReceipt(f.input, review => { review.scope = "native-long-full-project"; review.planHash = hash; });
  const file = f.input.prebuildReview!.path;
  const result = await executeNativeShortCommand(["check-long-review", file, hash]);
  assert.equal("scope" in result && result.scope, "native-long-full-project");
  await assert.rejects(executeNativeShortCommand(["check-long-review", file, "b".repeat(64)]), /stale/);
  reviseReceipt(f.input, review => { review.reviewer.sessionId = review.reviewer.plannerSessionId; });
  await assert.rejects(executeNativeShortCommand(["check-long-review", file, hash]), /independent/);
});

test("only generated transport and review reference are normalized; pinned request remains authored", t => {
  const f = fixture(t), original = nativeShortPrebuildPlanHash(f.input), changed = structuredClone(f.input);
  changed.preparedSources = { path: "/TEST/prepared.json", sha256: "a".repeat(64) };
  changed.guidedBinding = {} as NonNullable<NativeShortProjectInput["guidedBinding"]>;
  delete changed.prebuildReview;
  assert.equal(nativeShortPrebuildPlanHash(changed), original);
  changed.requestPacket = { path: "/TEST/request.json", sha256: "b".repeat(64) };
  assert.notEqual(nativeShortPrebuildPlanHash(changed), original);
});

test("linked, oversized and duplicate review evidence cannot enter a receipt", t => {
  for (const kind of ["symlink", "hardlink", "oversized", "duplicate"] as const) {
    const f = fixture(t), review = assertNativeShortPrebuildReview(f.input), file = review.evidence[0].path;
    const alias = path.join(f.directory, "alias-evidence.txt");
    if (kind === "symlink") symlinkSync(file, alias);
    if (kind === "hardlink") linkSync(file, alias);
    if (kind === "oversized") truncateSync(file, 256 * 1024 ** 2 + 1);
    reviseReceipt(f.input, receipt => {
      if (kind === "symlink" || kind === "hardlink") receipt.evidence[0].path = alias;
      if (kind === "duplicate") receipt.evidence.push({ ...receipt.evidence[0] });
    });
    assert.throws(() => assertNativeShortPrebuildReview(f.input));
    assert.equal(existsSync(f.destination), false);
  }
});
