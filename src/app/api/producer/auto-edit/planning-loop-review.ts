import path from "path";
import { randomUUID } from "node:crypto";
import type { AutoEditAuthoritySnapshot } from "@/lib/server/auto-edit-authority-snapshot";
import type { AutoEditJob } from "@/lib/server/auto-edit-job-store";
import { persistCriticObservations } from "@/lib/server/auto-edit-observations";
import { planningRoundDir } from "@/lib/server/auto-edit-quality-artifacts";
import type { ProducerReviewResult } from "./brain-review-runner";
import {
  assertPlanReviewPacketDestination,
  bindPlanReviewPacket,
  buildPlanReviewPacket,
  validatePlanReviewPacketRef,
  writePlanReviewPacketExclusive,
  type PlanReviewPacketRef,
} from "./plan-review-packet";
import {
  gateBundleOperatorIntent,
  type GateBundleInput,
  type GateBundleVerdict,
} from "./planning-gates";
import type { PlanningLoopDependencies } from "./planning-loop";
import type { ProducerMaterialIssue, ProducerReview } from "./review-contract";
import { AutoEditError } from "./stream";
import { cutApprovalPath } from "./cut-approval";
import { templateUsageHistoryPath } from "@/lib/server/template-usage-history";

interface PlanningRoundArtifactInput {
  job: AutoEditJob;
  round: number;
  gates: GateBundleVerdict;
  result: ProducerReviewResult;
  authority: AutoEditAuthoritySnapshot;
  packet: PlanReviewPacketRef;
}

interface PlanningRoundInput {
  job: AutoEditJob;
  round: number;
  gates: GateBundleVerdict;
  authority: AutoEditAuthoritySnapshot;
}

interface PlanningGateFailureArtifactInput extends PlanningRoundInput {
  packet: PlanReviewPacketRef;
}

export function requiredPlanningHash(hash: string | undefined, label: string): string {
  if (!hash) throw new AutoEditError(`cannot review missing ${label}`);
  return hash;
}

export function planningGateInput(job: AutoEditJob): GateBundleInput {
  const { ctx } = job;
  if (!ctx.templateUsage) throw new AutoEditError("template usage authority is missing");
  const reference = ctx.intent?.reference && ctx.referenceStudy
    ? { profilePath: ctx.referenceStudy.profilePath, intent: ctx.intent.reference }
    : undefined;
  return {
    planPath: ctx.planPath,
    manifestPath: ctx.manifestPath,
    transcriptsDir: ctx.transcriptsDir,
    cutApprovalPath: cutApprovalPath(ctx),
    templateUsagePath: templateUsageHistoryPath(ctx),
    templateUsageDigest: ctx.templateUsage.digest,
    operatorIntent: gateBundleOperatorIntent(ctx.scope, ctx.intent),
    reference,
  };
}

function gateIssues(verdict: GateBundleVerdict): ProducerMaterialIssue[] {
  const failures = verdict.errors.length
    ? verdict.errors
    : verdict.ok ? [] : [{ gate: "plan_lint" as const, message: "gate bundle failed without diagnostics" }];
  return failures.map((finding, index) => ({
    code: `GATE_${finding.gate.toUpperCase()}_${index + 1}`,
    severity: "critical" as const,
    lane: finding.gate,
    message: finding.message,
    evidence: [`deterministic gate ${finding.gate} failed`],
    requiredAction: `Revise the plan so ${finding.gate} passes, or defer if this is a system defect.`,
  }));
}

/** Controller-owned critique used only when deterministic gates already failed. */
export function planningGateFailureReview(
  gates: GateBundleVerdict,
): ProducerReview {
  if (gates.ok) throw new AutoEditError("clean planning gates require an independent critic");
  return {
    schemaVersion: 1,
    stage: "plan",
    verdict: "revise",
    summary: "Deterministic planning gates failed; independent editorial critique is deferred until the gates pass.",
    materialIssues: gateIssues(gates),
    findings: [],
  };
}

export function combinePlanningReview(
  review: ProducerReview,
  gates: GateBundleVerdict,
): ProducerReview {
  const materialIssues = [...gateIssues(gates), ...review.materialIssues];
  if (!materialIssues.length) return review;
  return {
    ...review,
    verdict: review.verdict === "block" ? "block" : "revise",
    summary: gates.ok ? review.summary : `Deterministic gates failed. ${review.summary}`,
    materialIssues,
  };
}

export function planningReviewArtifactPath(
  job: AutoEditJob,
  round: number,
  name: string,
): string {
  return path.join(planningRoundDir(job.ctx.dir, job.artifactToken ?? job.token, round), name);
}

export function persistPlanningReviewInputs(
  input: PlanningRoundInput,
  deps: PlanningLoopDependencies,
): PlanReviewPacketRef {
  const { job, round, gates, authority } = input;
  const packetPath = planningReviewArtifactPath(
    job, round, path.join(`critic-input-${randomUUID()}`, "plan-review-packet.json"),
  );
  assertPlanReviewPacketDestination(job.ctx, packetPath, round);
  const packet = buildPlanReviewPacket(job.ctx, round, gates, authority);
  const persistedPath = writePlanReviewPacketExclusive(packetPath, packet);
  const packetRef = bindPlanReviewPacket(persistedPath, packet);
  validatePlanReviewPacketRef(job.ctx, round, packetRef);
  deps.writeJson(planningReviewArtifactPath(job, round, "planning-gates.json"), {
    schemaVersion: 1,
    stage: "plan-gates",
    round,
    inputAuthority: authority,
    inputPacket: packetRef,
    gates,
  });
  return packetRef;
}

/** Persist the exact machine critique before launching the isolated revision writer. */
export function persistPlanningGateFailureRound(
  input: PlanningGateFailureArtifactInput,
  deps: PlanningLoopDependencies,
): { path: string; review: ProducerReview } {
  const { job, round, gates, authority, packet } = input;
  const review = planningGateFailureReview(gates);
  const reviewPath = deps.writeJson(planningReviewArtifactPath(job, round, "plan-review.json"), {
    schemaVersion: 1,
    stage: "plan",
    round,
    reviewSource: "deterministic-gates",
    inputAuthority: authority,
    inputPacket: packet,
    provider: null,
    ms: 0,
    review,
  });
  return { path: reviewPath, review };
}

export function persistPlanningRound(
  input: PlanningRoundArtifactInput,
  deps: PlanningLoopDependencies,
): string {
  const { job, round, gates, result, authority, packet } = input;
  const reviewPath = deps.writeJson(planningReviewArtifactPath(job, round, "plan-review.json"), {
    schemaVersion: 1,
    stage: "plan",
    round,
    inputAuthority: authority,
    inputPacket: packet,
    provider: result.provider,
    ms: result.ms,
    review: combinePlanningReview(result.review, gates),
  });
  persistCriticObservations({
    ctx: job.ctx, artifactPath: reviewPath, review: result.review,
    namespace: `planning-a${job.attempts}-r${round}`,
  });
  return reviewPath;
}
