/** Bounded command projections of existing strong readers, not a new authority store. */
import { observeHumanCutJob } from "../../src/lib/server/human-cut-acceptance-store";
import { observeGuidedCutV2 } from "../../src/lib/server/guided-cut-v2-store";
import { readGuidedCutV2 } from "../../src/lib/server/guided-cut-v2";
import { readRawTreatmentAdmission } from "../../src/lib/server/guided-raw-treatment-store";
import { readGuidedTreatmentProposal } from "../../src/lib/server/guided-proposal-store";
import { readGuidedProposalReadiness } from "../../src/lib/server/guided-proposal-review-store";
import { readTreatmentBriefHistory, assertTreatmentBriefHistoryCurrent } from "../../src/lib/server/guided-treatment-revision-history";

/** Fixed production readers. No command-line or request field can replace them. */
export const treatmentStatusReaders = {
  journal: observeHumanCutJob, pending: observeGuidedCutV2, cut: readGuidedCutV2,
  admission: readRawTreatmentAdmission, proposal: readGuidedTreatmentProposal,
  readiness: readGuidedProposalReadiness,
  briefs: readTreatmentBriefHistory,
  briefCurrent: assertTreatmentBriefHistoryCurrent,
};

type Journal = ReturnType<typeof observeHumanCutJob>;
interface StageProjection {
  stage: string;
  journalHash: string;
  nextCommand: "accept-cut" | "admit" | "compile" | "review" | "guided-opening launch-status" | null;
  requestBindings: Record<string, string> | null;
  facts: Record<string, string | number | boolean | null>;
}

function bindings(held: Pick<Journal, "job" | "sha256">) {
  return { expectedToken: held.job.token, expectedJournalHash: held.sha256 };
}

function pending(dir: string): StageProjection {
  const held = treatmentStatusReaders.pending(dir);
  if (held.job.status !== "awaiting_cut_approval") throw new Error("No qualified pending v2 cut preview");
  return { stage: "awaiting-cut-approval", journalHash: held.sha256, nextCommand: "accept-cut",
    requestBindings: { ...bindings(held), requestHash: held.request.requestHash,
      executionKey: held.receipt.executionKey, receiptHash: held.receipt.receiptHash,
      mediaSha256: held.receipt.media.sha256 },
    facts: { planHash: held.request.planHash, humanCutAccepted: false } };
}

function accepted(dir: string): StageProjection {
  const held = treatmentStatusReaders.cut(dir);
  if (held.job.status !== "awaiting_treatment_brief") throw new Error("Accepted cut has no consistent treatment-intake checkpoint");
  return { stage: "awaiting-treatment-brief", journalHash: held.sha256, nextCommand: "admit",
    requestBindings: { ...bindings(held), cutDecisionHash: held.pointer.cutDecisionHash,
      parentRevisionHash: held.pointer.pictureLockedRevisionHash },
    facts: { cutDecisionHash: held.pointer.cutDecisionHash, humanCutAccepted: true } };
}

function admitted(dir: string): StageProjection {
  const held = treatmentStatusReaders.admission(dir);
  return { stage: "raw-treatment-admitted", journalHash: held.sha256, nextCommand: "compile",
    requestBindings: { ...bindings(held), treatmentAdmissionHash: held.pointer.treatmentAdmissionHash! },
    facts: { generationStartedAt: held.generationStartedAt, treatmentAdmissionHash: held.pointer.treatmentAdmissionHash! } };
}

function proposed(dir: string): StageProjection {
  const held = treatmentStatusReaders.proposal(dir);
  const blocked = !held.result.candidate || held.result.blockers.length > 0;
  return { stage: blocked ? "proposal-blocked" : "proposal-awaiting-readiness", journalHash: held.sha256,
    nextCommand: blocked ? null : "review",
    requestBindings: blocked ? null : { ...bindings(held), proposalHash: held.proposalHash },
    facts: { proposalHash: held.proposalHash, blockerCount: held.result.blockers.length,
      generationStartedAt: held.generationStartedAt } };
}

function reviewed(dir: string): StageProjection {
  const held = treatmentStatusReaders.readiness(dir);
  const draft = held.pointer.treatmentDraftRevisionHash ?? null;
  const clean = held.readiness.verdict === "clean" && draft !== null && Boolean(held.draftRevision);
  return { stage: clean ? "treatment-draft-retained" : "readiness-blocked", journalHash: held.sha256,
    nextCommand: clean ? "guided-opening launch-status" : null, requestBindings: null,
    facts: { proposalReadinessHash: held.readinessHash, treatmentDraftRevisionHash: draft,
      generationStartedAt: held.generationStartedAt } };
}

function stage(dir: string, before: Journal): StageProjection {
  const pointer = before.job.guidedHandoffV2;
  if (pointer?.proposalReadinessHash) return reviewed(dir);
  if (pointer?.treatmentProposalHash) return proposed(dir);
  if (pointer?.treatmentAdmissionHash) return admitted(dir);
  if (pointer) return accepted(dir);
  return pending(dir);
}

/** No fallback to an earlier valid stage. Status neither refreshes source bytes nor grants approval. */
export function readTreatmentCommandStatus(dir: string) {
  const before = treatmentStatusReaders.journal(dir);
  const briefs = before.job.guidedHandoffV2?.treatmentAdmissionHash ? treatmentStatusReaders.briefs(dir) : null;
  const result: StageProjection = briefs?.pendingRevision ? { stage: "revision-reconciliation-required", journalHash: before.sha256,
    nextCommand: null, requestBindings: null, facts: { generationStartedAt: briefs.generationStartedAt } } : stage(dir, before);
  if (result.journalHash !== before.sha256 || treatmentStatusReaders.journal(dir).sha256 !== before.sha256) {
    throw new Error("Guided treatment journal changed during status observation");
  }
  if (briefs) treatmentStatusReaders.briefCurrent(dir, briefs);
  return { ok: true, scope: "guided-treatment-status-not-source-requalification-or-approval", ...result,
    briefs,
    sourceFreshness: "not-requalified-by-status", subjectiveListening: "not-performed-by-system",
    approvalGranted: false, requestBindingsIncludeConsent: false,
    note: "Bindings omit request UUIDs, creative text and human attestations. Opening eligibility requires its separate launch-status check." };
}
