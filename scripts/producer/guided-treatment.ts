/** File-based Codex entrypoint to existing v2 services. No bootstrap, server, or approval defaults. */
import path from "node:path";
import { canonicalProducerDir } from "../../src/app/api/producer/auto-edit/request";
import { observeCutPreviewFile } from "../../src/app/api/producer/auto-edit/cut-preview-receipt";
import { parseGuidedCutSubmissionV2 } from "../../src/lib/producer/contracts/guided-workflow-v2";
import { parseRawTreatmentSubmissionV1, parseTreatmentCompileSubmissionV1 } from "../../src/lib/producer/contracts/raw-treatment-v1";
import { parseRawTreatmentRevisionSubmissionV1 } from "../../src/lib/producer/contracts/raw-treatment-revision-v1";
import { parseProposalReadinessSubmission } from "../../src/lib/producer/contracts/proposal-readiness-v1";
import { acceptGuidedCutV2 } from "../../src/lib/server/guided-cut-v2";
import { admitRawTreatment } from "../../src/lib/server/guided-raw-treatment";
import { reviseRawTreatment, reconcileRawTreatmentRevision } from "../../src/lib/server/guided-treatment-revision";
import { compileGuidedTreatmentProposal } from "../../src/lib/server/guided-proposal";
import { reviewGuidedTreatmentProposal } from "../../src/lib/server/guided-proposal-review";
import { readTreatmentCommandStatus } from "./guided-treatment-status";
import { MAX_TREATMENT_REQUEST_BYTES, parseTreatmentRequestJson } from "./guided-treatment-json";

const USAGE = "node --import tsx scripts/producer/guided-treatment.ts status <producer-dir> "
  + "OR accept-cut|admit|revise|reconcile-revision|compile|review <producer-dir> <request.json>";
const MUTATIONS = ["accept-cut", "admit", "revise", "reconcile-revision", "compile", "review"] as const;
type Mutation = typeof MUTATIONS[number];

/** Fixed service references support in-process unit mocking only; no runtime override input exists. */
export const treatmentCommandServices = {
  canonicalDir: canonicalProducerDir, status: readTreatmentCommandStatus,
  accept: acceptGuidedCutV2, admit: admitRawTreatment,
  revise: reviseRawTreatment, reconcileRevision: reconcileRawTreatmentRevision,
  compile: compileGuidedTreatmentProposal, review: reviewGuidedTreatmentProposal,
};

function boundedPath(value: string): string {
  if (!value || value.length > 4096 || /[\0\r\n]/u.test(value)) throw new Error("Treatment command path is invalid");
  return path.resolve(value);
}

/** Read exact bounded regular, single-link UTF-8 JSON via the existing same-descriptor observer. */
function readRequest(file: string): unknown {
  const held = observeCutPreviewFile(boundedPath(file), MAX_TREATMENT_REQUEST_BYTES, true);
  return parseTreatmentRequestJson(new TextDecoder("utf-8", { fatal: true }).decode(held.bytes));
}

function acknowledgement(command: Mutation, submission: { idempotencyKey: string }, result: {
  job: { token: string; status: string }; replayed: boolean;
}, facts: Record<string, string | null>) {
  return { ok: true, scope: "guided-treatment-command-not-opening-body-or-delivery-approval",
    command, idempotencyKey: submission.idempotencyKey, replayed: result.replayed,
    recordedState: result.job.status, recordedToken: result.job.token, facts,
    verificationScope: result.replayed ? "recorded-request-acknowledgment-no-fresh-source-verification"
      : "existing-service-completed-this-invocation",
    subjectiveListening: "not-performed-by-system", openingApprovalGranted: false,
    bodyApprovalGranted: false, deliveryApprovalGranted: false };
}

