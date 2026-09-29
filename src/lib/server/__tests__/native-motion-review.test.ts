/** Structural admission fixtures; typed inspection entries are TEST declarations and nobody played or heard anything. */
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { assertNativeMotionReviews } from "../native-motion-review";
import { fileSha256 } from "../auto-edit-hash";
import { NATIVE_PREBUILD_COVERAGE } from "../native-short-prebuild-review";
import { readInspection } from "../native-review-submission-shared";
import { typedRecordParts } from "./_native-review-fixture";

function fixture() {
  const root = mkdtempSync("/private/tmp/sniper-motion-review-"), file = path.join(root, "reviews.json");
  const packetFile = path.join(root, "packet.json"), evidence = path.join(root, "TEST-evidence.txt");
  writeFileSync(evidence, "TEST structural review only; nobody viewed these synthetic previews.");
  const units = Array.from({ length: 10 }, (_, index) => ({ id: `scene-${index}`, hash: String(index).repeat(64) }));
  const packet = { project: root, units };
  const write = (target: string, value: unknown) => writeFileSync(target, JSON.stringify(value));
  function review(name: string, selected: typeof units) {
    const preview = path.join(root, `${name}.json`);
    write(preview, { status: "native-motion-previews-complete", packet: { ...packet, units: structuredClone(units) } });
    return { reviewer: { identity: "TEST synthetic reviewer", sessionId: "TEST-review", plannerSessionId: "TEST-author", independent: true },
      coverage: Object.fromEntries(NATIVE_PREBUILD_COVERAGE.map(key => [key, "TEST synthetic assessment only"])),
      evidence: [{ path: evidence, sha256: fileSha256(evidence)! }],
      review: { schemaVersion: 1, stage: "plan", verdict: "pass", summary: "TEST structural judgment", materialIssues: [], findings: [] },
      units: Object.fromEntries(selected.map(unit => [unit.id, unit.hash])),
      preview: { path: preview, sha256: fileSha256(preview)! }, assessment: "TEST no playback occurred; validator fixture only" };
  }
  return { root, file, packetFile, packet, units, write, review,
    check: (rows: unknown[]) => { write(file, { schemaVersion: 1, reviews: rows }); write(packetFile, packet); return assertNativeMotionReviews(file, packetFile); },
    cleanup: () => rmSync(root, { recursive: true, force: true }) };
}

test("three changed native regions need fresh reviews while seven retain their exact evidence", () => {
  const f = fixture();
  try {
    const before = f.review("before", f.units);
    f.check([before]);
    for (const index of [2, 5, 8]) f.units[index].hash = "a".repeat(64);
    assert.throws(() => f.check([before]), /current independent review/);
    const fresh = f.review("after", f.units.filter((_, index) => [2, 5, 8].includes(index)));
    const admitted = f.check([before, fresh]);
    assert.equal(admitted.status, "recorded-independent-motion-pass");
    assert.deepEqual(admitted.inspection, { authenticity: "declared-not-authenticated", typedRows: 0, untypedRows: 2,
      testFixtureRows: 0, audioApprovedUnits: [] });
    writeFileSync(before.preview.path, "TEST changed old preview");
    assert.throws(() => f.check([before, fresh]), /changed|Unexpected token/);
  } finally { f.cleanup(); }
});

test("material findings, self review and mismatched preview units refuse full-picture admission", () => {
  const f = fixture();
  try {
    const row = f.review("current", f.units);
    row.review.verdict = "block";
    assert.throws(() => f.check([row]), /material/);
    row.review.verdict = "pass"; row.reviewer.sessionId = row.reviewer.plannerSessionId;
    assert.throws(() => f.check([row]), /independent/);
    row.reviewer.sessionId = "TEST-review"; row.units["scene-0"] = "b".repeat(64);
    assert.throws(() => f.check([row]), /current independent review/);
  } finally { f.cleanup(); }
});

/** A schema-2 (Short) preview with one clip and a typed row approving its playback. */
function typedShortRow(f: ReturnType<typeof fixture>, clip: Record<string, unknown>) {
  const media = path.join(f.root, "TEST-window.mp4");
  writeFileSync(media, "TEST window bytes; nobody played them");
  const window = { startFrame: 0, endFrameExclusive: 60, path: media, sha256: fileSha256(media)! };
  const row = f.review("ancestor", f.units), preview = path.join(f.root, "ancestor.json");
  f.write(preview, { status: "native-motion-previews-complete", clips: [window],
    packet: { ...clip, canvas: { frameRate: "30/1", totalFrames: 300 }, units: structuredClone(f.units) } });
  row.preview = { path: preview, sha256: fileSha256(preview)! };
  const inspection = { schemaVersion: 1, approves: ["picture", "motion"], entries: [{ kind: "motion-playback",
    artifact: { path: media, sha256: window.sha256 }, span: "whole", method: "TEST fixture: nothing was played" }] };
  const parts = typedRecordParts(f.root, "motion-critic", { reviewer: row.reviewer, verdict: "pass", inspection },
    { preview: row.preview });
  return { row, window, inspection, typed: { ...row, evidence: [...parts.evidence, ...row.evidence], inspection,
    submission: parts.submission, approvedContent: parts.approvedContent } };
}

