/** Cross-unit contract with unit B1's packet `given` block (its fixture scripts/producer/tests/fixtures/
 * role-packet-given-contract.json, read by givenBlock) for
 * requirement approved-content-production-2026-09-27, plus the submission-time re-check of bound shared evidence, the
 * recorded submission (review-submitted) and check-final's as-submitted reading of a closed batch's record.
 * TEST structure only; nobody judged, watched or heard anything. */
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { test, type TestContext } from "node:test";
import { assertNativeFinalReview } from "../native-final-review";
import { givenCheck, type RecordCheck } from "../native-review-given-check";
import { recordDigest } from "../native-review-provenance";
import { evidenceCheck } from "../native-review-shared-evidence";
import { givenBlock, rewritePacket, TEST_SUBMITTED, testGivenCheck } from "./_native-review-fixture";
import { finalSetup, planSetup } from "./_native-review-subjects";

/** B1's shared evidence summary fields the re-check compares (role_packet_given.evidence_summary). */
const EVIDENCE = { path: "/TEST/SHARED-EVIDENCE-v1.json", sha256: "c".repeat(64), version: 1, contentSha256: "d".repeat(64) };
const CURRENT = { status: "shared-evidence-current", ...EVIDENCE, givenClips: ["TEST-Q1"] };
const CONTRADICTION = { code: "TEST_GIVEN_DEPARTS", severity: "major", lane: "copy", message: "TEST subject departs from the given words",
  evidence: ["TEST"], requiredAction: "TEST render the given words", scope: "approved-content-contradiction" };

function currentEvidence(t: TestContext, report: object = CURRENT) {
  return t.mock.method(evidenceCheck, "run", () => report);
}

/** A plan-critic subject whose packet binds TEST shared evidence and this given block (or none). */
function planWith(t: TestContext, given: unknown) {
  const s = planSetup(t), sha = rewritePacket(s.packet.path, packet => {
    packet.sharedEvidence = { ...EVIDENCE };
    if (given !== undefined) packet.given = given;
  });
  const draft = (extra: object = {}) => ({ ...s.draft(), rolePacketSha256: sha,
    scenes: s.draft().scenes.map(scene => ({ ...scene, evidenceBasis: "inspected" })), ...extra });
  return { ...s, sha, draft };
}

test("contract: unchanged given content passes and binds the given identity; an absent block binds no approval", t => {
  const run = currentEvidence(t);
  for (const [name, given, expected] of [
    ["exact", givenBlock(), { batch: "batch-test", clip: "TEST-Q1", origin: "studio.production.api.read_approval",
      identity: "b".repeat(64), scriptSha256: "a".repeat(64), title: "TEST Given Title" }],
    ["normalization-only", givenBlock({ title: { planned: "test given title", status: "normalization-only" } }), undefined],
    ["not-supplied", { status: "not-supplied", meaning: "TEST no live batch holds this source" }, null],
    ["absent", undefined, null]] as const) {
    const s = planWith(t, given);
    s.write(s.draft());
    const result = s.submit();
    assert.equal(result.status, "recorded-independent-plan-pass", name);
    assert.deepEqual(result.approvedContent.departures, [], name);
    if (expected !== undefined) assert.deepEqual(result.approvedContent.approved, expected, name);
    assert.deepEqual(JSON.parse(readFileSync(s.output, "utf8")).approvedContent, result.approvedContent, name);
  }
  assert.ok(run.mock.calls.every(call => call.arguments[0] === EVIDENCE.path));
});

test("contract: a material title or any selection, caption-text or timing mismatch refuses a pass", t => {
  currentEvidence(t);
  const cases: Array<[object, RegExp]> = [
    [{ title: { planned: "TEST Other Title", status: "different", material: true } },
      /title: the subject shows "TEST Other Title", given "TEST Given Title" \(different\)/],
    [{ selection: { matches: false, missingWords: [3, 4], otherOrder: true } }, /selection: kept words differ .*2 missing, 0 extra, 0 repeated, other order/],
    [{ captionText: { matches: false, mismatchedOccurrences: [1, 2] } }, /caption text: 2 occurrence\(s\) carry other words/],
    [{ timing: { matches: false, frameMismatches: [7] } }, /timing: 1 frame and 0 segment mismatch\(es\)/]];
  for (const [change, departure] of cases) {
    const s = planWith(t, givenBlock(change));
    s.write(s.draft());
    assert.throws(() => s.submit(), departure);
    assert.throws(() => s.submit(), (error: Error) => /A pass cannot be recorded/.test(error.message)
      && !/new approval|record a change/.test(error.message));
  }
});