async function mutate(command: Mutation, dir: string, value: unknown) {
  if (command === "revise" || command === "reconcile-revision") return revise(command, dir, value);
  if (command === "accept-cut") {
    const submission = parseGuidedCutSubmissionV2(value);
    const result = await treatmentCommandServices.accept({ dir, submission });
    return acknowledgement(command, submission, result, {
      cutDecisionHash: result.job.guidedHandoffV2!.cutDecisionHash,
      pictureLockedRevisionHash: result.job.guidedHandoffV2!.pictureLockedRevisionHash });
  }
  if (command === "admit") {
    const submission = parseRawTreatmentSubmissionV1(value);
    const result = await treatmentCommandServices.admit({ dir, submission });
    return acknowledgement(command, submission, result, {
      treatmentAdmissionHash: result.job.guidedHandoffV2!.treatmentAdmissionHash!, generationStartedAt: result.generationStartedAt });
  }
  if (command === "compile") {
    const submission = parseTreatmentCompileSubmissionV1(value);
    const result = await treatmentCommandServices.compile({ dir, submission });
    return acknowledgement(command, submission, result, { proposalHash: result.proposalHash });
  }
  const submission = parseProposalReadinessSubmission(value);
  const result = await treatmentCommandServices.review({ dir, submission });
  return acknowledgement(command, submission, result, { proposalReadinessHash: result.readinessHash,
    treatmentDraftRevisionHash: result.pointer.treatmentDraftRevisionHash ?? null });
}

async function revise(command: "revise" | "reconcile-revision", dir: string, value: unknown) {
  const submission = parseRawTreatmentRevisionSubmissionV1(value);
  const service = command === "revise" ? treatmentCommandServices.revise : treatmentCommandServices.reconcileRevision;
  const result = await service({ dir, submission });
  return { ...acknowledgement(command, submission, result, { treatmentAdmissionHash: result.treatmentAdmissionHash,
    parentAdmissionHash: submission.parentAdmissionHash, generationStartedAt: result.generationStartedAt }),
    superseded: result.superseded, sourceFreshness: result.sourceFreshness };
}

/** One explicit operation only. Never generate UUIDs, attestations, retries, model overrides or refreshed bindings. */
export async function executeTreatmentCommand(argv: string[]) {
  const [command, directory, file] = argv;
  if (argv.length === 1 && command === "--help") return { usage: USAGE,
    note: "Run from repository root. Requires an existing v2 guided cut-preview checkpoint; bootstrap is not provided. Accept-cut requires the user's explicit exact-preview watched/listened decision. Admit retains their raw treatment request and starts its original generation clock. Revise explicitly replaces the complete brief at unchanged accepted intent/cut, before any opening/body ownership; it does not refresh source bytes. Reconcile-revision explicitly recovers only the same retained request after failure. Neither resets the original clock or approves anything. Compile/review use configured subscription-backed services and local gates; status never does. Persist request UUIDs for exact replay; no automatic retry." };
  const mutation = MUTATIONS.includes(command as Mutation);
  if (!(command === "status" && argv.length === 2) && !(mutation && argv.length === 3)) throw new Error(USAGE);
  const directoryPath = boundedPath(directory);
  if (command === "status") return treatmentCommandServices.status(treatmentCommandServices.canonicalDir(directoryPath));
  // Invalid request transport is rejected before resolving or reading a user project.
  const value = readRequest(file), dir = treatmentCommandServices.canonicalDir(directoryPath);
  return mutate(command as Mutation, dir, value);
}

if (require.main === module) {
  executeTreatmentCommand(process.argv.slice(2)).then((value) => process.stdout.write(JSON.stringify(value) + "\n"))
    .catch((error: unknown) => {
      const message = error instanceof Error ? error.message.slice(0, 2048) : "Guided treatment command failed";
      process.stderr.write(JSON.stringify({ ok: false, error: message,
        recovery: "Recheck retained state; an error does not prove rollback. Do not automatically resubmit or replace a request UUID." }) + "\n");
      process.exitCode = 1;
    });
}
