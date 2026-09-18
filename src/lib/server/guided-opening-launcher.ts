import path from "node:path";
import { realpathSync, accessSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { canonicalProducerDir } from "@/app/api/producer/auto-edit/request";
import { cutPreviewLeaseGuard } from "@/app/api/producer/auto-edit/cut-preview-lease";
import { parsePrepareGuidedOpening } from "@/lib/producer/contracts/guided-opening-v1";
import { acquireGuidedMutation } from "./guided-cut-v2-store";
import { assertOpeningSubmission } from "./guided-opening-authority";
import { openingMediaAuthority } from "./guided-opening-media-input";
import { readGuidedProposalReadiness } from "./guided-proposal-review-store";
import { captureOpeningAttemptStart } from "./opening-deadline";
import { guardGenerationAttempt } from "./generation-clock-watermark";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { captureProcessIdentity } from "./process-liveness";
import { captureOpeningRuntimeControl } from "./guided-opening-runtime-control";
import { createOpeningLaunchRecord, openingLaunchDirectory, readOpeningLaunchIntent, openingControllerFiles,
  assertOpeningControllerTools, strictOpeningControllerIdentity, type OpeningLaunchIntent } from "./guided-opening-launch-store";

function acknowledgement(intent: OpeningLaunchIntent, replayed: boolean) {
  return { ok: true as const, replayed, state: "launch-recorded" as const,
    journalHash: intent.submission.expectedJournalHash, requestId: intent.submission.idempotencyKey,
    openingApproved: false as const, bodyGenerated: false as const, deliveryApproved: false as const };
}

function retainedLaunch(dir: string, submission: ReturnType<typeof parsePrepareGuidedOpening>) {
  const held = readOpeningLaunchIntent(dir, submission.expectedJournalHash);
  if (!held) return null;
  if (canonicalJsonSha256(held.intent.submission) !== canonicalJsonSha256(submission)) {
    throw new Error("This exact journal already has an opening launch intent. Recheck its outcome; do not start a duplicate");
  }
  return acknowledgement(held.intent, true);
}

/** Explicit one-shot launch; HTTP lifetime does not own rendering or reset its deadline.
 * Unknown/failed launches are fenced, not automatically restarted. */
export async function launchGuidedOpening(input: { dir: unknown; submission: unknown }) {
  const submission = parsePrepareGuidedOpening(structuredClone(input.submission)), captured = captureOpeningAttemptStart();
  const dir = canonicalProducerDir(input.dir), replay = retainedLaunch(dir, submission);
  if (replay) return replay;
  const lease = await acquireGuidedMutation(dir, { workflowVersion: 2, action: "prepare-guided-opening",
    expectedStatus: "treatment_admitted", expectedToken: submission.expectedToken, expectedJournalHash: submission.expectedJournalHash });
  let released: { root: string; intentHash: string; activationHash: string; intent: OpeningLaunchIntent };
  try {
    const guard = cutPreviewLeaseGuard(dir, lease), proposal = readGuidedProposalReadiness(dir);
    assertOpeningSubmission(proposal, submission); openingMediaAuthority(proposal); guard();
    if (proposal.pointer.openingExecutionClaimHash || proposal.pointer.openingMediaSelectionHash) {
      throw new Error("An existing owned or selected opening must be resolved before a new launch");
    }
    const launchId = randomUUID(), origin = { clockHash: proposal.clock.hash, startedAt: proposal.generationStartedAt };
    const budget = guardGenerationAttempt({ dir, origin, executionId: launchId, guard }, captured.start(origin));
    budget.remainingMs();
    assertOpeningControllerTools(); captureOpeningRuntimeControl(proposal); // Refuse missing controls before the permanent spawn fence.
    const intent: OpeningLaunchIntent = { schemaVersion: 1, kind: "guided-opening-launch-intent", dir, launchId,
      submission, receivedAt: captured.receivedAt, origin, controllerFiles: openingControllerFiles(proposal) };
    released = await spawnController({ intent, budget, guard });
  } finally { lease.release(); }
  // The child never races a still-held parent lease. A crash before this marker is unknown, not retry permission.
  createOpeningLaunchRecord(released.root, "released.json", { schemaVersion: 1,
    intentHash: released.intentHash, activationHash: released.activationHash });
  return acknowledgement(released.intent, false);
}

function spawnController(input: { intent: OpeningLaunchIntent;
  budget: ReturnType<ReturnType<typeof captureOpeningAttemptStart>["start"]>; guard: () => void }) {
  const { intent, budget, guard } = input, repo = realpathSync(process.cwd());
  const worker = path.join(repo, "src/lib/server/guided-opening-controller.ts");
  accessSync(path.join(repo, "node_modules/tsx/package.json")); accessSync(worker);
  guard(); budget.remainingMs();
  const root = openingLaunchDirectory(intent.dir, intent.submission.expectedJournalHash, true);
  const intentHash = createOpeningLaunchRecord(root, "intent.json", intent);
  const child = spawn(process.execPath, ["--import", "tsx", worker, intent.dir, intent.submission.expectedJournalHash], {
    cwd: repo, env: { ...process.env, SNIPER_RUNTIME_REPO_ROOT: repo, TSX_DISABLE_CACHE: "1" },
    detached: true, stdio: "ignore",
  });
  // A failed/ambiguous spawn leaves the immutable intent in place. Never infer absence from an error.
  child.once("error", () => { /* No automatic retry; the durable intent fences any possible child. */ });
  child.unref();
  if (!child.pid) throw new Error("Opening controller spawn has no verified PID; preserve its launch intent");
  const owner = strictOpeningControllerIdentity(captureProcessIdentity(child.pid));
  guard(); budget.remainingMs();
  const activationHash = createOpeningLaunchRecord(root, "activation.json", { schemaVersion: 1,
    kind: "guided-opening-controller-activation", intentHash, owner,
    handoff: { receivedAt: intent.receivedAt, admission: budget.admission, observation: budget.observe() } });
  return { root, intentHash, activationHash, intent };
}
