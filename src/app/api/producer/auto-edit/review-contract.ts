export const PRODUCER_REVIEW_SCHEMA_VERSION = 1 as const;
export const PRODUCER_REVIEW_STAGES = ["cut", "plan", "rendered"] as const;
export const PRODUCER_REVIEW_VERDICTS = ["pass", "revise", "block"] as const;

export type ProducerReviewStage = (typeof PRODUCER_REVIEW_STAGES)[number];
export type ProducerReviewVerdict = (typeof PRODUCER_REVIEW_VERDICTS)[number];

export interface ProducerMaterialIssue {
  code: string;
  severity: "major" | "critical";
  lane: string;
  message: string;
  evidence: string[];
  requiredAction: string;
}

export interface ProducerFinding {
  code: string;
  severity: "info" | "minor";
  lane: string;
  message: string;
  evidence: string[];
}

export interface ProducerReview {
  schemaVersion: typeof PRODUCER_REVIEW_SCHEMA_VERSION;
  stage: ProducerReviewStage;
  verdict: ProducerReviewVerdict;
  summary: string;
  materialIssues: ProducerMaterialIssue[];
  findings: ProducerFinding[];
}

export interface ProducerRevisionReceipt {
  schemaVersion: typeof PRODUCER_REVIEW_SCHEMA_VERSION;
  changedPlan: boolean;
  addressedIssueCodes: string[];
  deferredIssueCodes: string[];
  summary: string;
}

const REVIEW_KEYS = [
  "schemaVersion", "stage", "verdict", "summary", "materialIssues", "findings",
] as const;
const MATERIAL_KEYS = [
  "code", "severity", "lane", "message", "evidence", "requiredAction",
] as const;
const FINDING_KEYS = ["code", "severity", "lane", "message", "evidence"] as const;
const RECEIPT_KEYS = [
  "schemaVersion", "changedPlan", "addressedIssueCodes", "deferredIssueCodes", "summary",
] as const;
const CODE_PATTERN = /^[A-Z0-9][A-Z0-9_-]+$/;
const JSON_FENCE_PATTERN = /^```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```$/i;

function strictJsonPayload(text: string): string {
  const trimmed = text.trim();
  if (!trimmed.startsWith("```")) return trimmed;
  const fenced = JSON_FENCE_PATTERN.exec(trimmed);
  if (!fenced) {
    throw new Error("response must be exactly one JSON object or one JSON code fence");
  }
  return fenced[1].trim();
}

