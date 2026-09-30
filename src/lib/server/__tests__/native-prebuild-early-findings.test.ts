/** Early findings of a bounded plan critic and the final record's duty to account for them (P2-11). TEST-only
 * synthetic plans and packets: no fixture project is built and no Python runs (the engine's given check and early
 * record are TEST doubles over `_native-review-fixture`'s); nobody reviewed anything. */
import assert from "node:assert/strict";
import { existsSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test, type TestContext } from "node:test";
import type { JsonRecord } from "@/lib/producer/contracts/validation";
import { executeNativeReviewCommand } from "../../../../scripts/producer/native-review";
import { fileSha256 } from "../auto-edit-hash";
import { givenCheck } from "../native-review-given-check";
import { EARLY_KIND, earlyFindingsCheck, reviewLateness, submitNativePrebuildEarlyFindings } from "../native-prebuild-early-findings";
import { submitNativePrebuildReview } from "../native-prebuild-review-submission";
import { nativeShortPrebuildPlanHash } from "../native-short-prebuild-review";
import type { NativeShortProjectInput } from "../native-short-project";
import { AUTHOR, coverage, givenBlock, reviewer, rewritePacket, rolePacket, testRoot, writeJson } from "./_native-review-fixture";

const EARLY = new Map<string, JsonRecord[]>(), BUDGETS = new Map<string, JsonRecord>();
const COAUTHOR = "TEST-coauthor-session";
const BUDGET = { kind: "plan-critic", status: "bounded", resolvedElapsed: 0, earlyBy: 420, hardBy: 600 };

/** TEST doubles for this module, over the fixture's given check: it also reports the budget "recorded" at each packet's
 * resolution and this process's early records (per packet path); recording one keeps index order. Neither reads the
 * real authority. */
const fixtureGivenCheck = givenCheck.run;
givenCheck.run = (packetPath, check) => ({ ...fixtureGivenCheck(packetPath, check), budget: BUDGETS.get(packetPath) ?? null,
  earlyFindings: EARLY.get(packetPath) ?? [] });
earlyFindingsCheck.record = (packetPath, issuesSha256, counts, elapsed) => {
  const rows = EARLY.get(packetPath) ?? [];
  if (counts.index !== rows.length + 1) throw new Error("TEST authority refused an early record out of order");
  rows.push({ index: counts.index, issuesSha256, issues: counts.issues, elapsed });
  EARLY.set(packetPath, rows);
  return { status: "early-findings-recorded", packet: { path: packetPath, sha256: fileSha256(packetPath)! },
    event: { event: "review-early-findings", ...rows.at(-1) } };
};

/** A synthetic TEST plan and a plan-critic packet (batch-bound unless `bound` is false), with the budget its resolution
 * recorded (`budget`; null: none recorded). */
function setup(t: TestContext, options: { bound?: boolean; budget?: JsonRecord | null } = {}) {
  const root = testRoot(t, "TEST-early-findings-"), plan = { schemaVersion: 1, canvas: { frameRate: "30/1", totalFrames: 90 },
    strategy: { scenes: [{ startFrame: 0, endFrame: 90 }] }, assets: [] } as unknown as NativeShortProjectInput;
  const planFile = writeJson(path.join(root, "clip", "native-plan-v1.json"), plan), planHash = nativeShortPrebuildPlanHash(plan);
  const packet = rolePacket(root, "plan-critic", { plan: { path: planFile, sha256: fileSha256(planFile)!, planHash },
    frameRate: "30/1", totalFrames: 90, scenes: [{ index: 0, startFrame: 0, endFrame: 90 }] }, [planFile]);
  const records = path.dirname(packet.path), output = path.join(records, "PREBUILD-REVIEW-v1.json");
  const sha256 = rewritePacket(packet.path, value => {
    value.submission = { record: output };
    value.authorSessionIds = [AUTHOR, COAUTHOR];
    if (options.bound !== false) value.given = givenBlock();
  });
  if (options.budget !== null) BUDGETS.set(packet.path, options.budget ?? BUDGET);
  const early = (index: number) => path.join(records, `PREBUILD-REVIEW-v1-EARLY-${index}.json`);
  return { root, planFile, packet: packet.path, sha256, output, early,
    submitEarly: (index: number, issues: unknown[] = [issue(`TEST_EARLY_${index}`)], session?: string) => {
      const observations = writeJson(path.join(records, `EARLY-${index}-OBSERVATIONS.json`), { schemaVersion: 1, kind: EARLY_KIND,
        rolePacketSha256: sha256, reviewer: reviewer(session), materialIssues: issues });
      return submitNativePrebuildEarlyFindings({ packet: packet.path, observations, output: early(index) });
    },
    submitFinal: (codes: string[], withdrawn?: unknown[]) => {
      const observations = writeJson(path.join(records, "PREBUILD-REVIEW-v1-OBSERVATIONS.json"), { schemaVersion: 2,
        kind: "native-plan-review-observations", rolePacketSha256: sha256, reviewer: reviewer(), coverage: coverage(),
        verdict: "revise", summary: "TEST structural submission; no plan was judged.", materialIssues: codes.map(issue),
        findings: [], limitations: [], evidence: [], inspection: [], approves: [],
        scenes: [{ index: 0, startFrame: 0, endFrame: 90, note: "TEST synthetic scene note" }],
        ...(withdrawn ? { withdrawnEarlyIssues: withdrawn } : {}) });
      return submitNativePrebuildReview({ packet: packet.path, observations, output });
    } };
}