test("contract: a departure on a revise must be covered by an approved-content-contradiction material issue", t => {
  currentEvidence(t);
  const s = planWith(t, givenBlock({ title: { planned: "TEST Other Title", status: "different", material: true } }));
  s.write(s.draft({ verdict: "revise", materialIssues: [{ ...CONTRADICTION, scope: "execution" }] }));
  assert.throws(() => s.submit(), /cover it with a material issue scoped approved-content-contradiction/);
  s.write(s.draft({ verdict: "revise", materialIssues: [CONTRADICTION] }));
  const revised = s.submit();
  assert.equal(revised.status, "recorded-plan-review-requires-revision");
  assert.deepEqual([revised.approvedContent.departures.length, revised.approvedContent.contradictions], [1, ["TEST_GIVEN_DEPARTS"]]);
});

test("contract: a packet without the plan compared, or with a malformed given block", t => {
  currentEvidence(t);
  const unchecked = planWith(t, givenBlock({ planChecked: false }));
  unchecked.write(unchecked.draft());
  assert.equal(unchecked.submit().approvedContent.planChecked, false);
  const malformed: Array<[unknown, RegExp]> = [
    [{ ...givenBlock(), title: { given: "TEST Given Title", planned: "x", status: "different" } }, /given\.title\.material must be true or false/],
    [givenBlock({ title: { planned: "x", status: "different" } }), /given\.title\.material is true exactly for a different title/],
    [givenBlock({ title: { status: "similar" } }), /given\.title\.status is not a known state/],
    [{ ...givenBlock(), timing: undefined }, /given is missing fields: timing/],
    [{ ...givenBlock(), timing: { matches: false } }, /given\.timing\.details must be an object/],
    [{ ...givenBlock(), status: "approved" }, /given\.status must be bound or not-supplied/],
    [{ ...givenBlock(), readFrom: "shared-evidence" }, /approvals are read only through studio\.production\.api\.read_approval/],
    [{ ...givenBlock(), requirementRevision: "TEST-other" }, /given\.requirementRevision must be approved-content-production/],
    [{ ...givenBlock(), origin: "TEST" }, /given has unsupported fields: origin/],
    [{ ...givenBlock(), selection: { matches: "yes" } }, /given\.selection\.matches must be true or false/],
    [{ ...givenBlock(), scriptSha256: "not-a-hash" }, /given\.scriptSha256/]];
  for (const [given, refusal] of malformed) {
    const s = planWith(t, given);
    s.write(s.draft());
    assert.throws(() => s.submit(), refusal);
  }
});

test("a proposed change to the given words is surfaced for the operator and never withholds execution approval", t => {
  currentEvidence(t);
  const s = planWith(t, givenBlock());
  const finding = { code: "TEST_GIVEN_CLAIM", severity: "minor", lane: "copy", message: "TEST the given script misstates a year",
    evidence: ["TEST"], scope: "proposed-change" };
  s.write(s.draft({ findings: [finding] }));
  const result = s.submit();
  assert.equal(result.status, "recorded-independent-plan-pass");
  assert.deepEqual(result.approvedContent.proposedChanges, ["TEST_GIVEN_CLAIM"]);
  const again = planWith(t, givenBlock());
  again.write(again.draft({ verdict: "revise", materialIssues: [{ ...CONTRADICTION, scope: "proposed-change" }] }));
  assert.throws(() => again.submit(), /materialIssues\[0\]\.scope must be execution or approved-content-contradiction/);
  again.write(again.draft({ findings: [{ ...finding, scope: "approved-content-contradiction" }] }));
  assert.throws(() => again.submit(), /findings\[0\]\.scope must be execution or proposed-change/);
});

test("scene evidenceBasis is required with shared evidence bound and refused without it", t => {
  currentEvidence(t);
  const s = planWith(t, undefined);
  s.write({ ...s.draft(), scenes: planSetup(t).draft().scenes });
  assert.throws(() => s.submit(), /scenes\[0\]\.evidenceBasis is required with shared evidence bound: inspected or shared-evidence-only/);
  s.write(s.draft({ scenes: s.draft().scenes.map(scene => ({ ...scene, evidenceBasis: "assumed" })) }));
  assert.throws(() => s.submit(), /evidenceBasis is required/);
  const unbound = planSetup(t);
  unbound.write({ ...unbound.draft(), scenes: unbound.draft().scenes.map(scene => ({ ...scene, evidenceBasis: "inspected" })) });
  assert.throws(() => unbound.submit(), /evidenceBasis names shared evidence, but this role packet binds none/);
});

