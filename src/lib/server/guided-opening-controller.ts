import path from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { canonicalProducerDir } from "@/app/api/producer/auto-edit/request";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { exactKeys } from "@/lib/producer/contracts/validation";
import { acquireGuidedMutation, guidedOperation, finishGuidedOperation, writeGuidedObject } from "./guided-cut-v2-store";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { readGuidedProposalReadiness } from "./guided-proposal-review-store";
import { assertOpeningSubmission } from "./guided-opening-authority";
import { writeGuidedOpeningMediaInput } from "./guided-opening-media-input";
import { executeGuidedOpeningUnderLease } from "./guided-opening-execution";
import { holdOpeningControllerLifecycle, releaseOpeningControllerLease, type OpeningControllerLifecycle } from "./guided-opening-controller-lifecycle";
import { guardGenerationAttempt } from "./generation-clock-watermark";
import { startHandedOffOpeningAttempt } from "./opening-handoff-clock";
import { createHumanCutIndex } from "./human-cut-acceptance-store";
import { readOpeningLaunchIntent, readOpeningLaunchActivation, assertOpeningControllerSelf,
  optionalLaunchRecord, createOpeningLaunchRecord, openingControllerFiles } from "./guided-opening-launch-store";

type Launch = NonNullable<ReturnType<typeof readOpeningLaunchIntent>>;

function assertHandoffRelease(row: Record<string, unknown>, intentHash: string, activationHash: string) {
  const keys = ["schemaVersion", "intentHash", "activationHash"];
  exactKeys(row, keys, keys, "opening handoff release");
  if (row.schemaVersion !== 1 || row.intentHash !== intentHash || row.activationHash !== activationHash) {
    throw new Error("Opening controller release differs from its exact activation");
  }
}

/** No project lease, input materialization or subprocess until the parent explicitly released its lease. */
export async function waitForOpeningHandoff(held: Launch, timeoutMs = 20_000) {
  const began = performance.now();
  while (performance.now() - began < timeoutMs) {
    const active = readOpeningLaunchActivation(held);
    if (active) assertOpeningControllerSelf(active.activation);
    const released = optionalLaunchRecord(path.join(held.root, "released.json"));
    if (released && active) {
      assertHandoffRelease(released.value, held.hash, active.hash);
      return active;
    }
    await delay(50);
  }
  throw new Error("Opening handoff was not confirmed; retain launch intent for manual recovery");
}

/** Fixed detached entry point. One activation authorizes only this process, never a controller restart. */
export async function runGuidedOpeningController(rawDir: unknown, journalHash: string) {
  const began = performance.now(), dir = canonicalProducerDir(rawDir), held = readOpeningLaunchIntent(dir, journalHash);
  if (!held) throw new Error("Opening controller has no durable launch intent");
  const active = await waitForOpeningHandoff(held);
  createOpeningLaunchRecord(held.root, "controller-started.json", { schemaVersion: 1,
    intentHash: held.hash, activationHash: active.hash, owner: active.activation.owner, startedAt: new Date().toISOString() });
  let executionId: string | null = null;
  try {
    const result = await executeLaunchedOpening({ held, active, controllerStartedMono: began,
      onExecution: (id) => { executionId = id; } });
    createOpeningLaunchRecord(held.root, "outcome.json", { schemaVersion: 1, kind: "guided-opening-controller-outcome",
      intentHash: held.hash, executionId, completedAt: new Date().toISOString(), elapsedMs: performance.now() - began,
      state: "selected-not-approved", error: null, selectionHash: result.selection.selectionHash });
  } catch (error) {
    createOpeningLaunchRecord(held.root, "outcome.json", { schemaVersion: 1, kind: "guided-opening-controller-outcome",
      intentHash: held.hash, executionId, completedAt: new Date().toISOString(), elapsedMs: performance.now() - began,
      state: "failed", error: String(error).slice(0, 2048), selectionHash: null });
    throw error;
  }
}

/** A failed release never erases the original execution failure or reports an uncertain lease as released. */
function finishControllerLease(lifecycle: OpeningControllerLifecycle, failures: unknown[]): void {
  try { releaseOpeningControllerLease(lifecycle); }
  catch (releaseError) {
    if (failures.length) throw new AggregateError([...failures, releaseError], "Opening failed and original lease release remains unverified");
    throw releaseError;
  }
}

async function executeLaunchedOpening(input: { held: Launch; active: NonNullable<ReturnType<typeof readOpeningLaunchActivation>>;
  controllerStartedMono: number; onExecution: (id: string) => void }) {
  const { held, active } = input, { dir, submission, origin } = held.intent;
  const carried = startHandedOffOpeningAttempt({ origin, handoff: active.activation.handoff,
    startupElapsedMs: performance.now() - input.controllerStartedMono });
  carried.remainingMs();
  const lease = await acquireGuidedMutation(dir, { workflowVersion: 2, action: "prepare-guided-opening",
    expectedStatus: "treatment_admitted", expectedToken: submission.expectedToken, expectedJournalHash: submission.expectedJournalHash });
  const lifecycle = holdOpeningControllerLifecycle({ launch: held, activation: active, lease }), failures: unknown[] = [];
  try {
    const guard = cutPreviewLeaseGuard(dir, lease), proposal = readGuidedProposalReadiness(dir);
    assertOpeningSubmission(proposal, submission); assertOpeningControllerSelf(active.activation); guard(); carried.remainingMs();
    if (proposal.clock.hash !== origin.clockHash || proposal.generationStartedAt !== origin.startedAt
        || canonicalJsonSha256(openingControllerFiles(proposal)) !== canonicalJsonSha256(held.intent.controllerFiles)
        || readOpeningLaunchIntent(dir, submission.expectedJournalHash)?.hash !== held.hash) {
      throw new Error("Opening launch lost its original code, clock or exact intent");
    }
    const operation = guidedOperation({ dir, id: submission.idempotencyKey, submission, receivedAt: held.intent.receivedAt });
    input.onExecution(operation.executionId);
    const budget = guardGenerationAttempt({ dir, origin, executionId: operation.executionId, guard }, carried);
    createHumanCutIndex(path.join(operation.execution, "budget-admission.json"), budget.admission);
    const invocation = writeGuidedOpeningMediaInput({ proposal, operation, lease, remainingMs: budget.remainingMs });
    const result = await executeGuidedOpeningUnderLease({ proposal, operation, invocation, lease,
      remainingMs: budget.remainingMs, budgetAdmissionHash: writeGuidedObject(dir, budget.admission) }, {}, lifecycle);
    finishGuidedOperation(operation, { state: "opening-selected-not-approved", launchIntentHash: held.hash,
      selectionHash: result.selection.selectionHash, generationStartedAt: origin.startedAt,
      budget: budget.observe(), selectionElapsedMs: result.selectionElapsedMs, openingApproved: false, deliveryApproved: false });
    return result;
  } catch (error) { failures.push(error); throw error; }
  finally { finishControllerLease(lifecycle, failures); }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.length !== 4) { process.stderr.write("Opening controller requires only dir and exact journal hash\n"); process.exitCode = 1; }
  else runGuidedOpeningController(process.argv[2], process.argv[3]).catch((error) => {
    process.stderr.write(`${String(error).slice(0, 2048)}\n`); process.exitCode = 1;
  });
}
