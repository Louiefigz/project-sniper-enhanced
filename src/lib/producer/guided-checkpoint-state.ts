import type { ProducerRunState, ProjectCardSummary, ProjectPhaseCopy } from "./project-state";

/** Internal v2 checkpoints cannot fall through to legacy continuation controls. */
export function isTreatmentCheckpoint(run?: ProducerRunState | null): boolean {
  return run?.status === "awaiting_treatment_brief" || run?.status === "treatment_admitted"
    || (run?.workflowVersion === 2 && run.status !== "running");
}

export function isGuidedCheckpoint(run?: ProducerRunState | null): boolean {
  return isTreatmentCheckpoint(run) || run?.status === "awaiting_cut_approval"
    || run?.status === "cut_accepted";
}

export function treatmentCheckpointLabel(run?: ProducerRunState | null): string {
  if (run?.status === "awaiting_treatment_brief") return "Cut accepted · treatment brief pending";
  if (run?.status === "treatment_admitted") return "Treatment saved · opening workflow";
  if (run?.status === "failed" || run?.status === "interrupted") return "Guided workflow needs attention";
  return "Guided cut checkpoint · integration pending";
}

export const TREATMENT_INTEGRATION_NOTICE = "Use the explicit opening controls for a qualified proposal. Public treatment submission, proposal compilation and review, and full-body continuation are still unfinished. Saved decisions remain intact; legacy Generate, Resume, and saved-brief acceptance cannot bypass this workflow.";

export function treatmentCheckpointCopy(run?: ProducerRunState | null): ProjectPhaseCopy | null {
  if (!isTreatmentCheckpoint(run)) return null;
  return {
    label: treatmentCheckpointLabel(run),
    detail: TREATMENT_INTEGRATION_NOTICE,
    tone: run?.status === "failed" || run?.status === "interrupted" ? "error" : "neutral",
  };
}

/** A saved request is not an executed treatment, intro approval, or delivery. */
export function treatmentCheckpointSummary(run?: ProducerRunState | null): ProjectCardSummary | null {
  if (!isTreatmentCheckpoint(run)) return null;
  const accepted = run?.status === "awaiting_treatment_brief" || run?.status === "treatment_admitted";
  return {
    available: accepted
      ? "The versioned cut decision is saved; treatment and delivery are not approved."
      : "The versioned guided job and its existing evidence remain saved.",
    working: run?.message || treatmentCheckpointLabel(run),
    next: TREATMENT_INTEGRATION_NOTICE,
    safe: "Inspect the checkpoint or recheck status. Opening it cannot authorize new treatment or overwrite the accepted cut.",
  };
}

/** Keep the familiar cut labels unchanged for exact-v1 projects. */
export function guidedCheckpointOpenLabel(run?: ProducerRunState | null): string {
  if (isTreatmentCheckpoint(run)) return "Inspect guided checkpoint";
  return run?.status === "cut_accepted" ? "Open accepted-cut continuation" : "Open cut review";
}

export function treatmentCheckpointLockReason(run?: ProducerRunState | null): string | null {
  return isTreatmentCheckpoint(run)
    ? "The versioned guided checkpoint owns this timeline. Use its explicit available controls; legacy editing cannot bypass its saved authority."
    : null;
}
