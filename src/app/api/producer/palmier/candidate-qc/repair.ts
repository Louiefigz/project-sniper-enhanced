import { randomUUID } from "node:crypto";
import { existsSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { runPalmierNativeEdit } from "../../ai-edit/palmier-native-runner";
import { PALMIER_NATIVE_LANES } from "../../ai-edit/palmier-native-prompt";
import type { PalmierNativeQcAuthority } from "../../ai-edit/palmier-native-authority";
import type { SurgicalEditLane } from "@/lib/producer/surgical-edit";
import { atomicWriteJsonSync } from "@/lib/server/atomic-file";
import { candidateReceipt, nativeQcReceipt } from "@/lib/server/palmier-candidate-qc";
import { nativeRepairAuthority } from "./reviewer";

type Reject = (reasonPath: string) => Promise<Record<string, unknown>>;

export interface ReplacementCandidateInput {
  dir: string;
  authority: PalmierNativeQcAuthority;
  error: Error;
  reject: Reject;
  signal?: AbortSignal;
}

interface RepairEvidence {
  originalRequest: string;
  lanes: SurgicalEditLane[];
  issues: unknown[];
  reviewArtifacts: string[];
  reason: Record<string, unknown>;
}

function reviewEvidence(authority: PalmierNativeQcAuthority): {
  issues: unknown[];
  paths: string[];
} {
  const dir = path.join(
    authority.ctx.dir, ".sniper-learning", "runs", authority.captureId, "candidate-qc",
  );
  if (!existsSync(dir)) return { issues: [], paths: [] };
  const paths = readdirSync(dir).filter((name) => name.endsWith(".json"))
    .map((name) => path.join(dir, name));
  const issues = paths.flatMap((item) => {
    try {
      const value = JSON.parse(readFileSync(item, "utf8")) as {
        lens?: unknown; review?: { materialIssues?: unknown };
      };
      return Array.isArray(value.review?.materialIssues)
        ? [{ lens: value.lens, materialIssues: value.review.materialIssues }] : [];
    } catch { return []; }
  });
  return { issues, paths };
}

function auditIssues(dir: string): unknown[] {
  try {
    const value = JSON.parse(readFileSync(path.join(dir, "palmier.native-audit.json"), "utf8")) as {
      checks?: unknown;
    };
    return Array.isArray(value.checks)
      ? value.checks.filter((item) => item && typeof item === "object"
        && (item as Record<string, unknown>).status !== "pass") : [];
  } catch { return []; }
}

function repairEvidence(
  dir: string,
  authority: PalmierNativeQcAuthority,
  error: Error,
): RepairEvidence {
  const candidate = candidateReceipt(dir);
  const qc = nativeQcReceipt(dir);
  const receiptAuthority = qc?.authority as Record<string, unknown> | undefined;
  const governed = nativeRepairAuthority(authority);
  const reviews = reviewEvidence(authority);
  const issues = [...auditIssues(dir), ...reviews.issues];
  if (!issues.length) issues.push({ source: "candidate-qc", message: error.message });
  if (!candidate || typeof candidate.timelineId !== "string"
      || typeof candidate.fingerprint !== "string") {
    throw new Error("Rejected candidate disappeared before governed repair archival.");
  }
  const lanes = governed.lanes.filter((item): item is SurgicalEditLane =>
    PALMIER_NATIVE_LANES.includes(item as (typeof PALMIER_NATIVE_LANES)[number]),
  );
  if (!lanes.length || lanes.length !== governed.lanes.length) {
    throw new Error("Rejected candidate has an unsupported repair lane.");
  }
  return {
    originalRequest: governed.request,
    lanes,
    issues,
    reviewArtifacts: reviews.paths,
    reason: {
      schemaVersion: 1,
      reason: error.message,
      sourceCandidate: {
        timelineId: candidate.timelineId,
        fingerprint: candidate.fingerprint,
      },
      originalRequest: { text: governed.request, hash: authority.requestHash },
      controllerLanes: governed.lanes,
      inputAuthorityDigest: typeof receiptAuthority?.inputDigest === "string"
        ? receiptAuthority.inputDigest : null,
      issues,
      reviewArtifacts: reviews.paths,
    },
  };
}

function repairRequest(evidence: RepairEvidence): string {
  const value = JSON.stringify({
    task: "Create a new replacement candidate from the preserved canonical parent. Do not edit or approve the rejected candidate.",
    originalOperatorRequest: evidence.originalRequest,
    requiredFixesFromCandidateQc: evidence.issues,
    constraint: "Satisfy the original request while correcting only the listed QC defects in the same controller lanes.",
  });
  if (value.length > 4_000) {
    throw new Error("Candidate QC findings exceed the governed repair-request limit.");
  }
  return value;
}

/** Reject/archive through pinned Python and verify the preserved parent proof. */
export async function rejectFailedCandidate(
  dir: string,
  authority: PalmierNativeQcAuthority,
  error: Error,
  reject: Reject,
): Promise<{ archivePath: string; evidence: RepairEvidence }> {
  const evidence = repairEvidence(dir, authority, error);
  const reasonPath = path.join(dir, `.palmier-native-repair.${randomUUID()}.json`);
  try {
    writeFileSync(reasonPath, `${JSON.stringify(evidence.reason, null, 2)}\n`, {
      flag: "wx", mode: 0o600,
    });
    const rejected = await reject(reasonPath);
    if (rejected.status !== "candidate-rejected"
        || typeof rejected.archivePath !== "string" || !path.isAbsolute(rejected.archivePath)) {
      throw new Error("Pinned candidate rejection did not return a durable archive.");
    }
    const rejectedCandidate = candidateReceipt(dir);
    const parent = rejected.parent as Record<string, unknown> | undefined;
    const source = evidence.reason.sourceCandidate as Record<string, unknown>;
    const restored = rejectedCandidate?.status === "qc-rejected"
      && rejectedCandidate.timelineId === source.timelineId
      && rejectedCandidate.fingerprint === source.fingerprint
      && typeof parent?.timelineId === "string"
      && typeof parent.fingerprint === "string";
    if (!restored) {
      throw new Error("Pinned candidate rejection did not preserve the rejected candidate and verified parent.");
    }
    return { archivePath: rejected.archivePath, evidence };
  } finally {
    rmSync(reasonPath, { force: true });
  }
}

/** A bounded repair is a new governed candidate, never an in-place mutation. */
export async function createReplacementCandidate(
  input: ReplacementCandidateInput,
): Promise<void> {
  const { dir, authority, error, reject, signal } = input;
  const rejected = await rejectFailedCandidate(dir, authority, error, reject);
  const replacement = await runPalmierNativeEdit({
    dir,
    request: repairRequest(rejected.evidence),
    scope: { lanes: rejected.evidence.lanes },
  }, {}, { signal });
  atomicWriteJsonSync(path.join(rejected.archivePath, "superseded-by.json"), {
    schemaVersion: 1, status: "superseded", at: new Date().toISOString(), replacement,
  });
}