function record(value: unknown, at: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${at} must be an object`);
  }
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[], at: string): void {
  const expected = new Set(keys);
  const extras = Object.keys(value).filter((key) => !expected.has(key));
  const missing = keys.filter((key) => !(key in value));
  if (extras.length || missing.length) {
    throw new Error(`${at} keys invalid; missing=${missing.join(",") || "none"} extra=${extras.join(",") || "none"}`);
  }
}

function stringValue(value: unknown, at: string, max = 2000): string {
  if (typeof value !== "string" || !value.trim() || value.length > max) {
    throw new Error(`${at} must be a non-empty string of at most ${max} characters`);
  }
  return value;
}

function codeValue(value: unknown, at: string): string {
  const code = stringValue(value, at, 64);
  if (code.length < 2 || !CODE_PATTERN.test(code)) {
    throw new Error(`${at} must be an uppercase stable identifier`);
  }
  return code;
}

function stringArray(value: unknown, at: string, max: number, allowEmpty = false): string[] {
  if (!Array.isArray(value) || value.length > max || (!allowEmpty && !value.length)) {
    throw new Error(`${at} must contain ${allowEmpty ? "0" : "1"}-${max} strings`);
  }
  return value.map((item, index) => stringValue(item, `${at}[${index}]`, 1000));
}

function materialIssue(value: unknown, index: number): ProducerMaterialIssue {
  const at = `materialIssues[${index}]`;
  const row = record(value, at);
  exactKeys(row, MATERIAL_KEYS, at);
  if (row.severity !== "major" && row.severity !== "critical") {
    throw new Error(`${at}.severity must be major or critical`);
  }
  return {
    code: codeValue(row.code, `${at}.code`), severity: row.severity,
    lane: stringValue(row.lane, `${at}.lane`, 80),
    message: stringValue(row.message, `${at}.message`),
    evidence: stringArray(row.evidence, `${at}.evidence`, 20),
    requiredAction: stringValue(row.requiredAction, `${at}.requiredAction`),
  };
}

function finding(value: unknown, index: number): ProducerFinding {
  const at = `findings[${index}]`;
  const row = record(value, at);
  exactKeys(row, FINDING_KEYS, at);
  if (row.severity !== "info" && row.severity !== "minor") {
    throw new Error(`${at}.severity must be info or minor`);
  }
  return {
    code: codeValue(row.code, `${at}.code`), severity: row.severity,
    lane: stringValue(row.lane, `${at}.lane`, 80),
    message: stringValue(row.message, `${at}.message`),
    evidence: stringArray(row.evidence, `${at}.evidence`, 20),
  };
}

function reviewArrays(row: Record<string, unknown>): {
  materialIssues: ProducerMaterialIssue[]; findings: ProducerFinding[];
} {
  if (!Array.isArray(row.materialIssues) || row.materialIssues.length > 50) {
    throw new Error("materialIssues must be an array of at most 50 items");
  }
  if (!Array.isArray(row.findings) || row.findings.length > 100) {
    throw new Error("findings must be an array of at most 100 items");
  }
  return {
    materialIssues: row.materialIssues.map(materialIssue),
    findings: row.findings.map(finding),
  };
}

function enforceReviewSemantics(review: ProducerReview, expected?: ProducerReviewStage): void {
  if (expected && review.stage !== expected) throw new Error(`expected ${expected} review, got ${review.stage}`);
  if (review.verdict === "pass" && review.materialIssues.length) {
    throw new Error("pass verdict cannot contain materialIssues");
  }
  if (review.verdict !== "pass" && !review.materialIssues.length) {
    throw new Error(`${review.verdict} verdict requires at least one materialIssue`);
  }
  const codes = [...review.materialIssues, ...review.findings].map((item) => item.code);
  if (new Set(codes).size !== codes.length) throw new Error("review issue codes must be unique");
}

export function validateProducerReview(
  value: unknown,
  expected?: ProducerReviewStage,
): ProducerReview {
  const row = record(value, "producer review");
  exactKeys(row, REVIEW_KEYS, "producer review");
  if (row.schemaVersion !== PRODUCER_REVIEW_SCHEMA_VERSION) throw new Error("unsupported review schemaVersion");
  if (row.stage !== "cut" && row.stage !== "plan" && row.stage !== "rendered") {
    throw new Error("review stage is invalid");
  }
  if (row.verdict !== "pass" && row.verdict !== "revise" && row.verdict !== "block") {
    throw new Error("review verdict is invalid");
  }
  const review: ProducerReview = {
    schemaVersion: 1, stage: row.stage, verdict: row.verdict,
    summary: stringValue(row.summary, "summary"), ...reviewArrays(row),
  };
  enforceReviewSemantics(review, expected);
  return review;
}

export function parseProducerReview(text: string, expected?: ProducerReviewStage): ProducerReview {
  try {
    return validateProducerReview(JSON.parse(strictJsonPayload(text)), expected);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`invalid producer review JSON: ${detail}`);
  }
}

export function parseRevisionReceipt(text: string): ProducerRevisionReceipt {
  try {
    const row = record(JSON.parse(strictJsonPayload(text)), "revision receipt");
    exactKeys(row, RECEIPT_KEYS, "revision receipt");
    if (row.schemaVersion !== 1 || typeof row.changedPlan !== "boolean") {
      throw new Error("revision receipt schemaVersion/changedPlan is invalid");
    }
    return {
      schemaVersion: 1, changedPlan: row.changedPlan,
      addressedIssueCodes: receiptCodes(row.addressedIssueCodes, "addressedIssueCodes"),
      deferredIssueCodes: receiptCodes(row.deferredIssueCodes, "deferredIssueCodes"),
      summary: stringValue(row.summary, "summary"),
    };
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`invalid producer revision receipt JSON: ${detail}`);
  }
}

function receiptCodes(value: unknown, at: string): string[] {
  return stringArray(value, at, 50, true).map((code, index) => codeValue(code, `${at}[${index}]`));
}

export function validateRevisionReceipt(
  receipt: ProducerRevisionReceipt,
  review: ProducerReview,
): ProducerRevisionReceipt {
  const expected = new Set(review.materialIssues.map((issue) => issue.code));
  const addressed = new Set(receipt.addressedIssueCodes);
  const deferred = new Set(receipt.deferredIssueCodes);
  if (addressed.size !== receipt.addressedIssueCodes.length || deferred.size !== receipt.deferredIssueCodes.length) {
    throw new Error("revision receipt codes must be unique");
  }
  if ([...addressed].some((code) => deferred.has(code))) throw new Error("revision receipt code overlap");
  const reported = new Set([...addressed, ...deferred]);
  if ([...expected].some((code) => !reported.has(code)) || [...reported].some((code) => !expected.has(code))) {
    throw new Error(
      `revision receipt must account for every material issue exactly once; expected=${JSON.stringify([...expected])} reported=${JSON.stringify([...reported])}`,
    );
  }
  if (receipt.changedPlan !== (addressed.size > 0)) {
    throw new Error("changedPlan must match whether issues were addressed");
  }
  return receipt;
}