test("schema-2 packets admit same-clip reviews across revision folders and reject another clip", () => {
  const f = fixture();
  try {
    const clip = { schemaVersion: 2, subject: { clip: "c".repeat(32) }, units: f.units };
    const { row: untyped, typed: row } = typedShortRow(f, clip);
    f.write(f.packetFile, clip);
    f.write(f.file, { schemaVersion: 1, reviews: [untyped] });
    assert.throws(() => assertNativeMotionReviews(f.file, f.packetFile),
      /needs a current independent review for scene-0 \(a historical review without typed inspection cannot establish motion playback\)/);
    f.write(f.file, { schemaVersion: 1, reviews: [row] });
    const admitted = assertNativeMotionReviews(f.file, f.packetFile);
    assert.equal(admitted.status, "recorded-independent-motion-pass");
    assert.deepEqual(admitted.inspection, { authenticity: "declared-not-authenticated", typedRows: 1, untypedRows: 0,
      testFixtureRows: 0, audioApprovedUnits: [] });
    f.write(f.packetFile, { ...clip, subject: { clip: "d".repeat(32) } });
    assert.throws(() => assertNativeMotionReviews(f.file, f.packetFile), /does not bind current preview regions/);
    f.write(f.packetFile, { ...clip, subject: { clip: "c".repeat(32), project: f.root } });
    assert.throws(() => assertNativeMotionReviews(f.file, f.packetFile), /subject/);
  } finally { f.cleanup(); }
});

test("gate readers re-check provenance: a hand-built typed row cannot claim more than its bound submission", () => {
  const f = fixture();
  try {
    const clip = { schemaVersion: 2, subject: { clip: "c".repeat(32) }, units: f.units };
    const { typed, window } = typedShortRow(f, clip);
    f.write(f.packetFile, clip);
    const refused = (row: unknown, pattern: RegExp) => {
      f.write(f.file, { schemaVersion: 1, reviews: [row] });
      assert.throws(() => assertNativeMotionReviews(f.file, f.packetFile), pattern);
    };
    refused({ ...typed, reviewer: { ...typed.reviewer, sessionId: "TEST-never-ran-the-helper" } }, /disagrees with the observations it binds/);
    const listening = { kind: "audio-listening", artifact: { path: window.path, sha256: window.sha256 }, span: "whole",
      method: "TEST claimed afterwards" };
    refused({ ...typed, inspection: { ...typed.inspection, approves: ["picture", "motion", "audio"],
      entries: [...typed.inspection.entries, listening] } }, /disagrees with the observations it binds/);
    refused({ ...typed, submission: { ...typed.submission, packetResolvedAt: new Date().toISOString() } },
      /disagrees with its bound role packet/);
    refused({ ...typed, submission: { ...typed.submission, submittedAt: new Date(Date.now() + 60_000).toISOString() } },
      /Timing inconsistency: the review submission time is in the future/);
    const early = new Date(Date.parse(typed.submission.packetResolvedAt) + 1000).toISOString();
    refused({ ...typed, submission: { ...typed.submission, submittedAt: early } }, /Implausible completion: the inspection claims 2\.0 s/);
    refused({ ...typed, submission: { ...typed.submission, rolePacket: { ...typed.submission.rolePacket, sha256: "e".repeat(64) } } },
      /names a role packet that its evidence does not bind/);
  } finally { f.cleanup(); }
});

test("a route-canary TEST declaration admits only its own TEST fixture project and is readable nowhere else", () => {
  const f = fixture();
  try {
    const clip = { schemaVersion: 2, subject: { clip: "c".repeat(32) }, units: f.units };
    const { row, inspection } = typedShortRow(f, clip), project = path.join(f.root, "projects", "good");
    const manifest = path.join(f.root, "FIXTURE.json");
    const writeManifest = (authority: boolean) => { f.write(manifest, { schemaVersion: 1, scope: "TEST-native-route-canary-fixture",
      productionAuthority: authority, variants: { good: { project } } }); return { path: manifest, sha256: fileSha256(manifest)! }; };
    f.write(path.join(f.root, "export-request.json"), { project });
    const declared = (binding: { path: string; sha256: string }, named = project) => ({ ...row, submission: null, approvedContent: null,
      inspection: { ...inspection, fixture: { scope: "TEST-native-route-canary-fixture", manifest: binding, project: named } } });
    f.write(f.packetFile, clip);
    f.write(f.file, { schemaVersion: 1, reviews: [declared(writeManifest(false))] });
    assert.deepEqual(assertNativeMotionReviews(f.file, f.packetFile).inspection,
      { authenticity: "declared-not-authenticated", typedRows: 0, untypedRows: 0, testFixtureRows: 1, audioApprovedUnits: [] });
    for (const row of [declared(writeManifest(true)), declared(writeManifest(false), path.join(f.root, "projects", "other"))]) {
      f.write(f.file, { schemaVersion: 1, reviews: [row] });
      assert.throws(() => assertNativeMotionReviews(f.file, f.packetFile), /admitted only for its own TEST fixture project/);
    }
    f.write(path.join(f.root, "export-request.json"), { project: path.join(f.root, "production-project") });
    f.write(f.file, { schemaVersion: 1, reviews: [declared(writeManifest(false))] });
    assert.throws(() => assertNativeMotionReviews(f.file, f.packetFile), /admitted only for its own TEST fixture project/);
    // Probe p14: the preview a production batch budgets, or a manifest outside the canary layout, never admits.
    f.write(path.join(f.root, "export-request.json"), { project, productionBudget: { batchId: "batch-test", clipId: "Q1" } });
    assert.throws(() => assertNativeMotionReviews(f.file, f.packetFile), /a preview no production batch budgets/);
    f.write(path.join(f.root, "export-request.json"), { project });
    const renamed = path.join(f.root, "OTHER-FIXTURE.json");
    f.write(renamed, JSON.parse(readFileSync(manifest, "utf8")));
    f.write(f.file, { schemaVersion: 1, reviews: [declared({ path: renamed, sha256: fileSha256(renamed)! })] });
    assert.throws(() => assertNativeMotionReviews(f.file, f.packetFile), /<root>\/FIXTURE\.json/);
    assert.throws(() => readInspection(declared(writeManifest(false)).inspection), /TEST route-canary declaration/);
  } finally { f.cleanup(); }
});
