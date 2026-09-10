/** Direct Codex/skill entrypoint to EXISTING opening services; no web server required. */
import path from "node:path";
import { canonicalProducerDir } from "../../src/app/api/producer/auto-edit/request";
import { observeCutPreviewFile } from "../../src/app/api/producer/auto-edit/cut-preview-receipt";
import { parsePrepareGuidedOpening, parseRecoverGuidedOpeningCleanup,
  parseRecoverCompletedOpeningCleanup } from "../../src/lib/producer/contracts/guided-opening-v1";
import { parseGuidedOpeningApprovalSubmission } from "../../src/lib/producer/contracts/guided-opening-approval-v1";
import { readGuidedOpeningStatus } from "../../src/lib/server/guided-opening-status";
import { readGuidedOpeningLaunchStatus } from "../../src/lib/server/guided-opening-launch-status";
import { launchGuidedOpening } from "../../src/lib/server/guided-opening-launcher";
import { readSelectedOpeningMedia } from "../../src/lib/server/guided-opening-selection";
import { approveGuidedOpening } from "../../src/lib/server/guided-opening-approval";
import { createOpeningProtectedCleanupClock } from "../../src/lib/server/guided-opening-cleanup";
import { reconcilePendingSourceColorCleanup, reconcileCompletedSourceColorCleanup } from "../../src/lib/server/guided-source-color-cleanup-recovery";
import { readPendingOpeningCleanup, assertPendingOpeningCleanupRead, readCompletedOpeningCleanup,
  assertCompletedOpeningCleanupRead } from "../../src/lib/server/guided-opening-cleanup-store";

const MAX_REQUEST_BYTES = 16_384;
const USAGE = "node --import tsx scripts/producer/guided-opening.ts "
  + "status|launch-status|review-files|cleanup-status|completed-cleanup-status <producer-dir> OR "
  + "launch|approve|recover-cleanup|recover-completed-cleanup <producer-dir> <request.json>";

/** Service injection exists for no-media tests; CLI input cannot replace these dependencies. */
export const openingCommandServices = {
  canonicalDir: canonicalProducerDir, status: readGuidedOpeningStatus,
  launchStatus: readGuidedOpeningLaunchStatus, launch: launchGuidedOpening,
  selected: readSelectedOpeningMedia, observeFile: observeCutPreviewFile,
  approve: approveGuidedOpening,
  cleanupClock: createOpeningProtectedCleanupClock, recoverCleanup: reconcilePendingSourceColorCleanup,
  pendingCleanup: readPendingOpeningCleanup,
  completedCleanup: readCompletedOpeningCleanup, recoverCompletedCleanup: reconcileCompletedSourceColorCleanup,
};

function boundedPath(value: string): string {
  if (!value || value.length > 4096 || /[\0\r\n]/.test(value)) throw new Error("Opening command path is invalid");
  return path.resolve(value);
}

/** Reject symlink/special/oversized/racing files using the existing descriptor-bound reader. */
function readCommandJson(file: string): unknown {
  const observed = observeCutPreviewFile(boundedPath(file), MAX_REQUEST_BYTES, true);
  return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(observed.bytes));
}

/** Exact launch request only; a human decision is a different closed operation. */
export function readOpeningCommandRequest(file: string) {
  return parsePrepareGuidedOpening(readCommandJson(file));
}

/** All human attestations must already be explicit; this command never fills them. */
export function readOpeningApprovalCommandRequest(file: string) {
  return parseGuidedOpeningApprovalSubmission(readCommandJson(file));
}

/** Cleanup is an exact retained checkpoint operation, never a caller-supplied success or deadline. */
export function readOpeningCleanupCommandRequest(file: string) {
  return parseRecoverGuidedOpeningCleanup(readCommandJson(file));
}

function cleanupStatus(dir: string, services: typeof openingCommandServices) {
  const pending = services.pendingCleanup(dir);
  const request = parseRecoverGuidedOpeningCleanup({ schemaVersion: 1, operation: "recover-guided-opening-cleanup",
    expectedToken: pending.job.token, expectedJournalHash: pending.pendingJournalHash, claimHash: pending.fact.claimHash });
  const result = { ok: true, scope: "pending-reservation-retirement-not-native-cleanup-render-or-approval",
    state: "pending-retirement", request, mediaSelected: false, openingApproved: false, deliveryApproved: false };
  assertPendingOpeningCleanupRead(pending); return result;
}

function completedCleanupStatus(dir: string, services: typeof openingCommandServices) {
  const completed = services.completedCleanup(dir);
  const requests = completed.attempts.map(row => parseRecoverCompletedOpeningCleanup({ schemaVersion: 1,
    operation: "recover-completed-guided-opening-cleanup", expectedToken: completed.job.token,
    expectedJournalHash: completed.journalHash, claimHash: completed.claimHash,
    cleanupAttemptId: row.attemptId, preparedSha256: row.preparedRef.sha256 }));
  const result = { ok: true, scope: "completed-cleanup-adoption-not-native-replay-render-or-approval",
    state: "completed-not-committed", requests, mediaSelected: false, openingApproved: false, deliveryApproved: false };
  assertCompletedOpeningCleanupRead(completed); return result;
}

