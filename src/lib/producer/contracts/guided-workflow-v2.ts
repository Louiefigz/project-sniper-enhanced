import { exactKeys, objectValue, sha256, stringValue, uuid } from "./validation";

/** Internal opt-in only. No production route accepts this until opening/body continuation exists. */
export interface GuidedWorkflowV2 {
  schemaVersion: 2; mode: "guided"; afterCut: "treatment-then-intro";
  approvalPolicy: "explicit-human";
}
export interface GuidedCutSubmissionV2 {
  schemaVersion: 2; operation: "accept-cut-await-treatment"; idempotencyKey: string;
  expectedToken: string; expectedJournalHash: string; requestHash: string;
  executionKey: string; receiptHash: string; mediaSha256: string;
  attestation: { watched: true; listened: true; acceptsExactCut: true; understandsTreatmentPending: true };
}
export interface GuidedHandoffPointerV2 {
  schemaVersion: 2; cutDecisionHash: string; cutActivationHash: string; pictureLockedRevisionHash: string;
  treatmentAdmissionHash?: string;
  /** Unapproved private proposal only; not a rendered revision or delivery receipt. */
  treatmentProposalHash?: string;
  /** Isolated reviewed draft only; neither pointer advances accepted/final heads. */
  proposalReadinessHash?: string;
  treatmentDraftRevisionHash?: string;
  /** Unsupported pre-render attempt only; never a successful preview/approval pointer. */
  openingPreparationHash?: string;
  /** Possible private renderer ownership; blocks another attempt until exact cleanup is proved. */
  openingExecutionClaimHash?: string;
  /** Separately journal-held actual process return; raw sidecars alone cannot prove a stopped group. */
  openingProcessOutcomeHash?: string;
  /** Historical exact resource cleanup only; does not select or approve opening media. */
  openingCleanupHash?: string;
  /** Mechanical playback selection of exact verified private media; never opening/body/delivery approval. */
  openingMediaSelectionHash?: string;
  /** Explicit local-operator approval of that exact selection; body generation and delivery remain separate. */
  openingApprovalHash?: string;
  /** Internal non-executable body admission; exact recovery is required before any later mutation. */
  bodyExecutionClaimHash?: string;
  /** Distinct foreground body invocation, retained independently of non-executable V1 admission. */
  bodyActivationHash?: string;
  bodyProcessOutcomeHash?: string;
  bodyCleanupHash?: string;
  /** Mechanically qualified private candidate only, never delivery approval. */
  bodyCandidateHash?: string;
}

export function parseGuidedWorkflowV2(value: unknown): GuidedWorkflowV2 {
  const row = objectValue(value, "GuidedWorkflowV2");
  const keys = ["schemaVersion", "mode", "afterCut", "approvalPolicy"];
  exactKeys(row, keys, keys, "GuidedWorkflowV2");
  if (row.schemaVersion !== 2 || row.mode !== "guided" || row.afterCut !== "treatment-then-intro"
      || row.approvalPolicy !== "explicit-human") throw new Error("Guided workflow v2 policy is unsupported; no fallback is inferred");
  return row as unknown as GuidedWorkflowV2;
}

/** Distinct from v1 accept-and-continue: this decision authorizes no visual worker. */
export function parseGuidedCutSubmissionV2(value: unknown): GuidedCutSubmissionV2 {
  const row = objectValue(value, "GuidedCutSubmissionV2");
  const keys = ["schemaVersion", "operation", "idempotencyKey", "expectedToken", "expectedJournalHash",
    "requestHash", "executionKey", "receiptHash", "mediaSha256", "attestation"];
  exactKeys(row, keys, keys, "GuidedCutSubmissionV2");
  if (row.schemaVersion !== 2 || row.operation !== "accept-cut-await-treatment") throw new Error("The v2 cut decision operation is unsupported");
  uuid(row.idempotencyKey, "idempotencyKey"); stringValue(row.expectedToken, "expectedToken", 200);
  for (const key of ["expectedJournalHash", "requestHash", "executionKey", "receiptHash", "mediaSha256"]) sha256(row[key], key);
  const attestation = objectValue(row.attestation, "attestation");
  const flags = ["watched", "listened", "acceptsExactCut", "understandsTreatmentPending"];
  exactKeys(attestation, flags, flags, "attestation");
  if (!flags.every((key) => attestation[key] === true)) throw new Error("Every v2 human cut attestation must be explicit");
  return row as unknown as GuidedCutSubmissionV2;
}

