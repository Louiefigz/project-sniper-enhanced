import { createHash } from "node:crypto";
import type { PipelineRuntime } from "./pipeline";
import {
  candidateReceipt,
} from "@/lib/server/palmier-candidate-qc";
import {
  classifyPalmierWorkspace,
  type PalmierWorkspaceClassification,
} from "../ai-edit/palmier-native-stream";
import {
  runPalmierNativeEdit,
  type PalmierNativeRunOptions,
} from "../ai-edit/palmier-native-runner";
import type { PalmierNativePromptInput } from "../ai-edit/palmier-native-prompt";
import type { PalmierNativeResult } from "../ai-edit/palmier-native-contract";
import {
  promoteCandidate,
  runCandidateQc,
} from "../palmier/candidate-qc/runner";
import {
  selectPalmierPrimaryBuild,
  type PalmierPrimaryBuild,
} from "./palmier-primary-selection";

export {
  selectPalmierPrimaryBuild,
  type PalmierPrimaryBuild,
  type PalmierPrimaryLimitation,
} from "./palmier-primary-selection";

type NativeEdit = (
  input: PalmierNativePromptInput,
  options: PalmierNativeRunOptions,
) => Promise<PalmierNativeResult>;

interface PalmierPrimaryDependencies {
  classify?: (dir: string) => PalmierWorkspaceClassification;
  candidate?: typeof candidateReceipt;
  nativeEdit?: NativeEdit;
  qc?: (dir: string, send: PipelineRuntime["io"]["send"]) => Promise<Record<string, unknown>>;
  promote?: (dir: string) => Promise<Record<string, unknown>>;
}

const DEFAULT_DEPS: Required<PalmierPrimaryDependencies> = {
  classify: classifyPalmierWorkspace,
  candidate: candidateReceipt,
  nativeEdit: (input, options) => runPalmierNativeEdit(input, {}, options),
  qc: (dir, send) => runCandidateQc(dir, send),
  promote: (dir) => promoteCandidate(dir),
};

export class PalmierPrimaryError extends Error {
  constructor(message: string, readonly code: string) {
    super(message);
  }
}

function hashRequest(request: string): string {
  return createHash("sha256").update(request, "utf8").digest("hex");
}

function candidatePhase(
  run: PipelineRuntime,
  candidate: Record<string, unknown> | null,
  requestHash: string,
): "new" | "pending" | "approved" | "promoted" {
  if (!candidate || ["superseded-manual", "discarded", "qc-rejected"]
    .includes(String(candidate.status))) return "new";
  if (candidate.requestHash !== requestHash) {
    throw new PalmierPrimaryError(
      "Another governed Palmier candidate is already present. Resolve or discard it before starting this initial edit.",
      "PALMIER_NATIVE_CANDIDATE_CONFLICT",
    );
  }
  const resumed = run.job.attempts > 1;
  if (!resumed && candidate.status !== "promoted") {
    throw new PalmierPrimaryError(
      "A matching Palmier candidate is waiting. Resume the interrupted edit instead of starting a second candidate.",
      "PALMIER_NATIVE_RESUME_REQUIRED",
    );
  }
  if (candidate.status === "promoted") return resumed ? "promoted" : "new";
  if (candidate.status === "qc-approved") return "approved";
  if (["staged", "edited"].includes(String(candidate.status))) return "pending";
  throw new PalmierPrimaryError(
    `Palmier candidate ${String(candidate.status)} must be resolved before Auto Edit can continue.`,
    "PALMIER_NATIVE_CANDIDATE_UNRESOLVED",
  );
}

function approvedTimeline(
  promotion: Record<string, unknown>,
  expected: string,
): string {
  const approved = promotion.approvedHead;
  const timelineId = approved && typeof approved === "object" && !Array.isArray(approved)
    ? (approved as Record<string, unknown>).timelineId : undefined;
  if (promotion.status !== "candidate-promoted" || timelineId !== expected) {
    throw new PalmierPrimaryError(
      "Palmier promotion did not bind the approved head to the exact editable candidate.",
      "PALMIER_NATIVE_PROMOTION_MISMATCH",
    );
  }
  return timelineId as string;
}