function issue(code: string) {
  return { code, severity: "major", lane: "review", message: "TEST material issue; nothing was judged.",
    evidence: ["TEST fixture"], scope: "execution", requiredAction: "TEST smallest repair" };
}

test("records early material issues without a verdict", async t => {
  const s = setup(t);
  const first = s.submitEarly(1), observations = path.join(path.dirname(s.packet), "EARLY-2-OBSERVATIONS.json");
  writeJson(observations, { schemaVersion: 1, kind: EARLY_KIND, rolePacketSha256: s.sha256, reviewer: reviewer(),
    materialIssues: [issue("TEST_A"), issue("TEST_B")] });
  const second = await executeNativeReviewCommand(["submit-prebuild-early", s.packet, observations, s.early(2)]) as
    ReturnType<typeof submitNativePrebuildEarlyFindings>;
  assert.deepEqual([first.status, first.record, first.issues, first.index], ["early-findings-recorded", s.early(1), 1, 1]);
  assert.deepEqual([second.record, second.issues, second.index], [s.early(2), 2, 2]);
  const record = JSON.parse(readFileSync(s.early(1), "utf8")) as JsonRecord;
  assert.equal("verdict" in record || "review" in record || "approves" in record, false);
  assert.deepEqual(EARLY.get(s.packet)!.map(row => [row.index, row.issuesSha256]), [[1, record.issuesSha256], [2,
    (JSON.parse(readFileSync(s.early(2), "utf8")) as JsonRecord).issuesSha256]]);
});

