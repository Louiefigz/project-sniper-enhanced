import { assertPlanVisualSources } from "@/lib/producer/visual-source-policy";
import { readFileSync, rmSync } from "fs";
import { createHash } from "crypto";
import type { ProducerReview } from "../auto-edit/review-contract";
import { reconcileGraphicIds, type EditPlan } from "@/lib/producer/edit-plan";
import { assertSurgicalPlanChange } from "@/lib/producer/surgical-edit";
import { runSurgicalEditCritic, type SurgicalCriticInput } from "./critic";
import { atomicWriteFileSync } from "@/lib/server/atomic-file";
import {
  commitPlanRefitReceipt,
  discardPendingPlanRefit,
  recoverPendingPlanRefit,
} from "../../_lib/plan-refit-receipt";
import {
  refitPlanTransaction,
  type PlanRefitReceipt,
} from "../../_lib/plan-refit-transaction";
import {
  runSurgicalGovernance,
  type SurgicalGovernanceInput,
  type SurgicalGovernanceResult,
} from "./surgical-governance";
import { writeTemplateUsageApproval } from "@/lib/server/template-usage-approval";
import {
  assertPromotedCandidateCurrent,
  isPromotionRecoverySettled,
  promoteCandidateUnderLease,
  restorePromotedCandidate,
  type PromotedPlanSnapshot,
} from "./promotion-recovery";
import {
  compileTypedCompatibilityEdit,
  type TypedCompatibilityEdit,
} from "./typed-compatibility-edit";
import { assertStreamActive } from "./stream-cancellation";
import { assertSurgicalReviewCurrent as assertReviewCurrent } from
  "./surgical-review-current";
import {
  restoreFile,
  runRecoveryActions,
  type FileBackup,
} from "./finalize-file-backup";
import { assertPalmierWorkspaceAbsent } from
  "./palmier-workspace-classification";
import {
  SURGICAL_REVIEW_FILE,
  surgicalReviewMarkerPath,
  writeSurgicalReviewMarker,
} from "./surgical-review-marker";
import {
  commitFinalizeRefit,
  promoteFinalizeSidecars,
} from "./finalize-sidecars";
import { reconcileCaptionPlanAuthority } from "./caption-plan-authority-v1";
import {
  publishFinalizeRevisionShadow,
  type ProducerRevisionShadowResult,
} from "./finalize-revision-shadow";
import { runTypedCompatibilityShadowSync } from
  "@/lib/server/producer-revision-shadow";
export { SURGICAL_REVIEW_FILE, beginSurgicalReview } from "./surgical-review-marker";
export function assertSurgicalReviewCurrent(planPath: string): void {
  assertReviewCurrent(planPath, SURGICAL_REVIEW_FILE);
}
export interface FinalizeSurgicalEditInput extends Omit<SurgicalCriticInput, "changedFields"> {
  originalPlanText: string;
  signal?: AbortSignal;
  parentPlanHash: string;
  requestId?: string;
  submittedAt?: string;
  authorityPlanPath?: string;
}

interface FinalizeGovernanceResult {
  warnings: string[];
  cutApproval?: { path: string; text: string };
  verdict?: SurgicalGovernanceResult["verdict"];
  templateUsage?: SurgicalGovernanceResult["templateUsage"];
}

export interface FinalizeSurgicalEditDependencies {
  governance?: (input: SurgicalGovernanceInput) => Promise<FinalizeGovernanceResult>;
  critic?: (input: SurgicalCriticInput) => Promise<ProducerReview>;
  afterPromotion?: (authorityPlanPath: string) => void | Promise<void>;
  afterSidecars?: (authorityPlanPath: string) => void | Promise<void>;
  templateApproval?: typeof writeTemplateUsageApproval;
  cutApprovalWriter?: typeof atomicWriteFileSync;
  refit?: typeof refitPlanTransaction;
  commitRefit?: typeof commitPlanRefitReceipt;
  revisionShadow?: typeof runTypedCompatibilityShadowSync;
}

export interface FinalizeSurgicalEditResult {
  changedFields: string[];
  review: ProducerReview;
  refit: PlanRefitReceipt | null;
  typedCompatibility?: TypedCompatibilityEdit;
  revisionShadow?: ProducerRevisionShadowResult;
}