function advanceToCandidate(run: PipelineRuntime, result: PalmierNativeResult): void {
  run.job = run.io.advance({
    checkpoint: "plan_reviewed", phase: "validating",
    message: `Editable Palmier candidate ${result.timelineId} passed deterministic planning gates and two fresh plan reviews.`,
    planningRound: 2, planningRoundsRequired: 2, planningCleanRounds: 2,
  });
  run.io.send({
    event: "palmier_candidate_ready", mode: "palmier-native-initial",
    timelineId: result.timelineId, fingerprint: result.fingerprint,
    operationCount: result.operationCount, editable: true,
  });
}

async function buildCandidate(
  run: PipelineRuntime,
  selection: Extract<PalmierPrimaryBuild, { kind: "native" }>,
  deps: Required<PalmierPrimaryDependencies>,
): Promise<PalmierNativeResult> {
  run.job = run.io.advance({
    checkpoint: "authoring", phase: "authoring",
    message: "Claude is planning the first editable Palmier timeline from the visible source view.",
  });
  const result = await deps.nativeEdit(selection.input, {
    planReviewsRequired: 2,
    keepCandidateActive: true,
    onEvent: run.io.send,
  });
  advanceToCandidate(run, result);
  return result;
}

async function approveCandidate(
  run: PipelineRuntime,
  timelineId: string,
  phase: "pending" | "approved",
  deps: Required<PalmierPrimaryDependencies>,
): Promise<Record<string, unknown>> {
  run.job = run.io.advance({
    checkpoint: "quality_check", phase: "quality_check",
    message: "Exporting and reviewing the exact editable Palmier candidate before promotion.",
  });
  if (phase === "pending") await deps.qc(run.job.ctx.dir, run.io.send);
  const promotion = await deps.promote(run.job.ctx.dir);
  approvedTimeline(promotion, timelineId);
  return promotion;
}

export async function runPalmierPrimaryAutoEdit(
  run: PipelineRuntime,
  dependencies: PalmierPrimaryDependencies = {},
): Promise<boolean> {
  const deps = { ...DEFAULT_DEPS, ...dependencies };
  const selected = selectPalmierPrimaryBuild(run.job.ctx, deps.classify);
  if (selected.kind === "legacy") return false;
  if (selected.kind === "governed-plan") {
    run.io.send({
      event: "palmier_governed_plan_selected",
      requiredLanes: selected.requiredLanes,
      message: selected.message,
    });
    return false;
  }
  if (selected.kind === "blocked") {
    run.io.send({ event: "palmier_primary_blocked", ...selected });
    throw new PalmierPrimaryError(selected.message, selected.code);
  }
  run.io.send({
    event: "palmier_primary_selected", mode: "palmier-native-initial",
    editable: true, planReviewsRequired: 2, limitations: selected.limitations,
  });
  const existing = deps.candidate(run.job.ctx.dir);
  const phase = candidatePhase(run, existing, hashRequest(selected.input.request));
  let timelineId = typeof existing?.timelineId === "string" ? existing.timelineId : "";
  if (phase === "promoted") {
    run.io.send({ event: "outputs", approved: true, editable: true,
      mode: "palmier-native-initial", timelineId, resumed: true });
    return true;
  }
  let approvalPhase: "pending" | "approved" = phase === "approved" ? "approved" : "pending";
  if (phase === "new") {
    const built = await buildCandidate(run, selected, deps);
    timelineId = built.timelineId;
    approvalPhase = "pending";
  } else {
    run.io.send({ event: "resume", stage: "palmier_candidate_qc", timelineId,
      message: "Resuming exact-timeline QC for the saved editable Palmier candidate." });
  }
  await approveCandidate(run, timelineId, approvalPhase, deps);
  run.io.send({
    event: "candidate_promoted", mode: "palmier-native-initial",
    timelineId, editable: true,
    message: "The exact edited timeline passed QC and is now both the Palmier working head and approved head.",
  });
  run.io.send({ event: "outputs", approved: true, editable: true,
    mode: "palmier-native-initial", timelineId });
  return true;
}
