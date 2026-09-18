import { randomUUID } from "node:crypto";
import { rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { persistNativeAuditObservations } from
  "@/lib/server/auto-edit-observations";
import {
  candidateReviewEvidence,
  requireCandidatePass,
  runCandidateReview,
  type CandidateQcAuthority,
  type CandidateQcFailure,
  type QcReviewer,
} from "./reviewer";

type Send = (event: Record<string, unknown>) => void;

export type CandidateQcCli = (
  dir: string,
  action: "prepare" | "audit" | "finalize" | "reject" | "promote",
  inputPath?: string,
  signal?: AbortSignal,
) => Promise<Record<string, unknown>>;

interface AttemptInput {
  dir: string;
  send: Send;
  payload: CandidateQcAuthority;
  cli: CandidateQcCli;
  review?: QcReviewer;
  signal?: AbortSignal;
}

function writeInput(dir: string, name: string, value: unknown): string {
  const destination = path.join(dir, `.${name}.${randomUUID()}.json`);
  writeFileSync(destination, `${JSON.stringify(value, null, 2)}\n`, {
    flag: "wx", mode: 0o600,
  });
  return destination;
}

async function deterministicAudit(input: AttemptInput): Promise<void> {
  input.send({ event: "candidate_qc_progress", step: "audit",
    message: "Running deterministic graph, render, audio, and frame checks." });
  const auditPath = path.join(input.dir, "palmier.native-audit.json");
  try {
    await input.cli(input.dir, "audit", undefined, input.signal);
  } catch (error) {
    persistNativeAuditObservations(
      input.payload.ctx, auditPath, `native-qc-${input.payload.captureId}`,
    );
    const repairable = error as Error & {
      candidateQcRepairable?: boolean; code?: number; status?: unknown;
      candidateQcFailure?: {
        lens: string; materialIssues: Record<string, unknown>[];
      };
      candidateQcEvidencePaths?: string[];
    };
    repairable.candidateQcRepairable = repairable.code === 65
      && repairable.status === "rejected";
    repairable.candidateQcFailure = {
      lens: "deterministic",
      materialIssues: [{ message: repairable.message }],
    };
    repairable.candidateQcEvidencePaths = [auditPath];
    throw repairable;
  }
  persistNativeAuditObservations(
    input.payload.ctx, auditPath, `native-qc-${input.payload.captureId}`,
  );
}

async function independentReviews(input: AttemptInput): Promise<string> {
  const evidence = candidateReviewEvidence(input.dir, input.payload);
  input.send({ event: "candidate_qc_progress", step: "rendered_reviews",
    message: "Running independent composition and editorial reviews in parallel against the exact export." });
  const reviewer = input.review ?? runCandidateReview;
  const reviews = await Promise.all([
    reviewer(input.dir, "composition", evidence, input.signal),
    reviewer(input.dir, "editorial", evidence, input.signal),
  ]);
  try {
    requireCandidatePass(reviews);
  } catch (reason) {
    const error = reason as Error & {
      candidateQcFailure?: CandidateQcFailure;
      candidateQcEvidencePaths?: string[];
    };
    error.candidateQcEvidencePaths = [evidence.exportPath, ...evidence.paths];
    throw error;
  }
  return writeInput(input.dir, "palmier-native-qc-reviews", {
    schemaVersion: 1, reviews,
  });
}

/** Export, audit, and independently review one exact candidate. */
export async function runCandidateQcAttempt(
  input: AttemptInput,
): Promise<Record<string, unknown>> {
  const contextPath = writeInput(
    input.dir, "palmier-native-qc-context", input.payload,
  );
  try {
    input.send({ event: "candidate_qc_progress", step: "prepare",
      message: "Reading and exporting the exact candidate; the parent will be restored afterward." });
    await input.cli(input.dir, "prepare", contextPath, input.signal);
    await deterministicAudit(input);
    const reviewsPath = await independentReviews(input);
    try {
      input.send({ event: "candidate_qc_progress", step: "approval",
        message: "Binding both passing reviews to the current candidate export." });
      return await input.cli(input.dir, "finalize", reviewsPath, input.signal);
    } finally {
      rmSync(reviewsPath, { force: true });
    }
  } finally {
    rmSync(contextPath, { force: true });
  }
}