function clearSurgicalReview(input: FinalizeSurgicalEditInput): void {
  const authority = input.authorityPlanPath ?? input.planPath;
  if (input.planPath !== authority) rmSync(input.planPath, { force: true });
  rmSync(surgicalReviewMarkerPath(input.dir), { force: true });
}

export function rollbackSurgicalEdit(input: FinalizeSurgicalEditInput): void {
  if (isPromotionRecoverySettled(input)) return;
  const authority = input.authorityPlanPath ?? input.planPath;
  if (input.planPath === authority) atomicWriteFileSync(authority, input.originalPlanText);
  clearSurgicalReview(input);
}

function parsedPlan(text: string, label: string): Record<string, unknown> {
  const value = JSON.parse(text) as unknown;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be a JSON object`);
  }
  return value as Record<string, unknown>;
}

function normalizePlan(planPath: string): Record<string, unknown> {
  const parsed = parsedPlan(readFileSync(planPath, "utf8"), "edited plan");
  assertPlanVisualSources(parsed);
  const graphics = reconcileGraphicIds(parsed as EditPlan).plan;
  const captions = reconcileCaptionPlanAuthority(graphics).plan;
  atomicWriteFileSync(planPath, `${JSON.stringify(captions, null, 1)}\n`);
  return captions as Record<string, unknown>;
}

/** Increment the bookkeeping version before refit receipts bind child bytes. */
function bumpPlanVersion(planPath: string, before: Record<string, unknown>): void {
  const current = parsedPlan(readFileSync(planPath, "utf8"), "edited plan");
  const next = { ...current, planVersion: (Number(before.planVersion) || 0) + 1 };
  atomicWriteFileSync(planPath, `${JSON.stringify(next, null, 1)}\n`);
}

interface FinalizeState {
  refit: PlanRefitReceipt | null;
  cutApprovalBackup: FileBackup | null;
  templateApprovalBackup: FileBackup | null;
  refitReceiptBackup: FileBackup | null;
  promoted: PromotedPlanSnapshot | null;
}

interface ReviewedCandidate {
  childBytes: Buffer;
  childHash: string;
  changedFields: string[];
  refit: PlanRefitReceipt | null;
  governance: FinalizeGovernanceResult;
  review: ProducerReview;
  typedCompatibility: TypedCompatibilityEdit | null;
}

type PreparedCandidate = Omit<ReviewedCandidate, "governance" | "review">;

async function prepareCandidate(
  input: FinalizeSurgicalEditInput,
  dependencies: FinalizeSurgicalEditDependencies,
): Promise<PreparedCandidate> {
  recoverPendingPlanRefit(input.dir, input.authorityPlanPath ?? input.planPath);
  const before = parsedPlan(input.originalPlanText, "original plan");
  const after = normalizePlan(input.planPath);
  const changedFields = assertSurgicalPlanChange(before, after, input.scope);
  const typedCompatibility = compileTypedCompatibilityEdit(
    before as EditPlan, after as EditPlan,
  );
  bumpPlanVersion(input.planPath, before);
  const refit = input.scope.lanes.includes("cuts")
    ? await (dependencies.refit ?? refitPlanTransaction)({
      planPath: input.planPath, oldPlanText: input.originalPlanText,
      source: "surgical-cut", receiptDir: input.dir, deferReceiptCommit: true,
    }) : null;
  const childBytes = readFileSync(input.planPath);
  const childHash = createHash("sha256").update(childBytes).digest("hex");
  return { changedFields, refit, typedCompatibility, childBytes, childHash };
}

async function reviewCandidate(
  input: FinalizeSurgicalEditInput,
  dependencies: FinalizeSurgicalEditDependencies,
  prepared: PreparedCandidate,
): Promise<ReviewedCandidate> {
  const governance = await (dependencies.governance ?? runSurgicalGovernance)({
    dir: input.dir, planPath: input.planPath,
    manifestPath: input.manifestPath, transcriptsDir: input.transcriptsDir,
    scope: input.scope,
  });
  const review = await (dependencies.critic ?? runSurgicalEditCritic)({
    ...input, changedFields: prepared.changedFields,
  });
  if (review.verdict === "pass" && !review.materialIssues.length) {
    return { ...prepared, governance, review };
  }
  const issue = review.materialIssues[0];
  throw new Error(`independent critic rejected the edit: ${issue?.message ?? review.summary}`);
}

async function publishCandidate(
  input: FinalizeSurgicalEditInput,
  dependencies: FinalizeSurgicalEditDependencies,
  candidate: ReviewedCandidate,
  state: FinalizeState,
): Promise<FinalizeSurgicalEditResult> {
  assertStreamActive(input.signal);
  assertPalmierWorkspaceAbsent(input.dir);
  state.promoted = promoteCandidateUnderLease(input, {
    bytes: candidate.childBytes, hash: candidate.childHash,
  }, (snapshot) => { state.promoted = snapshot; });
  const authority = state.promoted.authorityPath;
  await dependencies.afterPromotion?.(authority);
  assertStreamActive(input.signal);
  assertPalmierWorkspaceAbsent(input.dir);
  assertPromotedCandidateCurrent(state.promoted);
  promoteFinalizeSidecars({
    producerDir: input.dir, planPath: authority,
    manifestPath: input.manifestPath, transcriptsDir: input.transcriptsDir,
    governance: candidate.governance, state,
    templateApproval: dependencies.templateApproval,
    cutApprovalWriter: dependencies.cutApprovalWriter,
  });
  await dependencies.afterSidecars?.(authority);
  assertStreamActive(input.signal);
  assertPalmierWorkspaceAbsent(input.dir);
  assertPromotedCandidateCurrent(state.promoted);
  const planHash = state.promoted.childHash;
  writeSurgicalReviewMarker(input.dir, {
    schemaVersion: 1, status: "approved", scope: input.scope, planHash,
    changedFields: candidate.changedFields, gateWarnings: candidate.governance.warnings,
    critic: candidate.review, ...(candidate.typedCompatibility
      ? { typedCompatibility: candidate.typedCompatibility } : {}),
  });
  if (authority !== input.planPath) rmSync(input.planPath, { force: true });
  state.refit = commitFinalizeRefit({
    dir: input.dir, authorityPath: authority, receipt: state.refit,
    state, commit: dependencies.commitRefit,
  });
  const revisionShadow = candidate.typedCompatibility
    ? publishFinalizeRevisionShadow(input,
      { ...candidate, typedCompatibility: candidate.typedCompatibility },
      dependencies.revisionShadow) : undefined;
  return {
    changedFields: candidate.changedFields, review: candidate.review, refit: state.refit,
    ...(candidate.typedCompatibility
      ? { typedCompatibility: candidate.typedCompatibility } : {}),
    ...(revisionShadow ? { revisionShadow } : {}),
  };
}

function recoverFinalizeFailure(
  input: FinalizeSurgicalEditInput,
  state: FinalizeState,
  trigger: unknown,
): never {
  const recoveryError = runRecoveryActions([
    () => {
      if (state.promoted) restorePromotedCandidate(input, state.promoted, trigger);
      if (state.promoted) clearSurgicalReview(input);
      else rollbackSurgicalEdit(input);
    },
    () => restoreFile(state.cutApprovalBackup),
    () => restoreFile(state.templateApprovalBackup),
    () => restoreFile(state.refitReceiptBackup),
    () => { if (state.refit) discardPendingPlanRefit(input.dir); },
  ]);
  if (recoveryError) throw recoveryError;
  throw trigger;
}

export async function finalizeSurgicalEdit(
  input: FinalizeSurgicalEditInput,
  dependencies: FinalizeSurgicalEditDependencies = {},
): Promise<FinalizeSurgicalEditResult> {
  const state: FinalizeState = {
    refit: null,
    cutApprovalBackup: null,
    templateApprovalBackup: null,
    refitReceiptBackup: null,
    promoted: null,
  };
  try {
    assertStreamActive(input.signal);
    const prepared = await prepareCandidate(input, dependencies);
    state.refit = prepared.refit;
    assertStreamActive(input.signal);
    const reviewed = await reviewCandidate(input, dependencies, prepared);
    assertStreamActive(input.signal);
    return await publishCandidate(input, dependencies, reviewed, state);
  } catch (error) {
    return recoverFinalizeFailure(input, state, error);
  }
}