test("refuses a stale plan", t => {
  const s = setup(t), run = givenCheck.run;
  t.after(() => { givenCheck.run = run; });
  givenCheck.run = (packetPath, check) => {
    const report: JsonRecord = run(packetPath, check);
    return { ...report, given: { ...(report.given as JsonRecord), identity: "c".repeat(64) } };
  };
  assert.throws(() => s.submitEarly(1), /no longer yields this packet's given block/);
  givenCheck.run = run;
  writeFileSync(s.planFile, readFileSync(s.planFile, "utf8").replace("\"totalFrames\": 90", "\"totalFrames\": 91"));
  assert.throws(() => s.submitEarly(1), /Stale review inputs/);
  assert.equal(existsSync(s.early(1)), false);
});

test("refuses an author as critic", t => {
  const s = setup(t);
  assert.throws(() => s.submitEarly(1, [issue("TEST_EARLY_1")], COAUTHOR), /Reviewer session TEST-coauthor-session is a recorded author/);
  assert.equal(existsSync(s.early(1)), false);
});

test("refuses an empty issue list", t => {
  const s = setup(t);
  assert.throws(() => s.submitEarly(1, []), /1–16 material issues/);
  assert.throws(() => s.submitEarly(1, Array.from({ length: 17 }, (_, index) => issue(`TEST_${index}`))), /1–16 material issues/);
  assert.throws(() => s.submitEarly(1, [{ ...issue("TEST_EARLY_1"), scope: "proposed-change" }]), /scope must be execution/);
  assert.equal(EARLY.get(s.packet), undefined);
});

test("refuses a fourth early record", t => {
  const s = setup(t);
  for (const index of [1, 2, 3]) s.submitEarly(index);
  assert.throws(() => s.submitEarly(4), /at most 3 early findings per role packet/);
  const other = setup(t);
  assert.throws(() => submitNativePrebuildEarlyFindings({ packet: other.packet, observations: other.planFile,
    output: other.early(2) }), /The next early findings record of this packet is .*EARLY-1\.json/);
  const unbound = setup(t, { bound: false });
  assert.throws(() => unbound.submitEarly(1), /only for a batch-bound packet/);
});

test("final review must account for early findings", t => {
  const s = setup(t);
  s.submitEarly(1);
  assert.throws(() => s.submitFinal(["TEST_OTHER"]),
    /^Error: Final plan review omits early finding TEST_EARLY_1; keep it as a material issue or withdraw it with a reason$/);
  assert.throws(() => s.submitFinal(["TEST_OTHER"], [{ code: "TEST_EARLY_1", reason: "TEST too short" }]), /at least 20 characters/);
  assert.throws(() => s.submitFinal(["TEST_OTHER"], [{ code: "TEST_UNKNOWN", reason: "TEST reason long enough to count" }]),
    /which no early finding of this packet raised/);
  renameSync(s.early(1), `${s.early(1)}.moved`);
  assert.throws(() => s.submitFinal(["TEST_EARLY_1"]), /Early findings record 1 of this packet is missing/);
  const kept = readFileSync(`${s.early(1)}.moved`, "utf8");
  writeFileSync(s.early(1), kept.replace("TEST_EARLY_1", "TEST_EARLY_X"));
  assert.throws(() => s.submitFinal(["TEST_EARLY_1"]), /differs from what the batch authority recorded/);
  writeFileSync(s.early(1), kept);
  const done = s.submitFinal(["TEST_OTHER"], [{ code: "TEST_EARLY_1", reason: "TEST the repair made this obsolete" }]);
  assert.deepEqual(done.earlyFindings, { early: ["TEST_EARLY_1"], withdrawn: ["TEST_EARLY_1"] });
  assert.equal(done.status, "recorded-plan-review-requires-revision");
});

test("late submission is marked late", t => {
  const late = setup(t).submitFinal(["TEST_MATERIAL"]);
  const onTime = setup(t, { budget: { ...BUDGET, hardBy: 1e7 } }).submitFinal(["TEST_MATERIAL"]);
  assert.deepEqual(late.timing, { late: true, lateBasis: "budget", hardBy: 600 });
  assert.deepEqual(onTime.timing, { late: false, lateBasis: "budget", hardBy: 1e7 });
});

test("clock-unknown counts as late", t => {
  for (const options of [{ budget: null }, { bound: false }, { budget: { ...BUDGET, hardBy: null } }]) {
    const done = setup(t, options).submitFinal(["TEST_MATERIAL"]);
    assert.deepEqual(done.timing, { late: true, lateBasis: "clock-unknown", hardBy: null }, JSON.stringify(options));
  }
});

test("hardBy itself is on time; an engine report without the budget or early findings is refused", t => {
  const at = (submittedElapsed: number) => ({ basis: "batch-authority" as const, batchId: "TEST", clipId: "TEST",
    resolvedElapsed: 0, submittedElapsed });
  assert.deepEqual(reviewLateness({ hardBy: 600 }, at(600)), { late: false, lateBasis: "budget", hardBy: 600 });
  assert.deepEqual(reviewLateness({ hardBy: 600 }, at(600.001)), { late: true, lateBasis: "budget", hardBy: 600 });
  assert.equal(reviewLateness(null, at(1)).lateBasis, "clock-unknown");
  assert.equal(reviewLateness({ hardBy: 600 }, { basis: "declared-not-authenticated" }).lateBasis, "clock-unknown");
  const s = setup(t), run = givenCheck.run;
  t.after(() => { givenCheck.run = run; });
  for (const drop of ["budget", "earlyFindings"]) {
    givenCheck.run = (packetPath, check) => {
      const report: JsonRecord = run(packetPath, check);
      delete report[drop];
      return report;
    };
    assert.throws(() => s.submitFinal(["TEST_MATERIAL"]), /did not report this packet's budget and early findings/);
  }
});
