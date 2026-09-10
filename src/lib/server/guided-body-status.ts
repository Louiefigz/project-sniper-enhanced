import { canonicalProducerDir } from "@/app/api/producer/auto-edit/request";
import { parseGuidedBodyStatus, type GuidedBodyStatusV1 } from "@/lib/producer/contracts/guided-body-command-v1";
import { readGuidedBodyClaim } from "./guided-body-lineage";
import { readGuidedBodyActivation } from "./guided-body-activation";
import { readBodyPhase } from "./guided-body-phase";
import { readQualifiedBodyCandidate } from "./guided-body-readback";
import { readStoppedBodyProcess } from "./guided-body-process";
import { readHeldBodyCleanup } from "./guided-body-result";
import { observeHumanCutJob } from "./human-cut-acceptance-store";

/** Exact provenance for command replay, without rerunning source verification, a worker or any budget admission. */
export function readRecordedBodyAdmission(dir: string) {
  const pointer = observeHumanCutJob(dir).job.guidedHandoffV2;
  if (!pointer?.bodyExecutionClaimHash) return null;
  if (pointer.bodyCandidateHash) return readBodyPhase(dir, "candidate").held.admission;
  if (pointer.bodyCleanupHash) return readBodyPhase(dir, "cleanup").held.admission;
  if (pointer.bodyProcessOutcomeHash) return readBodyPhase(dir, "process").held.admission;
  if (pointer.bodyActivationHash) return readGuidedBodyActivation(dir).admission;
  return readGuidedBodyClaim(dir);
}

function phaseStatus(dir: string, status: GuidedBodyStatusV1): GuidedBodyStatusV1 {
  const held = readRecordedBodyAdmission(dir);
  if (!held) return status;
  const row = { ...status, requestId: held.claim.requestId, executionId: held.claim.executionId };
  if (row.candidateHash) {
    const selected = readQualifiedBodyCandidate(dir);
    return { ...row, state: "private-candidate-qualified", candidate: selected.candidate,
      detail: "Recorded private candidate passed owned mechanical verification; no fresh source/media decode, creative review, listening or delivery approval occurs in status." };
  }
  if (row.cleanupHash) {
    const cleanup = readHeldBodyCleanup(readBodyPhase(dir, "cleanup"));
    return { ...row, state: cleanup.stopped.receipt.status === "complete" ? "cleanup-verified" : "failed-or-unresolved",
      detail: "Recorded resource cleanup is verified. A private candidate is not selected; no automatic resume is permitted." };
  }
  if (observeHumanCutJob(dir).job.guidedHandoffV2?.bodyProcessOutcomeHash) {
    const stopped = readStoppedBodyProcess(readBodyPhase(dir, "process"));
    return { ...row, state: stopped.receipt.status === "complete" ? "process-returned" : "failed-or-unresolved",
      detail: "An actual body process return is retained. Exact Docker cleanup and candidate verification remain separate." };
  }
  return { ...row, state: row.activationHash ? "execution-owned" : "admission-fenced",
    detail: row.activationHash ? "Durable execution ownership is recorded; this is not evidence that a worker is alive or media is ready. No automatic retry."
      : "Non-executable admission is retained. It cannot be activated by replay or silently restarted." };
}

/** Read-only metadata/status. Changed or incomplete ownership remains explicit, never idle or a guessed success. */
export function readGuidedBodyStatus(value: unknown): GuidedBodyStatusV1 {
  const dir = canonicalProducerDir(value), current = observeHumanCutJob(dir), pointer = current.job.guidedHandoffV2;
  const initial: GuidedBodyStatusV1 = { ok: true, state: "unavailable", detail: "No body admission exists. Body execution requires an exact approved guided opening and a fresh explicit request.",
    journalHash: current.sha256, requestId: null, executionId: null, admissionClaimHash: pointer?.bodyExecutionClaimHash ?? null,
    activationHash: pointer?.bodyActivationHash ?? null, cleanupHash: pointer?.bodyCleanupHash ?? null, candidateHash: pointer?.bodyCandidateHash ?? null,
    candidate: null, observedAt: new Date().toISOString(), sourceFreshness: "not-observed-by-status", bodyApproved: false, deliveryApproved: false };
  let status = initial;
  try { status = phaseStatus(dir, initial); }
  catch (error) { status = { ...initial, state: "failed-or-unresolved", detail: String(error).slice(0, 4000) }; }
  if (observeHumanCutJob(dir).sha256 !== current.sha256) throw new Error("Body journal changed during status observation");
  return parseGuidedBodyStatus(status);
}