export function parseGuidedHandoffPointerV2(value: unknown): GuidedHandoffPointerV2 {
  const row = objectValue(value, "GuidedHandoffPointerV2");
  const required = ["schemaVersion", "cutDecisionHash", "cutActivationHash", "pictureLockedRevisionHash"];
  exactKeys(row, [...required, "treatmentAdmissionHash", "treatmentProposalHash", "proposalReadinessHash", "treatmentDraftRevisionHash", "openingPreparationHash", "openingExecutionClaimHash", "openingProcessOutcomeHash", "openingCleanupHash", "openingMediaSelectionHash", "openingApprovalHash", "bodyExecutionClaimHash", "bodyActivationHash", "bodyProcessOutcomeHash", "bodyCleanupHash", "bodyCandidateHash"], required, "GuidedHandoffPointerV2");
  if (row.schemaVersion !== 2) throw new Error("Guided handoff version is unsupported");
  for (const key of required.slice(1)) sha256(row[key], key);
  if (Object.hasOwn(row, "treatmentAdmissionHash")) sha256(row.treatmentAdmissionHash, "treatmentAdmissionHash");
  if (Object.hasOwn(row, "treatmentProposalHash")) {
    sha256(row.treatmentProposalHash, "treatmentProposalHash");
    if (!row.treatmentAdmissionHash) throw new Error("Proposal requires an exact admitted request");
  }
  if (Object.hasOwn(row, "proposalReadinessHash")) {
    sha256(row.proposalReadinessHash, "proposalReadinessHash");
    if (!row.treatmentProposalHash) throw new Error("Readiness requires an exact compiled proposal");
  }
  if (Object.hasOwn(row, "treatmentDraftRevisionHash")) {
    sha256(row.treatmentDraftRevisionHash, "treatmentDraftRevisionHash");
    if (!row.proposalReadinessHash) throw new Error("Treatment draft requires a distinct proposal review");
  }
  if (Object.hasOwn(row, "openingPreparationHash")) {
    sha256(row.openingPreparationHash, "openingPreparationHash");
    if (!row.treatmentDraftRevisionHash) throw new Error("Opening preparation requires an exact isolated treatment draft");
  }
  if (Object.hasOwn(row, "openingExecutionClaimHash")) {
    sha256(row.openingExecutionClaimHash, "openingExecutionClaimHash");
    if (!row.treatmentDraftRevisionHash) throw new Error("Opening resource ownership requires an exact isolated treatment draft");
  }
  if (Object.hasOwn(row, "openingCleanupHash")) {
    sha256(row.openingCleanupHash, "openingCleanupHash");
    if (!row.treatmentDraftRevisionHash) throw new Error("Opening cleanup requires an exact isolated treatment draft");
  }
  if (Object.hasOwn(row, "openingProcessOutcomeHash")) {
    sha256(row.openingProcessOutcomeHash, "openingProcessOutcomeHash");
    if (!row.openingExecutionClaimHash) throw new Error("Opening actual outcome requires its exact pending execution claim");
  }
  if (Object.hasOwn(row, "openingMediaSelectionHash")) {
    sha256(row.openingMediaSelectionHash, "openingMediaSelectionHash");
    if (!row.openingCleanupHash) throw new Error("Opening media selection requires exact committed resource cleanup");
  }
  if (Object.hasOwn(row, "openingApprovalHash")) {
    sha256(row.openingApprovalHash, "openingApprovalHash");
    if (!row.openingMediaSelectionHash) throw new Error("Opening approval requires an exact media selection");
  }
  if (Object.hasOwn(row, "bodyExecutionClaimHash")) {
    sha256(row.bodyExecutionClaimHash, "bodyExecutionClaimHash");
    if (!row.openingApprovalHash || !row.treatmentDraftRevisionHash || row.openingExecutionClaimHash) {
      throw new Error("Body ownership requires exact opening approval/draft and no pending opening claim");
    }
  }
  for (const [key, prior] of [["bodyActivationHash", "bodyExecutionClaimHash"], ["bodyProcessOutcomeHash", "bodyActivationHash"],
    ["bodyCleanupHash", "bodyProcessOutcomeHash"], ["bodyCandidateHash", "bodyCleanupHash"]]) {
    if (!Object.hasOwn(row, key)) continue;
    sha256(row[key], key);
    if (!row[prior]) throw new Error("Body execution facts require their exact prior durable phase");
  }
  return row as unknown as GuidedHandoffPointerV2;
}

export function validGuidedWorkflowV2(value: unknown): boolean {
  try { parseGuidedWorkflowV2(value); return true; } catch { return false; }
}
export function validGuidedHandoffPointerV2(value: unknown): boolean {
  try { parseGuidedHandoffPointerV2(value); return true; } catch { return false; }
}
