import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import type { AutoEditAuthoritySnapshot } from "@/lib/server/auto-edit-authority-snapshot";
import { stableAuthorityHash } from "@/lib/server/auto-edit-authority-snapshot";
import { fileSha256, type AutoEditJob } from "@/lib/server/auto-edit-job-store";
import {
  planningRoundDir,
  type AuditEvidenceAuthority,
  type HashedArtifactRef,
  type PlanningReviewEvidence,
} from "@/lib/server/auto-edit-quality-artifacts";
import type { AuditBOutcome } from "./chain";
import type { RenderedReviewEvidence } from "./rendered-review-prompt";
import type { ProducerReview } from "./review-contract";
import { AutoEditError } from "./stream";

interface AuditMachine {
  frames?: Array<{ path?: unknown }>;
}

export interface BoundRenderedEvidence {
  prompt: RenderedReviewEvidence;
  authority: AuditEvidenceAuthority;
}

export interface QualitySummaryReceipt {
  path: string;
  ref: HashedArtifactRef;
}

function requiredHash(filePath: string, label: string): string {
  const hash = fileSha256(filePath);
  if (!hash) throw new AutoEditError(`${label} is missing or unreadable: ${filePath}`);
  return hash;
}

export function artifactRef(filePath: string): HashedArtifactRef {
  return { path: filePath, hash: requiredHash(filePath, "QC evidence") };
}

function auditMachinePath(candidateDir: string, audit: AuditBOutcome): string {
  return typeof audit.event.machine === "string"
    ? audit.event.machine : path.join(candidateDir, "audit_report.json");
}

function auditReportPath(candidateDir: string, audit: AuditBOutcome): string {
  return typeof audit.event.report === "string"
    ? audit.event.report : path.join(candidateDir, "audit_report.md");
}

function framePaths(machinePath: string): string[] {
  try {
    const report = JSON.parse(readFileSync(machinePath, "utf8")) as AuditMachine;
    return (report.frames ?? []).flatMap((frame) =>
      typeof frame.path === "string" && frame.path && existsSync(frame.path) ? [frame.path] : []);
  } catch {
    return [];
  }
}

export function captureRenderedEvidence(
  candidatePath: string,
  candidateDir: string,
  audit: AuditBOutcome,
): BoundRenderedEvidence | null {
  const machinePath = auditMachinePath(candidateDir, audit);
  const reportPath = auditReportPath(candidateDir, audit);
  const frames = framePaths(machinePath);
  if (!existsSync(machinePath) || !existsSync(reportPath) || !frames.length) return null;
  const content = {
    candidateHash: requiredHash(candidatePath, "candidate"),
    assembledProofHash: requiredHash(`${candidatePath}.assembled.json`, "candidate assembly proof"),
    machine: artifactRef(machinePath),
    report: artifactRef(reportPath),
    frames: frames.map(artifactRef),
  };
  return {
    prompt: { auditReportPath: machinePath, framePaths: frames, finalPath: candidatePath },
    authority: { ...content, digest: stableAuthorityHash(content) },
  };
}

function json(filePath: string): Record<string, unknown> | null {
  try {
    const value: unknown = JSON.parse(readFileSync(filePath, "utf8"));
    return value && typeof value === "object" && !Array.isArray(value)
      ? value as Record<string, unknown> : null;
  } catch {
    return null;
  }
}

function nested(value: unknown, key: string): unknown {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)[key] : undefined;
}

function planningPacketRef(
  gates: Record<string, unknown>,
  review: Record<string, unknown>,
  round: number,
  authorityDigest: string,
): HashedArtifactRef | null {
  const left = nested(gates, "inputPacket");
  const right = nested(review, "inputPacket");
  if (!left || typeof left !== "object" || Array.isArray(left)
      || stableAuthorityHash(left) !== stableAuthorityHash(right)) return null;
  const row = left as Record<string, unknown>;
  if (typeof row.path !== "string" || typeof row.hash !== "string"
      || row.round !== round || row.authorityDigest !== authorityDigest) return null;
  try {
    const current = artifactRef(row.path);
    return current.hash === row.hash ? current : null;
  } catch {
    return null;
  }
}

function planningEvidenceAt(
  job: AutoEditJob,
  round: number,
  authority: AutoEditAuthoritySnapshot,
): PlanningReviewEvidence | null {
  const dir = planningRoundDir(job.ctx.dir, job.artifactToken ?? job.token, round);
  const gatesPath = path.join(dir, "planning-gates.json");
  const reviewPath = path.join(dir, "plan-review.json");
  const gates = json(gatesPath);
  const review = json(reviewPath);
  const packet = gates && review ? planningPacketRef(gates, review, round, authority.digest) : null;
  if (gates?.stage !== "plan-gates" || gates.round !== round
      || nested(gates.inputAuthority, "digest") !== authority.digest
      || nested(gates.gates, "ok") !== true
      || review?.stage !== "plan" || review.round !== round
      || nested(review.inputAuthority, "digest") !== authority.digest
      || nested(review.review, "verdict") !== "pass"
      || !authority.planHash || !packet) return null;
  return {
    round,
    authorityDigest: authority.digest,
    planHash: authority.planHash,
    packet,
    gates: artifactRef(gatesPath),
    review: artifactRef(reviewPath),
  };
}

export function collectPlanningReviewEvidence(
  job: AutoEditJob,
  authority: AutoEditAuthoritySnapshot,
): PlanningReviewEvidence[] {
  const required = job.planningRoundsRequired ?? 0;
  const rounds = Array.from({ length: job.planningRound ?? 0 }, (_, index) => index + 1)
    .flatMap((round) => {
      const item = planningEvidenceAt(job, round, authority);
      return item ? [item] : [];
    });
  const selected = rounds.slice(-required);
  if (required < 1 || selected.length !== required) {
    throw new AutoEditError(`QC approval requires ${required || "the expected"} hash-bound clean planning review(s)`);
  }
  return selected;
}

export function qualitySummaryValue(
  job: AutoEditJob,
  authority: AutoEditAuthoritySnapshot,
  evidence: AuditEvidenceAuthority,
  audit: AuditBOutcome,
  aggregate: ProducerReview,
  reviewRefs: HashedArtifactRef[],
): Record<string, unknown> {
  return {
    schemaVersion: 1,
    stage: "quality-summary",
    qcRound: job.qcRound,
    inputAuthority: authority,
    evidence,
    audit,
    aggregate,
    reviews: reviewRefs,
  };
}