function recoverCleanupCommand(input: { command: string; dir: string; request: string;
  clock: ReturnType<typeof createOpeningProtectedCleanupClock> }, services: typeof openingCommandServices) {
  if (input.command === "recover-completed-cleanup") {
    const submission = parseRecoverCompletedOpeningCleanup(readCommandJson(input.request));
    return services.recoverCompletedCleanup({ dir: input.dir, expectedToken: submission.expectedToken,
      expectedJournalHash: submission.expectedJournalHash, expectedClaimHash: submission.claimHash,
      cleanupAttemptId: submission.cleanupAttemptId, preparedSha256: submission.preparedSha256, clock: input.clock });
  }
  const submission = readOpeningCleanupCommandRequest(input.request);
  return services.recoverCleanup({ dir: input.dir, expectedToken: submission.expectedToken,
    expectedJournalHash: submission.expectedJournalHash, expectedClaimHash: submission.claimHash, clock: input.clock });
}

/** Return locally previewable paths only after checking current selected bytes.
 * This is point-in-time file identity, not source requalification, decoded QC or approval. */
function reviewFiles(dir: string, services: typeof openingCommandServices) {
  const started = performance.now(), selected = services.selected(dir);
  const checked = new Map<string, ReturnType<typeof observeCutPreviewFile>>();
  for (const row of Object.values(selected.rows)) {
    const observed = checked.get(row.path) ?? services.observeFile(row.path, 2 * 1024 ** 3);
    if (observed.sha256 !== row.mediaSha256 || observed.sizeBytes !== row.sizeBytes) {
      throw new Error("Selected opening media bytes changed; no review path is available");
    }
    checked.set(row.path, observed);
  }
  const current = services.selected(dir);
  if (current.selectionHash !== selected.selectionHash || current.observed.sha256 !== selected.observed.sha256) {
    throw new Error("Opening selection changed while checking review files");
  }
  return { ok: true, scope: "selected-local-opening-files-not-source-requalification-or-approval",
    selectionHash: selected.selectionHash, media: selected.rows, sourceFreshness: selected.sourceFreshness,
    observedAt: new Date().toISOString(), fileCheckElapsedMs: performance.now() - started,
    subjectiveListening: "not-performed-by-system", openingApprovalGranted: false,
    bodyGenerated: false, deliveryApproved: false };
}

/** Each mutation is explicit and isolated: launch never approves; approval never renders the body. */
export async function executeOpeningCommand(argv: string[], services = openingCommandServices) {
  const [command, directory, request] = argv;
  if (argv.length === 1 && command === "--help") return { usage: USAGE,
    note: "Run from the repository root. Status never renders. Launch needs an existing reviewed guided project and an exact persisted request. Approve records only an explicit human decision after viewing/listening; no body generation or delivery is implied. Cleanup-status reads a pending reservation retirement; completed-cleanup-status reads completed work without that checkpoint. Use the matching recovery command with one exact persisted request. Each recovery never retries native work or renews a render allowance, and grants no media approval." };
  const valid = (["status", "launch-status", "review-files", "cleanup-status", "completed-cleanup-status"].includes(command) && argv.length === 2)
    || (["launch", "approve", "recover-cleanup", "recover-completed-cleanup"].includes(command) && argv.length === 3);
  if (!valid) throw new Error(USAGE);
  const cleanupClock = ["recover-cleanup", "recover-completed-cleanup"].includes(command) ? services.cleanupClock() : undefined;
  const dir = services.canonicalDir(boundedPath(directory));
  if (command === "status") return services.status(dir);
  if (command === "launch-status") return services.launchStatus(dir);
  if (command === "review-files") return reviewFiles(dir, services);
  if (command === "cleanup-status") return cleanupStatus(dir, services);
  if (command === "completed-cleanup-status") return completedCleanupStatus(dir, services);
  if (cleanupClock) return recoverCleanupCommand({ command, dir, request, clock: cleanupClock }, services);
  if (command === "approve") {
    const submission = readOpeningApprovalCommandRequest(request);
    const result = await services.approve({ dir, submission });
    return { ...result, openingApproved: true, bodyGenerated: false, deliveryApproved: false,
      verificationScope: result.replayed ? "recorded-decision-acknowledgment-no-fresh-readback"
        : "fresh-readback-for-this-human-opening-decision" };
  }
  // The caller retains its UUID across retries. Never generate one, rewrite a
  // request, refresh a deadline, or retry a failed/unknown launch here.
  const submission = readOpeningCommandRequest(request);
  return services.launch({ dir, submission });
}

if (require.main === module) {
  executeOpeningCommand(process.argv.slice(2)).then((result) => {
    process.stdout.write(JSON.stringify(result) + "\n");
  }).catch((error: unknown) => {
    const message = error instanceof Error ? error.message.slice(0, 2048) : "Opening command failed";
    process.stderr.write(JSON.stringify({ ok: false, error: message }) + "\n");
    process.exitCode = 1;
  });
}
