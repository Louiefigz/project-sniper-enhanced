import assert from "node:assert/strict";
import { mergeProducerReviewBatch } from
  "../../../app/api/producer/auto-edit/review-batch";
import type {
  ProducerMaterialIssue,
  ProducerReview,
} from "../../../app/api/producer/auto-edit/review-contract";

function issue(
  code: string,
  severity: ProducerMaterialIssue["severity"],
): ProducerMaterialIssue {
  return {
    code,
    severity,
    lane: "graphics",
    message: `issue ${code}`,
    evidence: ["evidence"],
    requiredAction: "fix it",
  };
}

function review(issues: ProducerMaterialIssue[]): ProducerReview {
  return {
    schemaVersion: 1,
    stage: "plan",
    verdict: "revise",
    summary: "critic review",
    materialIssues: issues,
    findings: [],
  };
}

/** A merged batch over the 50-issue cap must triage (keep the 50 most severe)
 * instead of throwing and killing the run — criticals always survive, and the
 * deferred count is surfaced in the summary rather than dropped silently. */
function testTriageClampsInsteadOfThrowing(): void {
  const majorsA = Array.from({ length: 40 }, (_, i) =>
    issue(`AMAJOR-${i}`, "major"));
  const criticalsB = Array.from({ length: 5 }, (_, i) =>
    issue(`CRIT-${i}`, "critical"));
  const majorsB = Array.from({ length: 10 }, (_, i) =>
    issue(`BMAJOR-${i}`, "major"));

  const merged = mergeProducerReviewBatch(
    [review(majorsA), review([...criticalsB, ...majorsB])],
    "plan",
  );

  // 55 unique codes → clamped to exactly 50, 5 deferred.
  assert.equal(merged.materialIssues.length, 50);
  assert.equal(merged.verdict, "revise");
  // Every critical survives the cut (severity-ranked triage).
  for (let i = 0; i < 5; i += 1) {
    assert.ok(
      merged.materialIssues.some((it) => it.code === `CRIT-${i}`),
      `critical CRIT-${i} must survive triage`,
    );
  }
  // The deferral is reported, not silent.
  assert.match(merged.summary, /5 lower-severity issue\(s\)/);
}

/** A batch at or under the cap passes through unchanged with no deferral note. */
function testUnderCapIsUntouched(): void {
  const issues = Array.from({ length: 12 }, (_, i) =>
    issue(`ONLY-${i}`, "major"));
  const merged = mergeProducerReviewBatch([review(issues)], "plan");
  assert.equal(merged.materialIssues.length, 12);
  assert.doesNotMatch(merged.summary, /deferred to the next review round/);
}

function main(): void {
  testTriageClampsInsteadOfThrowing();
  testUnderCapIsUntouched();
  console.log("review-batch-triage.test.ts: all assertions passed");
}

main();
