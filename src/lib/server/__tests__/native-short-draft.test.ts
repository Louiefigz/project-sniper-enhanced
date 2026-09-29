/** TEST-only review-draft construction/admission; no fixture here claims a real creative review. */
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { test, type TestContext } from "node:test";
import { canonicalJson, canonicalJsonSha256, fileSha256 } from "../auto-edit-hash";
import { nativeShortPrebuildPlanHash, type NativePrebuildReview } from "../native-short-prebuild-review";
import { readNativeShortProject, writeNativeShortProject, type NativeShortProjectInput } from "../native-short-project";
import { deriveNativeShortDraftAuthority, NATIVE_DRAFT_LABEL } from "../native-short-draft";
import { executeNativeShortCommand } from "../../../../scripts/producer/native-short";
import { nativeShortFixture, reviseNativePrebuildReviewFixture } from "./_native-short-project-fixture";

const ISSUE = { code: "TEST_OPEN_ISSUE", severity: "major" as const, lane: "plan",
  message: "TEST synthetic unresolved finding; not a real review", evidence: ["TEST synthetic evidence"],
  requiredAction: "TEST correct the synthetic issue" };

function fixture(t: TestContext) {
  const directory = realpathSync(mkdtempSync(path.join(tmpdir(), "TEST-native-draft-")));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  return { directory, input: nativeShortFixture(directory), destination: path.join(directory, "draft-project") };
}

function revise(input: NativeShortProjectInput, change: (review: NativePrebuildReview) => void): void {
  reviseNativePrebuildReviewFixture(input, change);
}

function withFindings(input: NativeShortProjectInput): NativeShortProjectInput {
  revise(input, review => { review.review.verdict = "revise"; review.review.materialIssues = [ISSUE];
    review.review.summary = "TEST synthetic revise verdict; no real reviewer inspected media"; });
  return input;
}

function planFile(f: ReturnType<typeof fixture>): string {
  const file = path.join(f.directory, "TEST-plan.json"); writeFileSync(file, canonicalJson(f.input)); return file;
}

function draftBuild(f: ReturnType<typeof fixture>) {
  return writeNativeShortProject({ ...f.input, draft: deriveNativeShortDraftAuthority(f.input) }, f.destination);
}

function rewriteManifest(directory: string, change: (manifest: Record<string, unknown>) => void): void {
  const file = path.join(directory, "PROJECT-MANIFEST.json"), manifest = JSON.parse(readFileSync(file, "utf8"));
  change(manifest); writeFileSync(file, canonicalJson(manifest));
}

test("recorded material findings build an explicit draft that every final reader and export check refuses", async t => {
  const f = fixture(t); withFindings(f.input);
  const file = planFile(f);
  await assert.rejects(executeNativeShortCommand(["build", file, f.destination]), /must pass with zero material issues/);
  assert.equal(existsSync(f.destination) || existsSync(`${f.destination}.sources`), false);
  const built = draftBuild(f);
  assert.equal(built.manifest.reviewState, "draft");
  assert.equal(built.manifest.prebuildReview.status, "recorded-independent-plan-findings-review-draft");
  assert.deepEqual(built.manifest.prebuildReview.materialIssueCodes, ["TEST_OPEN_ISSUE"]);
  assert.equal(built.manifest.humanApproved, false);
  const stored = JSON.parse(readFileSync(path.join(f.destination, "SHORT-PROJECT.json"), "utf8"));
  assert.deepEqual(stored.draft, { schemaVersion: 1, state: "review-findings", verdict: "revise", materialIssueCodes: ["TEST_OPEN_ISSUE"] });
  assert.ok(existsSync(path.join(f.destination, "PREBUILD-REVIEW.json")));
  assert.throws(() => readNativeShortProject(f.destination), /REVIEW DRAFT[\s\S]*refuse draft projects/);
  await assert.rejects(executeNativeShortCommand(["check", f.destination]), /refuse draft projects/);
  await assert.rejects(executeNativeShortCommand(["check-export", f.destination]), /refuse draft projects/);
  assert.equal(readNativeShortProject(f.destination, {}, undefined, "draft").draft?.state, "review-findings");
  const checked = await executeNativeShortCommand(["check-draft", f.destination]) as Record<string, unknown>;
  assert.equal(checked.reviewState, "draft"); assert.equal(checked.promotable, false);
  assert.equal(checked.finalEligible, false); assert.equal(checked.label, NATIVE_DRAFT_LABEL);
  assert.deepEqual((checked.openFindings as Array<{ code: string }>).map(row => row.code), ["TEST_OPEN_ISSUE"]);
});

test("an explicit pending review builds a draft; missing review never selects the legacy lane", async t => {
  const f = fixture(t); delete f.input.prebuildReview;
  const built = draftBuild(f);
  assert.equal(built.manifest.prebuildReview.status, "independent-plan-review-pending-review-draft");
  assert.equal(built.manifest.prebuildReview.planHash, nativeShortPrebuildPlanHash(f.input));
  assert.equal(existsSync(path.join(f.destination, "PREBUILD-REVIEW.json")), false);
  await assert.rejects(executeNativeShortCommand(["check", f.destination]), /independent plan review pending/);
  await assert.rejects(executeNativeShortCommand(["check-export", f.destination]), /refuse draft projects/);
  const checked = await executeNativeShortCommand(["check-draft", f.destination]) as Record<string, unknown>;
  assert.deepEqual(checked.draft, { schemaVersion: 1, state: "review-pending" });
  assert.deepEqual(checked.openFindings, []);
});

