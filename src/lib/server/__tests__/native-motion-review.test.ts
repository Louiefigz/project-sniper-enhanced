/** Structural admission fixtures; no playback or independent reviewer is fabricated. */
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { assertNativeMotionReviews } from "../native-motion-review";
import { fileSha256 } from "../auto-edit-hash";
import { NATIVE_PREBUILD_COVERAGE } from "../native-short-prebuild-review";

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
    assert.equal(f.check([before, fresh]).status, "recorded-independent-motion-pass");
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
