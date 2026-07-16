export type CandidateQcAction = "run_qc" | "promote" | "discard";

/** User-facing label for the one durable candidate mutation currently active. */
export function candidateActionLabel(action: CandidateQcAction | null): string {
  if (action === "promote") return "Promoting approved candidate…";
  if (action === "discard") return "Archiving candidate & restoring parent…";
  return "Running candidate QC…";
}

export function candidateActionTitle(action: CandidateQcAction | null): string {
  if (action === "promote") {
    return "Promotion is rechecking both candidate and parent. Palmier stays locked until it finishes.";
  }
  if (action === "discard") {
    return "Discard is archiving exact evidence and restoring the parent. Palmier stays locked until it finishes.";
  }
  return "Candidate QC is reading and exporting the candidate. Palmier stays locked until it finishes.";
}