test("passing, stale, invalid or author-declared review state cannot build a draft", async t => {
  const pass = fixture(t);
  assert.throws(() => deriveNativeShortDraftAuthority(pass.input), /passes; use build/);
  await assert.rejects(executeNativeShortCommand(["build-draft", planFile(pass), pass.destination]), /passes; use build/);
  assert.equal(existsSync(`${pass.destination}.sources`), false);
  const stale = fixture(t); withFindings(stale.input); stale.input.canvas.occurrences[0][5] = "Changed";
  assert.throws(() => deriveNativeShortDraftAuthority(stale.input), /stale/);
  const dependent = fixture(t); withFindings(dependent.input);
  revise(dependent.input, review => { review.reviewer.sessionId = review.reviewer.plannerSessionId; });
  assert.throws(() => deriveNativeShortDraftAuthority(dependent.input), /independent/);
  const declared = fixture(t); withFindings(declared.input);
  const forged = { ...declared.input, draft: { schemaVersion: 1 as const, state: "review-pending" as const } };
  assert.throws(() => deriveNativeShortDraftAuthority(forged), /already declares draft authority/);
  assert.throws(() => writeNativeShortProject(forged, declared.destination), /differs from its recorded/);
  writeFileSync(path.join(declared.directory, "forged.json"), canonicalJson(forged));
  await assert.rejects(executeNativeShortCommand(["build", path.join(declared.directory, "forged.json"),
    declared.destination]), /cannot carry draft authority/);
  assert.equal(existsSync(declared.destination), false);
});

test("draft authority is excluded from the review hash but bound by the project hash and manifest", t => {
  const f = fixture(t); withFindings(f.input);
  const draft = deriveNativeShortDraftAuthority(f.input);
  assert.equal(nativeShortPrebuildPlanHash({ ...f.input, draft }), nativeShortPrebuildPlanHash(f.input));
  draftBuild(f);
  const inputFile = path.join(f.destination, "SHORT-PROJECT.json"), stored = JSON.parse(readFileSync(inputFile, "utf8"));
  delete stored.draft; writeFileSync(inputFile, canonicalJson(stored));
  rewriteManifest(f.destination, manifest => { manifest.projectHash = canonicalJsonSha256(stored);
    (manifest.files as Array<{ file: string; sha256: string }>).find(row => row.file === "SHORT-PROJECT.json")!.sha256 = fileSha256(inputFile)!; });
  assert.throws(() => readNativeShortProject(f.destination, {}, undefined, "draft"), /review state differs/);
  rewriteManifest(f.destination, manifest => { delete manifest.reviewState; });
  assert.throws(() => readNativeShortProject(f.destination), /review publication differs|must pass/);
});

test("a draft cannot relabel its verdict, drop its receipt or claim final eligibility", t => {
  const f = fixture(t); withFindings(f.input); draftBuild(f);
  const inputFile = path.join(f.destination, "SHORT-PROJECT.json"), stored = JSON.parse(readFileSync(inputFile, "utf8"));
  stored.draft.verdict = "block"; writeFileSync(inputFile, canonicalJson(stored));
  rewriteManifest(f.destination, manifest => { manifest.projectHash = canonicalJsonSha256(stored);
    (manifest.files as Array<{ file: string; sha256: string }>).find(row => row.file === "SHORT-PROJECT.json")!.sha256 = fileSha256(inputFile)!; });
  assert.throws(() => readNativeShortProject(f.destination, {}, undefined, "draft"), /differs from its recorded/);
  const g = fixture(t); withFindings(g.input); draftBuild(g);
  rewriteManifest(g.destination, manifest => { manifest.reviewState = "final"; });
  assert.throws(() => readNativeShortProject(g.destination, {}, undefined, "draft"), /unknown review state/);
  rewriteManifest(g.destination, manifest => { manifest.reviewState = "draft";
    (manifest.prebuildReview as Record<string, unknown>).finalEligible = true; });
  assert.throws(() => readNativeShortProject(g.destination, {}, undefined, "draft"), /draft review publication differs/);
  revise(g.input, review => { review.review.summary = "TEST changed after draft publication"; });
  assert.throws(() => readNativeShortProject(g.destination, {}, undefined, "draft"));
});

test("final-eligible projects are readable in draft mode; legacy unreviewed projects are not", async t => {
  const f = fixture(t), built = writeNativeShortProject(f.input, f.destination);
  assert.equal(built.manifest.reviewState, undefined);
  const checked = await executeNativeShortCommand(["check-draft", f.destination]) as Record<string, unknown>;
  assert.equal(checked.reviewState, "final-eligible"); assert.equal(checked.promotable, true);
  assert.equal(checked.label, null);
  const inputFile = path.join(f.destination, "SHORT-PROJECT.json"), stored = JSON.parse(readFileSync(inputFile, "utf8"));
  delete stored.prebuildReview; writeFileSync(inputFile, canonicalJson(stored));
  rmSync(path.join(f.destination, "PREBUILD-REVIEW.json"));
  rewriteManifest(f.destination, manifest => { delete manifest.prebuildReview; manifest.projectHash = canonicalJsonSha256(stored);
    manifest.files = (manifest.files as Array<{ file: string }>).filter(row => row.file !== "PREBUILD-REVIEW.json")
      .map(row => ({ ...row, sha256: fileSha256(path.join(f.destination, row.file)) })); });
  await assert.rejects(executeNativeShortCommand(["check-draft", f.destination]), /Legacy unreviewed/);
});