test("bound shared evidence that is superseded, moved or changed refuses the submission", t => {
  currentEvidence(t, { ...CURRENT, contentSha256: "e".repeat(64) });
  const s = planWith(t, givenBlock());
  s.write(s.draft());
  assert.throws(() => s.submit(), /shared evidence this role packet bound is no longer current/);
  const failing = planWith(t, givenBlock());
  t.mock.method(evidenceCheck, "run", () => { throw new Error("Shared evidence re-check failed: TEST superseded by v2"); });
  failing.write(failing.draft());
  assert.throws(() => failing.submit(), /TEST superseded by v2/);
});

test("final critics (FC-12): a departure refuses the pass; a proposed change is surfaced in the hand-off step", t => {
  const s = finalSetup(t);
  const sha = rewritePacket(s.packet.path, packet => { packet.given = givenBlock({ selection: { matches: false, extraWords: [9] } }); });
  s.write({ ...s.draft(), rolePacketSha256: sha });
  assert.throws(() => s.submit(), /A pass cannot be recorded while the subject departs .*selection: kept words differ/);
  const clean = finalSetup(t), cleanSha = rewritePacket(clean.packet.path, packet => { packet.given = givenBlock(); });
  const finding = { code: "TEST_GIVEN_NAME", severity: "minor", lane: "copy", message: "TEST given title misspells a name",
    evidence: ["TEST"], scope: "proposed-change" };
  clean.write({ ...clean.draft(), rolePacketSha256: cleanSha, findings: [finding] });
  const result = clean.submit();
  assert.equal(result.editorialFinal, "approved");
  assert.match(result.nextStep, /Surface the proposed-change findings \(TEST_GIVEN_NAME\) to the operator; they need no second approval round/);
  assert.deepEqual(assertNativeFinalReview(clean.output).approvedContent?.proposedChanges, ["TEST_GIVEN_NAME"]);
});

/** The TEST double's report with the batch closed (and optionally a later approval superseding the answered one). */
function closedReport(packetPath: string, record?: RecordCheck, supersededBy: object | null = null) {
  const report = testGivenCheck(packetPath, record);
  return { ...report, given: { ...report.given, authorityStatus: "closed" },
    asSubmitted: report.asSubmitted && { ...report.asSubmitted, authorityStatus: "closed", supersededBy } };
}

test("a batch-bound record admits only with its recorded submission; check-final reads it as submitted after close", t => {
  const s = finalSetup(t), sha = rewritePacket(s.packet.path, packet => { packet.given = givenBlock(); });
  s.write({ ...s.draft(), rolePacketSha256: sha });
  assert.equal(s.submit().editorialFinal, "approved");
  const record = JSON.parse(readFileSync(s.output, "utf8"));
  const event = TEST_SUBMITTED.get(recordDigest(record));
  assert.deepEqual([record.submission.timing.basis, event?.role, event?.elapsed],
    ["batch-authority", "final-critic", record.submission.timing.submittedElapsed]);
  const run = t.mock.method(givenCheck, "run", (file: string, check?: RecordCheck) => closedReport(file, check));
  const closed = assertNativeFinalReview(s.output);
  assert.deepEqual([closed.editorialFinal, closed.approvalAsSubmitted?.authorityStatus], ["approved", "closed"]);
  assert.equal(run.mock.calls.at(-1)?.arguments[1]?.asSubmitted, true);
  run.mock.mockImplementation((file: string, check?: RecordCheck) => closedReport(file, check, { identity: "f".repeat(64), elapsed: 12 }));
  const superseded = assertNativeFinalReview(s.output);
  assert.equal(superseded.editorialFinal, "not-established");
  assert.match(superseded.missing.join("; "), /superseded at 12\.0 s of the batch clock/);
  run.mock.restore();
  const edited = `${s.output}.EDITED.json`;
  record.submission.timing.submittedElapsed = record.submission.timing.resolvedElapsed;
  writeFileSync(edited, JSON.stringify(record));
  assert.throws(() => assertNativeFinalReview(edited), /did not record the submission of record/);
});

test("an admitting reader never binds a closed batch's approval; only a read as submitted does", t => {
  currentEvidence(t);
  const s = planWith(t, givenBlock());
  s.write(s.draft());
  t.mock.method(givenCheck, "run", (file: string, check?: RecordCheck) => closedReport(file, check));
  assert.throws(() => s.submit(), /given\.authorityStatus is closed: only the current active or draining batch binds/);
});
