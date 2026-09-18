import path from "node:path";
import { existsSync, lstatSync, realpathSync } from "node:fs";
import {
  acquireProjectMutationLease,
  type ProjectMutationLease,
} from "@/lib/server/project-mutation-lease";
import { producerRun } from "@/lib/server/producer-run-registry";
import { autoEditJobPath, parseAutoEditJobRecord } from "@/lib/server/auto-edit-job-persistence";
import type { ProducerRunState } from "@/lib/producer/project-state";
import { readCutPreviewObject } from "../producer/auto-edit/cut-preview-receipt";
import {
  assertNoPromotionReconciliation,
  PromotionReconciliationError,
} from "@/lib/server/ask-editor-reconciliation";
import {
  assertNoPendingCutRepairTransitionSync,
  CutRepairTransitionPendingError,
} from "@/lib/server/cut-repair-transition-reconciliation";

interface GuardInput {
  projectRoot: string;
  producerDir: string;
  operation: string;
  allowCutRepairRecovery?: boolean;
  checkpointVerification?: CheckpointVerification;
}

/** Internal lease admission only; never an acceptance, source proof or permission to save a plan. */
export type CheckpointVerification = { expectedToken: string; expectedJournalHash: string } & (
  | { workflowVersion: 1; action: "accept-cut-and-continue"; expectedStatus: "awaiting_cut_approval" }
  | { workflowVersion: 1; action: "retry-cut-continuation"; expectedStatus: "cut_accepted" }
  | { workflowVersion: 2; action: "accept-cut-await-treatment"; expectedStatus: "awaiting_cut_approval" }
  | { workflowVersion: 2; action: "admit-post-cut-treatment"; expectedStatus: "awaiting_treatment_brief" }
  | { workflowVersion: 2; action: "compile-post-cut-proposal"; expectedStatus: "treatment_admitted" }
  | { workflowVersion: 2; action: "revise-post-cut-treatment"; expectedStatus: "treatment_admitted" }
  | { workflowVersion: 2; action: "review-post-cut-proposal"; expectedStatus: "treatment_admitted" }
  | { workflowVersion: 2; action: "prepare-guided-opening"; expectedStatus: "treatment_admitted" }
  | { workflowVersion: 2; action: "reconcile-guided-opening"; expectedStatus: "treatment_admitted" }
  | { workflowVersion: 2; action: "approve-guided-opening"; expectedStatus: "treatment_admitted" }
  | { workflowVersion: 2; action: "continue-approved-opening"; expectedStatus: "treatment_admitted" }
  | { workflowVersion: 2; action: "activate-guided-body" | "reconcile-guided-body" | "read-guided-body"; expectedStatus: "treatment_admitted" }
);

class CheckpointAuthorityError extends Error {}
const CHECKPOINT_STATUSES = ["awaiting_cut_approval", "cut_accepted", "awaiting_treatment_brief", "treatment_admitted"];
const VERIFICATION_ACTIONS = new Set([
  "1:accept-cut-and-continue:awaiting_cut_approval", "1:retry-cut-continuation:cut_accepted",
  "2:accept-cut-await-treatment:awaiting_cut_approval", "2:admit-post-cut-treatment:awaiting_treatment_brief",
  "2:compile-post-cut-proposal:treatment_admitted",
  "2:revise-post-cut-treatment:treatment_admitted",
  "2:review-post-cut-proposal:treatment_admitted",
  "2:prepare-guided-opening:treatment_admitted",
  "2:reconcile-guided-opening:treatment_admitted",
  "2:approve-guided-opening:treatment_admitted",
  "2:continue-approved-opening:treatment_admitted",
  "2:activate-guided-body:treatment_admitted", "2:reconcile-guided-body:treatment_admitted", "2:read-guided-body:treatment_admitted",
]);

export type ProjectMutationGuard =
  | { lease: ProjectMutationLease; response?: never }
  | { lease?: never; response: Response };

export function mutationProjectRoot(dir: string): string {
  const clean = dir.replace(/\/$/, "");
  if (existsSync(path.join(clean, "project.json"))) return clean;
  const parent = path.dirname(clean);
  return existsSync(path.join(parent, "project.json")) ? parent : clean;
}

function conflict(message: string, detail: Record<string, unknown>): Response {
  return new Response(JSON.stringify({
    error: message,
    code: "PROJECT_MUTATION_BUSY",
    retryable: true,
    ...detail,
  }), { status: 409, headers: { "Content-Type": "application/json" } });
}

function staleLeaseConflict(input: GuardInput): Response {
  return new Response(JSON.stringify({
    error: "A prior project mutation lease is stale but its exact owner inode "
      + "cannot be verified. Verify no Sniper or Palmier writer is running, then "
      + "quarantine the named legacy/malformed lock or interrupted recovery "
      + "claim before retrying.",
    code: "PROJECT_MUTATION_RECOVERY_REQUIRED",
    retryable: false,
    activeOperation: null,
    projectRoot: input.projectRoot,
  }), { status: 409, headers: { "Content-Type": "application/json" } });
}

/** A malformed/present journal is not absence of checkpoint ownership. */
function observeCheckpointJournal(dir: string) {
  const file = autoEditJobPath(dir);
  try { lstatSync(file); } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw new CheckpointAuthorityError("The durable Auto Edit journal cannot be inspected");
  }
  try {
    const observed = readCutPreviewObject(path.join(realpathSync(dir), path.basename(file)));
    const job = parseAutoEditJobRecord(observed.value);
    if (realpathSync(job.ctx.dir) !== realpathSync(dir)) throw new Error("journal names another project");
    return { job, sha256: observed.sha256 };
  } catch (error) {
    throw new CheckpointAuthorityError(`The durable Auto Edit journal requires recovery: ${String(error)}`);
  }
}

