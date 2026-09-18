import { validateProducerReview, type ProducerReview } from "@/app/api/producer/auto-edit/review-contract";
import { exactKeys, objectValue, sha256, stringValue, uuid } from "./validation";
import { proposalInteger, type TreatmentProposalV2 } from "./treatment-proposal-v2";

export const PROPOSAL_READINESS_SCOPE = "independent-proposal-review-not-plan-render-or-delivery-approval";
export const PROPOSAL_PENDING_CHECKS = ["versioned-treatment-execution-authority", "deterministic-full-plan-gates",
  "measured-opening-assets-and-geometry", "qualified-full-program-audio-and-color", "opening-playback-and-decision",
  "body-render-and-opening-parity", "full-program-qc-and-delivery"] as const;
/** Retained readiness evidence: the exact deterministic gate bundle verdict the draft was graded by. */
export const PROPOSAL_GATE_BUNDLE_KIND = "guided-proposal-deterministic-gate-bundle";
/** Readiness now RUNS this one; it stops being a promise the moment the bundle passes. */
export const PROPOSAL_DETERMINISTIC_GATE_CHECK = "deterministic-full-plan-gates" as const;
export interface ProposalReadinessCheckLedger { executedChecks: string[]; pendingChecks: string[] }

/** A passing bundle moves the deterministic gate out of pendingChecks; a failed or
 * unrun bundle leaves the full historical list untouched, so nothing is ever claimed. */
export function proposalReadinessChecks(deterministicGatesOk: boolean): ProposalReadinessCheckLedger {
  return {
    executedChecks: deterministicGatesOk ? [PROPOSAL_DETERMINISTIC_GATE_CHECK] : [],
    pendingChecks: PROPOSAL_PENDING_CHECKS.filter((check) =>
      !deterministicGatesOk || check !== PROPOSAL_DETERMINISTIC_GATE_CHECK),
  };
}
export interface ProposalReadinessSubmissionV1 {
  schemaVersion: 1; operation: "review-post-cut-proposal"; idempotencyKey: string;
  expectedToken: string; expectedJournalHash: string; proposalHash: string;
}
export interface ProposalReadinessCheck {
  kind: "clause" | "beat"; index: number; verdict: "pass" | "issue"; occurrenceIds: number[]; reason: string;
}
export interface ProposalReadinessReviewV1 extends Omit<ProducerReview, "stage"> {
  stage: "proposal-readiness"; checks: ProposalReadinessCheck[];
}

export function parseProposalReadinessSubmission(value: unknown): ProposalReadinessSubmissionV1 {
  const row = objectValue(value, "proposal readiness submission");
  const keys = ["schemaVersion", "operation", "idempotencyKey", "expectedToken", "expectedJournalHash", "proposalHash"];
  exactKeys(row, keys, keys, "proposal readiness submission");
  if (row.schemaVersion !== 1 || row.operation !== "review-post-cut-proposal") throw new Error("Unsupported proposal readiness action");
  uuid(row.idempotencyKey, "idempotencyKey"); stringValue(row.expectedToken, "expectedToken", 200);
  sha256(row.expectedJournalHash, "expectedJournalHash"); sha256(row.proposalHash, "proposalHash");
  return row as unknown as ProposalReadinessSubmissionV1;
}

function check(value: unknown): ProposalReadinessCheck {
  const row = objectValue(value, "readiness check"), keys = ["kind", "index", "verdict", "occurrenceIds", "reason"];
  exactKeys(row, keys, keys, "readiness check");
  if (!["clause", "beat"].includes(String(row.kind)) || !["pass", "issue"].includes(String(row.verdict))
      || !Array.isArray(row.occurrenceIds) || row.occurrenceIds.length > 20) throw new Error("Invalid readiness check");
  const occurrenceIds = row.occurrenceIds.map((id) => proposalInteger(id, "occurrenceId", 29999));
  if (new Set(occurrenceIds).size !== occurrenceIds.length) throw new Error("Duplicate readiness occurrence reference");
  return { kind: row.kind as "clause" | "beat", index: proposalInteger(row.index, "check index", 127),
    verdict: row.verdict as "pass" | "issue", occurrenceIds, reason: stringValue(row.reason, "reason", 2000) };
}

/** Reuse issue-shape semantics only. No legacy plan review object or approval is returned. */
export function parseProposalReadinessReview(value: unknown): ProposalReadinessReviewV1 {
  const row = objectValue(value, "proposal readiness review");
  const keys = ["schemaVersion", "stage", "verdict", "summary", "materialIssues", "findings", "checks"];
  exactKeys(row, keys, keys, "proposal readiness review");
  if (row.stage !== "proposal-readiness" || !Array.isArray(row.checks) || row.checks.length > 256) throw new Error("Invalid proposal readiness scope/checks");
  const { checks, ...fields } = row;
  const shared = validateProducerReview({ ...fields, stage: "plan" }, "plan");
  const parsed = checks.map(check);
  if (shared.verdict === "pass" && parsed.some((item) => item.verdict !== "pass")) throw new Error("Passing readiness review contains a failed check");
  return { ...shared, stage: "proposal-readiness", checks: parsed };
}

/** Every raw clause and whole-program beat is reviewed once; references name controller occurrences. */
export function assertProposalReviewCoverage(review: ProposalReadinessReviewV1, proposal: Pick<TreatmentProposalV2, "clauses" | "beats">,
  evidence: { anchors: number[]; occurrences: Array<readonly [number, number, number, number, number, ...unknown[]]> }): void {
  const expected = [...proposal.clauses.map((_, index) => `clause:${index}`), ...proposal.beats.map((_, index) => `beat:${index}`)];
  const actual = review.checks.map((item) => `${item.kind}:${item.index}`), unique = new Set(actual);
  if (actual.length !== expected.length || unique.size !== actual.length || expected.some((key) => !unique.has(key))
      || review.checks.some((item) => item.occurrenceIds.some((id) => id >= evidence.occurrences.length))) {
    throw new Error("Readiness review omitted/duplicated a raw clause or program beat, or used an ungrounded occurrence");
  }
  for (const item of review.checks.filter((check) => check.kind === "beat")) {
    const beat = proposal.beats[item.index], start = evidence.anchors[beat.startAnchor], end = evidence.anchors[beat.endAnchorExclusive];
    if (!item.occurrenceIds.some((id) => evidence.occurrences[id][3] < end && evidence.occurrences[id][4] > start)) {
      throw new Error("Readiness beat needs an actual occurrence within its own frame range, not only a distant reference");
    }
  }
}
