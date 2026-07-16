import { readFileSync } from "node:fs";
import type { AuditBOutcome } from "./chain";
import type { ProducerReviewResult } from "./brain-review-runner";
import type { RenderedReviewEvidence } from "./rendered-review-prompt";
import type { VisualReviewLens } from "./round-policy";
import type { ProducerFinding, ProducerMaterialIssue, ProducerReview } from "./review-contract";

interface AuditMachine {
  checks?: Array<{
    name?: unknown;
    status?: unknown;
    measured?: unknown;
    detail?: unknown;
  }>;
}

export interface QualityLensReview {
  lens: VisualReviewLens;
  result: ProducerReviewResult;
  path: string;
}

function safeCode(lens: VisualReviewLens, code: string, index: number): string {
  const prefix = lens === "composition" ? "QC_COMP" : "QC_EDIT";
  return `${prefix}_${index + 1}_${code}`.slice(0, 64);
}

function lensIssues(review: QualityLensReview): ProducerMaterialIssue[] {
  return review.result.review.materialIssues.map((issue, index) => ({
    ...issue,
    code: safeCode(review.lens, issue.code, index),
    lane: `${review.lens}:${issue.lane}`.slice(0, 80),
  }));
}

function lensFindings(review: QualityLensReview): ProducerFinding[] {
  return review.result.review.findings.map((finding, index) => ({
    ...finding,
    code: safeCode(review.lens, finding.code, index + 50),
    lane: `${review.lens}:${finding.lane}`.slice(0, 80),
  }));
}

const MATERIAL_TEMPORAL_WARNINGS = new Set(["motion_pacing"]);

function materialAuditWarnings(evidence: RenderedReviewEvidence | null): ProducerMaterialIssue[] {
  if (!evidence) return [];
  try {
    const machine = JSON.parse(readFileSync(evidence.auditReportPath, "utf8")) as AuditMachine;
    return (machine.checks ?? []).flatMap((check) => {
      const name = typeof check.name === "string" ? check.name : "";
      if (check.status !== "warn" || !MATERIAL_TEMPORAL_WARNINGS.has(name)) return [];
      const measured = typeof check.measured === "string" ? check.measured : "warning";
      const detail = typeof check.detail === "string" ? check.detail : "";
      return [{
        code: `QC_AUDIT_WARN_${name.toUpperCase()}`.slice(0, 64),
        severity: "major" as const,
        lane: "deterministic-qc",
        message: `${name}: ${measured}`.slice(0, 1900),
        evidence: [detail || evidence.auditReportPath],
        requiredAction: "Repair and rerender until temporal QC passes without this warning.",
      }];
    });
  } catch {
    return [];
  }
}

function auditIssues(audit: AuditBOutcome, evidence: RenderedReviewEvidence | null): ProducerMaterialIssue[] {
  if (!audit.failure && evidence) return materialAuditWarnings(evidence);
  const message = audit.failure ?? "Audit B did not produce readable visual-review evidence.";
  return [{
    code: evidence ? "QC_DETERMINISTIC_AUDIT" : "QC_REVIEW_EVIDENCE_MISSING",
    severity: "critical",
    lane: "deterministic-qc",
    message: message.slice(0, 1900),
    evidence: [String(audit.event.report ?? audit.event.machine ?? "audit report unavailable")],
    requiredAction: evidence
      ? "Repair the plan if possible, then render and run the complete audit again."
      : "Restore review-frame extraction or its evidence contract before any candidate can be approved.",
  }];
}

export function aggregateQualityReview(
  audit: AuditBOutcome,
  evidence: RenderedReviewEvidence | null,
  reviews: QualityLensReview[],
): ProducerReview {
  const materialIssues = [...auditIssues(audit, evidence), ...reviews.flatMap(lensIssues)];
  const blocked = !evidence || reviews.some((item) => item.result.review.verdict === "block");
  return {
    schemaVersion: 1,
    stage: "rendered",
    verdict: materialIssues.length ? (blocked ? "block" : "revise") : "pass",
    summary: materialIssues.length
      ? `Candidate has ${materialIssues.length} material QC issue(s).`
      : "Deterministic Audit B and both independent visual critics passed.",
    materialIssues,
    findings: reviews.flatMap(lensFindings),
  };
}
