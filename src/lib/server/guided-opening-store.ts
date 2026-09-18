import path from "node:path";
import { parseOpeningPreparationReceipt } from "@/lib/producer/contracts/guided-opening-v1";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { readGuidedExecution, readGuidedObject } from "./guided-cut-v2-store";
import { observeHumanCutJob } from "./human-cut-acceptance-store";
import { parseAutoEditJobRecord } from "./auto-edit-job-persistence";
import { readGuidedProposalReadiness } from "./guided-proposal-review-store";
import { buildOpeningAuthority } from "./guided-opening-authority";

function execution(dir: string, receipt: ReturnType<typeof parseOpeningPreparationReceipt>) {
  const start = readGuidedExecution({ dir, id: receipt.submission.idempotencyKey, executionId: receipt.executionId, hash: receipt.executionStartHash });
  const before = readCutPreviewObject(path.join(dir, "human-cut-job-snapshots", `${receipt.beforeJournalHash}.json`));
  const job = parseAutoEditJobRecord(before.value);
  if (before.sha256 !== receipt.beforeJournalHash || job.status !== "treatment_admitted" || job.token !== receipt.submission.expectedToken
      || job.guidedHandoffV2?.proposalReadinessHash !== receipt.submission.proposalReadinessHash
      || job.guidedHandoffV2?.treatmentDraftRevisionHash !== receipt.submission.treatmentDraftRevisionHash
      || job.updatedAt > String(start.firstReceivedAt) || String(start.startedAt) > receipt.createdAt
      || start.submissionHash !== canonicalJsonSha256(receipt.submission)) throw new Error("Opening attempt lost its actual before-journal/start bindings");
  return { job, root: path.join(dir, "guided-v2-operations", receipt.submission.idempotencyKey, "executions", receipt.executionId) };
}

function verifyObject(dir: string, root: string, input: { name: string; hash: string; expected: unknown }): void {
  const value = readGuidedObject(dir, input.hash), privateValue = readCutPreviewObject(path.join(root, input.name));
  if (canonicalJsonSha256(value) !== canonicalJsonSha256(input.expected) || canonicalJsonSha256(privateValue.value) !== input.hash) {
    throw new Error(`Opening attempt object changed: ${input.name}`);
  }
}

/** Strong current record read. Unsupported is not success, a preview pointer or a current source-byte claim. */
export function readGuidedOpeningPreparation(dir: string) {
  const proposal = readGuidedProposalReadiness(dir), hash = proposal.pointer.openingPreparationHash;
  if (proposal.pointer.openingExecutionClaimHash) throw new Error("Opening renderer ownership is unresolved; no preparation replay or media selection is allowed");
  if (!hash) throw new Error("No opening preparation attempt is recorded");
  const receipt = parseOpeningPreparationReceipt(readGuidedObject(dir, hash)), held = execution(dir, receipt);
  if (receipt.submission.expectedToken !== proposal.job.token || receipt.submission.proposalReadinessHash !== proposal.readinessHash
      || receipt.submission.treatmentDraftRevisionHash !== proposal.pointer.treatmentDraftRevisionHash
      || receipt.clockHash !== proposal.clock.hash || receipt.generationStartedAt !== proposal.generationStartedAt
      || receipt.createdAt > proposal.job.updatedAt || receipt.createdAt < String(proposal.readinessReceipt.createdAt)
      || canonicalJsonSha256(held.job.ctx) !== proposal.fact.contextHash) throw new Error("Opening record no longer binds this exact draft/clock/context");
  const authority = buildOpeningAuthority(proposal);
  verifyObject(dir, held.root, { name: "input.json", hash: receipt.inputHash, expected: authority.input });
  verifyObject(dir, held.root, { name: "implementation.json", hash: receipt.implementationHash, expected: authority.implementation });
  if (receipt.frameBindingsHash !== authority.input.frameBindingsHash
      || canonicalJsonSha256(receipt.blockerCodes) !== canonicalJsonSha256(authority.blockerCodes)) throw new Error("Opening scope or unsupported capability changed");
  if (receipt.frameBindingsHash) verifyObject(dir, held.root, { name: "frame-bindings.json", hash: receipt.frameBindingsHash, expected: authority.bindings });
  if (observeHumanCutJob(dir).sha256 !== proposal.sha256) throw new Error("Opening journal changed during read");
  return { proposal, receipt, preparationHash: hash, state: receipt.state, available: false as const,
    currentExecutionAuthority: false as const, media: null, scope: receipt.scope };
}