/** Compare the closed action and exact durable bytes under the acquired project lease. */
function assertCheckpointVerification(input: GuardInput, observed: ReturnType<typeof observeCheckpointJournal>): void {
  const value = input.checkpointVerification;
  const keys = ["action", "expectedJournalHash", "expectedStatus", "expectedToken", "workflowVersion"];
  if (!value || Object.keys(value).sort().join(",") !== keys.join(",")
      || !VERIFICATION_ACTIONS.has(`${value.workflowVersion}:${value.action}:${value.expectedStatus}`)
      || typeof value.expectedToken !== "string" || !value.expectedToken || value.expectedToken.length > 200
      || typeof value.expectedJournalHash !== "string" || !/^[a-f0-9]{64}$/.test(value.expectedJournalHash)
      || !observed || observed.sha256 !== value.expectedJournalHash || observed.job.token !== value.expectedToken
      || observed.job.status !== value.expectedStatus || observed.job.ctx.workflowPolicy !== "cut-first"
      || (observed.job.ctx.workflowV2 ? 2 : 1) !== value.workflowVersion) {
    throw new CheckpointAuthorityError("Checkpoint verification does not name the exact current durable action, token and journal");
  }
}

function checkpointOwnsAuthority(observed: ReturnType<typeof observeCheckpointJournal>, run: ProducerRunState | null): boolean {
  const job = observed?.job;
  return Boolean((job && (CHECKPOINT_STATUSES.includes(job.status) || (job.ctx.workflowV2 && job.status !== "running")))
    || (run && (CHECKPOINT_STATUSES.includes(run.status) || (run.workflowVersion === 2 && run.status !== "running"))));
}

function activeRunConflict(input: GuardInput, run: ProducerRunState): Response {
  const phase = run.phase.replaceAll("_", " ");
  return conflict(
    `${run.kind === "auto_edit" ? "Auto Edit" : "Rendering"} is currently ${phase}. `
      + `Choose Stop & keep checkpoint before ${input.operation}, then retry.`,
    { activeRun: { kind: run.kind, phase: run.phase }, action: "stop_keep_checkpoint" },
  );
}

/** Exact phase capability grants a lease only; fresh execution and cleanup remain service-owned proofs. */
function assertBodyPhaseCapability(input: GuardInput, observed: NonNullable<ReturnType<typeof observeCheckpointJournal>>): void {
  const pointer = observed.job.guidedHandoffV2!, action = input.checkpointVerification?.action;
  assertCheckpointVerification(input, observed);
  const allowed = action === "activate-guided-body" && !pointer.bodyActivationHash
    || action === "reconcile-guided-body" && pointer.bodyActivationHash && pointer.bodyProcessOutcomeHash && !pointer.bodyCleanupHash
    || action === "read-guided-body" && pointer.bodyCleanupHash && !pointer.bodyCandidateHash;
  if (!allowed) throw new CheckpointAuthorityError("Private body ownership is fenced; use only its exact current verification/recovery phase");
}

/** Reconciliation is never waived by a checkpoint verification capability. */
function guardedAuthority(input: GuardInput, lease: ProjectMutationLease): ProjectMutationGuard {
  assertNoPromotionReconciliation(input.producerDir);
  if (!input.allowCutRepairRecovery || input.checkpointVerification) assertNoPendingCutRepairTransitionSync(input.producerDir);
  const observed = observeCheckpointJournal(input.producerDir), run = producerRun(input.producerDir);
  if (observed?.job.guidedHandoffV2?.bodyExecutionClaimHash) {
    assertBodyPhaseCapability(input, observed);
  }
  if (run?.status === "running") { lease.release(); return { response: activeRunConflict(input, run) }; }
  if (input.checkpointVerification !== undefined) {
    assertCheckpointVerification(input, observed);
    return { lease };
  }
  if (checkpointOwnsAuthority(observed, run)) {
    throw new CheckpointAuthorityError("The guided checkpoint owns this project's cut and treatment authority. Use its dedicated review or recovery action; ordinary edits cannot replace it.");
  }
  return { lease };
}

function authorityErrorResponse(error: unknown): Response {
  if (error instanceof PromotionReconciliationError || error instanceof CutRepairTransitionPendingError
      || error instanceof CheckpointAuthorityError) {
    const code = error instanceof CheckpointAuthorityError ? "PROJECT_CHECKPOINT_OWNS_AUTHORITY"
      : error instanceof CutRepairTransitionPendingError ? "CUT_REPAIR_RECOVERY_REQUIRED" : "PROJECT_RECONCILIATION_REQUIRED";
    return new Response(JSON.stringify({ error: error.message, code, retryable: false }), {
      status: 409, headers: { "Content-Type": "application/json" },
    });
  }
  throw error;
}

/** Serialize writers; guided checkpoints retain authority even after their worker exits. */
export function guardProjectMutation(input: GuardInput): ProjectMutationGuard {
  const acquired = acquireProjectMutationLease(input.projectRoot, input.operation);
  if (!acquired.lease) {
    if (acquired.conflict.stale) return { response: staleLeaseConflict(input) };
    const holder = acquired.conflict.operation || "another project update";
    return { response: conflict(
      `This project is busy with ${holder}. Wait for it to finish, then retry ${input.operation}.`,
      { activeOperation: acquired.conflict.operation ?? null },
    ) };
  }
  try { return guardedAuthority(input, acquired.lease); } catch (error) {
    acquired.lease.release();
    return { response: authorityErrorResponse(error) };
  }
}
