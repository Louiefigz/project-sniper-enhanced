import type {
  ProducerFinding,
  ProducerMaterialIssue,
  ProducerReview,
  ProducerReviewStage,
} from "./review-contract";

const MAX_EVIDENCE = 20;
const MAX_SUMMARY = 2000;
const MAX_MATERIAL_ISSUES = 50;
const MAX_FINDINGS = 100;

export function rejectedBatchResult<T>(
  values: PromiseSettledResult<T>[],
): PromiseRejectedResult | undefined {
  return values.find(
    (value): value is PromiseRejectedResult => value.status === "rejected",
  );
}

function unique(values: string[]): string[] {
  return [...new Set(values)].slice(0, MAX_EVIDENCE);
}

function mergeMaterial(
  current: ProducerMaterialIssue,
  incoming: ProducerMaterialIssue,
): ProducerMaterialIssue {
  return {
    ...current,
    severity: current.severity === "critical" || incoming.severity === "critical"
      ? "critical" : "major",
    evidence: unique([...current.evidence, ...incoming.evidence]),
  };
}

function mergeFinding(
  current: ProducerFinding,
  incoming: ProducerFinding,
): ProducerFinding {
  return {
    ...current,
    severity: current.severity === "minor" || incoming.severity === "minor"
      ? "minor" : "info",
    evidence: unique([...current.evidence, ...incoming.evidence]),
  };
}

function materialIssues(reviews: ProducerReview[]): ProducerMaterialIssue[] {
  const merged = new Map<string, ProducerMaterialIssue>();
  for (const issue of reviews.flatMap((review) => review.materialIssues)) {
    const current = merged.get(issue.code);
    merged.set(issue.code, current ? mergeMaterial(current, issue) : issue);
  }
  return [...merged.values()];
}

const SEVERITY_RANK: Record<ProducerMaterialIssue["severity"], number> = {
  critical: 0,
  major: 1,
};

/** Triage the merged issue set to the governed cap by severity (criticals
 * always survive) instead of failing the run. The revision contract can only
 * account for MAX_MATERIAL_ISSUES codes in one round, and a batch exceeding it
 * used to throw and discard the whole run — including already-approved cuts.
 * The deferred tail resurfaces on the next review round after the top issues
 * are fixed, so nothing is lost; it is only reordered. */
function triageMaterialIssues(issues: ProducerMaterialIssue[]): {
  kept: ProducerMaterialIssue[];
  deferred: number;
} {
  if (issues.length <= MAX_MATERIAL_ISSUES) return { kept: issues, deferred: 0 };
  const ranked = [...issues].sort(
    (a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity],
  );
  return {
    kept: ranked.slice(0, MAX_MATERIAL_ISSUES),
    deferred: issues.length - MAX_MATERIAL_ISSUES,
  };
}

function findings(
  reviews: ProducerReview[],
  materialCodes: Set<string>,
): ProducerFinding[] {
  const merged = new Map<string, ProducerFinding>();
  for (const finding of reviews.flatMap((review) => review.findings)) {
    if (materialCodes.has(finding.code)) continue;
    const current = merged.get(finding.code);
    merged.set(finding.code, current ? mergeFinding(current, finding) : finding);
  }
  return [...merged.values()];
}

function summary(reviews: ProducerReview[]): string {
  const values = [...new Set(reviews.map((review) => review.summary))];
  return values.join(" | ").slice(0, MAX_SUMMARY);
}

/** Merge independent reviews of one immutable authority into one revision brief. */
export function mergeProducerReviewBatch(
  reviews: ProducerReview[],
  stage: ProducerReviewStage,
): ProducerReview {
  if (!reviews.length) throw new Error("cannot merge an empty producer review batch");
  if (reviews.some((review) => review.stage !== stage)) {
    throw new Error(`producer review batch contains a non-${stage} review`);
  }
  const allIssues = materialIssues(reviews);
  const { kept: issues, deferred } = triageMaterialIssues(allIssues);
  const verdict = reviews.some((review) => review.verdict === "block")
    ? "block" : issues.length ? "revise" : "pass";
  const deferralNote = deferred
    ? ` [${deferred} lower-severity issue(s) over the ${MAX_MATERIAL_ISSUES}-issue revision cap deferred to the next review round]`
    : "";
  return {
    schemaVersion: 1,
    stage,
    verdict,
    summary: (summary(reviews) + deferralNote).slice(0, MAX_SUMMARY),
    materialIssues: issues,
    findings: findings(
      reviews, new Set(allIssues.map((issue) => issue.code)),
    ).slice(0, MAX_FINDINGS),
  };
}
