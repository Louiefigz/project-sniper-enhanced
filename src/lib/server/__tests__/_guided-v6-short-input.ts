/** Actual leased14-document input and Python source/profile read, never an opening render. */
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import path from "node:path";
import { pythonInterpreter, SCRIPTS_DIR } from "@/app/api/_lib/spawn-python";
import { runCutPreviewProcess } from "@/app/api/producer/auto-edit/cut-preview-process";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { parsePrepareGuidedOpening } from "@/lib/producer/contracts/guided-opening-v1";
import { SCREENED_CAPTION_SHORT_PROFILE } from "@/lib/producer/contracts/guided-caption-profile";
import { acquireGuidedMutation, guidedOperation, finishGuidedOperation } from "../guided-cut-v2-store";
import { createHumanCutIndex } from "../human-cut-acceptance-store";
import { captureOpeningAttemptStart } from "../opening-deadline";
import { guardGenerationAttempt } from "../generation-clock-watermark";
import { readGuidedProposalReadiness } from "../guided-proposal-review-store";
import { writeGuidedOpeningMediaInput, observeGuidedOpeningMediaInput, assertFullProgramMediaMetadata, openingMediaAuthority } from "../guided-opening-media-input";

const PYTHON_READ = ["import json,sys", "from pathlib import Path",
  "from guided_opening_inputs import read_current_inputs", "from guided_opening_pipeline import observe_pipeline",
  "from guided_opening_frames import full_program_frames", "from guided_short_geometry import preflight_short_source",
  "inputs=read_current_inputs(Path(sys.argv[1]),sys.argv[2])", "pipeline=observe_pipeline(inputs)",
  "frames=full_program_frames(inputs)", "preflight_short_source(inputs)",
  "print(json.dumps({'scope':'TEST-only-current-source-and-input-not-rendered', 'profile':inputs.value['profile'],",
  "'documentCount':len(inputs.documents),'graphicCount':len(frames),'executionClosure':pipeline['executionClosure']}))"].join("\n");

export async function prepareV6ShortInput(dir: string, remainingMs: () => number) {
  remainingMs();
  const proposal = readGuidedProposalReadiness(dir);
  const submission = parsePrepareGuidedOpening({ schemaVersion: 1, operation: "prepare-guided-opening", idempotencyKey: randomUUID(),
    expectedToken: proposal.job.token, expectedJournalHash: proposal.sha256, proposalReadinessHash: proposal.readinessHash,
    treatmentDraftRevisionHash: proposal.pointer.treatmentDraftRevisionHash });
  const captured = captureOpeningAttemptStart();
  const lease = await acquireGuidedMutation(dir, { workflowVersion: 2, action: "prepare-guided-opening", expectedStatus: "treatment_admitted",
    expectedToken: proposal.job.token, expectedJournalHash: proposal.sha256 });
  try {
    const operation = guidedOperation({ dir, id: submission.idempotencyKey, submission, receivedAt: captured.receivedAt });
    const guard = cutPreviewLeaseGuard(dir, lease), origin = { clockHash: proposal.clock.hash, startedAt: proposal.generationStartedAt };
    const budget = guardGenerationAttempt({ dir, origin, executionId: operation.executionId, guard }, captured.start(origin));
    createHumanCutIndex(path.join(operation.execution, "budget-admission.json"), budget.admission);
    const heldRemaining = () => Math.min(remainingMs(), budget.remainingMs());
    const invocation = writeGuidedOpeningMediaInput({ proposal, operation, lease, remainingMs: heldRemaining });
    const observed = observeGuidedOpeningMediaInput(invocation.inputPath, invocation.inputSha256);
    assert.equal(observed.authority.profile, SCREENED_CAPTION_SHORT_PROFILE);
    assertFullProgramMediaMetadata({ plan: proposal.result.candidate!, bindings: openingMediaAuthority(proposal).bindings });
    const producer = path.join(SCRIPTS_DIR, "producer");
    const started = performance.now();
    const read = await runCutPreviewProcess({ command: pythonInterpreter(), args: ["-c", PYTHON_READ, invocation.inputPath, invocation.inputSha256],
      cwd: producer, timeoutMs: Math.min(120_000, heldRemaining()), trackForShutdown: true,
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", PYTHONPATH: producer } });
    const python = JSON.parse(read.stdout.trim());
    assert.equal(python.documentCount, 14); assert.equal(python.graphicCount, 0); assert.equal(python.profile, SCREENED_CAPTION_SHORT_PROFILE);
    assert.ok(python.executionClosure.some((row: { path: string }) => row.path === "schemas/producer/treatment-proposal-v6.schema.json"));
    guard(); heldRemaining();
    finishGuidedOperation(operation, { state: "TEST-input-only-not-rendered", generationStartedAt: proposal.generationStartedAt,
      budget: budget.observe(), openingApproved: false, deliveryApproved: false });
    createHumanCutIndex(path.join(operation.execution, "TEST-python-input-read.json"), { python, elapsedMs: performance.now() - started,
      actualAsr: false, genuineHumanAcceptance: false, openingRendered: false, openingApproved: false });
    return { invocation, observed, python, operation };
  } finally { lease.release(); }
}
