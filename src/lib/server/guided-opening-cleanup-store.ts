import path from "node:path";
import { lstatSync } from "node:fs";
import { isDeepStrictEqual } from "node:util";
import { exactKeys, sha256, uuid } from "@/lib/producer/contracts/validation";
import { parseOpeningCleanupStdout } from "@/lib/producer/contracts/guided-opening-cleanup-v1";
import { readCutPreviewObject } from "@/app/api/producer/auto-edit/cut-preview-receipt";
import { readGuidedObject, strictGuidedTimestamp } from "./guided-cut-v2-store";
import { readRetainedOpeningExecutionClaim, readGuidedOpeningExecutionClaim } from "./guided-opening-claim";
import { readStoppedOpeningProcess } from "./guided-opening-process";
import { observeHumanCutJob } from "./human-cut-acceptance-store";
import { canonicalJsonSha256 } from "./auto-edit-hash";
import { autoEditJobPath, parseAutoEditJobRecord } from "./auto-edit-job-persistence";
import { assertOpeningCleanupIdentity } from "./guided-opening-cleanup";
import { readFinalSourceColorCleanupForJournal, assertSourceColorFinalCleanupMetadata } from "./guided-source-color-cleanup-final-read";
import { parsePreparedSourceColorCleanupFact } from "@/lib/producer/contracts/guided-source-color-cleanup-facts";
import { readSourceColorCleanupPending, assertSourceColorCleanupPendingMetadata } from "./guided-source-color-cleanup-pending-read";
import { readSourceColorCleanupHistory, assertSourceColorCleanupHistoryMetadata } from "./guided-source-color-cleanup-history";
import { sourceColorCleanupAttemptReadDependencies } from "./guided-source-color-cleanup-attempt-read";
import { capturePublication, assertPublication } from "./guided-source-color-cleanup-pending-commit";
import { snapshotSourceColorMetadata, freezeSourceColorValue } from "./guided-source-color-staging-hold";

/** Code-only TEST claim/native leaves still return the actual authenticated final reader result. */
export const openingCleanupStoreDependencies = { final: readFinalSourceColorCleanupForJournal, pending: readSourceColorCleanupPending,
  completedClaim: readGuidedOpeningExecutionClaim, get completedHistory() { return sourceColorCleanupAttemptReadDependencies; } };
const pendingProofReads = new WeakMap<object, () => void>();
const completedProofReads = new WeakMap<object, () => void>();
const finalProofReads = new WeakMap<object, ReturnType<typeof readFinalSourceColorCleanupForJournal>>();

/** One observation allowance, not a renewal of either the original render or destructive cleanup clock. */
function proofReadRemainder(): () => number {
  const started = performance.now();
  return () => {
    const elapsed = performance.now() - started;
    if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed >= 30_000) throw new Error("Opening cleanup read-only observation budget expired");
    return 30_000 - elapsed;
  };
}

/** Current prepared evidence only. It does not grant retirement, cleanup replay, selection or approval. */
export function readPendingOpeningCleanup(dir: string) {
  const remaining = proofReadRemainder(), current = observeHumanCutJob(dir), pointer = current.job.guidedHandoffV2;
  const claimHash = sha256(pointer?.openingExecutionClaimHash, "pending opening claim");
  const factHash = sha256(pointer?.openingCleanupHash, "pending opening cleanup");
  const fact = parsePreparedSourceColorCleanupFact(readGuidedObject(dir, factHash));
  if (fact.claimHash !== claimHash || canonicalJsonSha256(fact) !== factHash) throw new Error("Pending opening cleanup names another current claim");
  const pending = openingCleanupStoreDependencies.pending({ dir, guard: () => { remaining(); }, remainingMs: remaining });
  assertSourceColorCleanupPendingMetadata(pending);
  if (pending.scope !== "current-pending-source-color-cleanup-not-retirement-or-approval"
      || pending.pendingJournalHash !== current.sha256 || pending.factHash !== factHash
      || pending.fact.claimHash !== claimHash || pending.held.claimHash !== claimHash) {
    throw new Error("Pending opening cleanup differs from its exact current journal and claim");
  }
  if (observeHumanCutJob(dir).sha256 !== current.sha256) throw new Error("Pending opening cleanup changed during observation");
  const check = () => { assertSourceColorCleanupPendingMetadata(pending); remaining(); };
  check(); pendingProofReads.set(pending, check); return pending;
}

/** Same original read allowance after display/request callbacks; never resurrects a cleanup clock. */
export function assertPendingOpeningCleanupRead(pending: ReturnType<typeof readPendingOpeningCleanup>): void {
  const check = pendingProofReads.get(pending);
  if (!check) throw new Error("Pending opening cleanup needs its actual original bounded proof read");
  check();
}

/** Explicit on-demand metadata status, not automatic status polling or native/retirement authority. */
export function readCompletedOpeningCleanup(dir: string) {
  const remaining = proofReadRemainder(), current = observeHumanCutJob(dir), pointer = current.job.guidedHandoffV2;
  const journal = capturePublication(autoEditJobPath(dir), current.sha256), job = freezeSourceColorValue(snapshotSourceColorMetadata(current.job));
  const claimHash = sha256(pointer?.openingExecutionClaimHash, "completed opening claim");
  if (pointer?.openingCleanupHash) throw new Error("Completed cleanup status requires the original precleanup checkpoint");
  const held = openingCleanupStoreDependencies.completedClaim(dir), fixed = snapshotSourceColorMetadata(held);
  const guard = () => {
    assertPublication(journal);
    if (!isDeepStrictEqual(held, fixed) || held.sha256 !== current.sha256 || held.claimHash !== claimHash
        || !isDeepStrictEqual(held.job, job) || !isDeepStrictEqual(held.bytes, current.bytes)) {
      throw new Error("Completed opening cleanup differs from its original current claim/journal");
    }
    remaining();
  };
  const history = readSourceColorCleanupHistory({ held, guard, remainingMs: remaining }, openingCleanupStoreDependencies.completedHistory);
  const result = Object.freeze({ scope: "completed-cleanup-history-status-not-adoption-native-replay-or-approval" as const,
    job, journalHash: current.sha256, claimHash, attempts: history.attempts });
  const check = () => { guard(); assertSourceColorCleanupHistoryMetadata(history); remaining(); };
  check(); completedProofReads.set(result, check); return result;
}

/** Private successful status-read identity and the same 30s observation cap, never a cleanup work clock. */
export function assertCompletedOpeningCleanupRead(value: ReturnType<typeof readCompletedOpeningCleanup>): void {
  const check = completedProofReads.get(value);
  if (!check) throw new Error("Completed cleanup status requires its actual original bounded read");
  check();
}

function absent(file: string): void {
  try { lstatSync(file); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return; throw error; }
  throw new Error("Opening cleanup attempt has a retained failure; no success can be selected");
}

function receipt(row: ReturnType<typeof readGuidedObject>) {
  const keys = ["schemaVersion", "kind", "scope", "claimHash", "beforeJournalHash", "cleanupAttemptId",
    "processOutcomeSha256", "cleanupStartSha256", "cleanupOutputSha256", "cleanupResultHash", "clockHash", "generationStartedAt", "createdAt",
    "claimRetained", "openingApproved", "deliveryApproved"];
  exactKeys(row, keys, keys, "opening cleanup commit"); uuid(row.cleanupAttemptId, "cleanupAttemptId");
  if (typeof row.claimRetained !== "boolean") throw new Error("Opening cleanup commit must state whether the claim was retained");
  for (const key of ["claimHash", "beforeJournalHash", "processOutcomeSha256", "cleanupStartSha256", "cleanupOutputSha256", "cleanupResultHash", "clockHash"]) sha256(row[key], key);
  if (row.schemaVersion !== 1 || row.kind !== "guided-opening-cleanup-commit"
      || row.scope !== "exact-owned-resource-cleanup-not-opening-or-delivery-approval" || row.openingApproved !== false || row.deliveryApproved !== false) {
    throw new Error("Opening cleanup commit is not exact resource-only evidence");
  }
  strictGuidedTimestamp(row.createdAt); strictGuidedTimestamp(row.generationStartedAt); return row;
}

function attemptEvidence(dir: string, row: ReturnType<typeof receipt>, held: ReturnType<typeof readRetainedOpeningExecutionClaim>) {
  const root = path.join(path.dirname(held.claimPath), "cleanup-attempts", String(row.cleanupAttemptId)); absent(path.join(root, "failure.json"));
  const startFile = readCutPreviewObject(path.join(root, "start.json")), outputFile = readCutPreviewObject(path.join(root, "output.json"));
  const start = startFile.value, output = outputFile.value, stop = readStoppedOpeningProcess(held);
  const startKeys = ["schemaVersion", "kind", "cleanupAttemptId", "claimHash", "processOutcomeSha256", "beforeJournalHash", "clockHash", "generationStartedAt", "receivedAt", "startedAt", "budgetScope"];
  const outputKeys = ["schemaVersion", "kind", "stdout", "stderr", "mediaProcessGroupStopped", "cleanupProcessGroupStopped", "observedAt", "elapsedMs"];
  exactKeys(start, startKeys, startKeys, "opening cleanup start"); exactKeys(output, outputKeys, outputKeys, "opening cleanup owned output");
  const stamps = [stop.receipt.finishedAt, start.receivedAt, start.startedAt, output.observedAt, row.createdAt].map(strictGuidedTimestamp);
  if (startFile.sha256 !== row.cleanupStartSha256 || outputFile.sha256 !== row.cleanupOutputSha256 || stop.receiptSha256 !== row.processOutcomeSha256
      || start.schemaVersion !== 1 || start.kind !== "guided-opening-cleanup-start" || start.cleanupAttemptId !== row.cleanupAttemptId
      || start.claimHash !== held.claimHash || start.processOutcomeSha256 !== stop.receiptSha256 || start.beforeJournalHash !== held.sha256
      || start.clockHash !== held.claim.clockHash || start.generationStartedAt !== held.claim.generationStartedAt
      || start.budgetScope !== "separate-protected-cleanup-not-render-allowance" || output.schemaVersion !== 1
      || output.kind !== "guided-opening-cleanup-owned-output" || output.mediaProcessGroupStopped !== true || output.cleanupProcessGroupStopped !== true
      || stamps.some((at, index) => index > 0 && at < stamps[index - 1]) || typeof output.elapsedMs !== "number"
      || !Number.isFinite(output.elapsedMs) || output.elapsedMs < 0 || output.elapsedMs > 300_000
      || typeof output.stdout !== "string" || typeof output.stderr !== "string" || Buffer.byteLength(output.stderr, "utf8") > 2 * 1024 * 1024) {
    throw new Error("Opening cleanup lost its actual stopped-process, exact attempt or clock lineage");
  }
  const result = parseOpeningCleanupStdout(output.stdout); assertOpeningCleanupIdentity(result, held);
  if (result.elapsedMs > output.elapsedMs + 1 || canonicalJsonSha256(result) !== row.cleanupResultHash
      || canonicalJsonSha256(readGuidedObject(dir, String(row.cleanupResultHash))) !== row.cleanupResultHash) throw new Error("Opening cleanup result differs from actual owned stdout");
  absent(path.join(root, "failure.json"));
  return { start, output, stop, result };
}

/** Historical exact cleanup read only. No Docker call, source freshness, active execution or media approval is inferred. */
function cleanupForJournal(dir: string, current: ReturnType<typeof observeHumanCutJob>, journalPath: string, remainingMs: () => number) {
  const pointer = current.job.guidedHandoffV2, hash = pointer?.openingCleanupHash;
  if (!hash) throw new Error("No committed opening resource cleanup exists");
  const actual = readGuidedObject(dir, hash);
  if (actual.schemaVersion === 2 && actual.kind === "guided-opening-source-color-cleanup-commit") {
    remainingMs();
    return openingCleanupStoreDependencies.final({ dir, journal: { path: journalPath, observed: current }, guard: () => { remainingMs(); }, remainingMs });
  }
  const row = receipt(actual), held = readRetainedOpeningExecutionClaim(dir, String(row.beforeJournalHash));
  if (row.claimRetained !== false) throw new Error("Opening cleanup retained an unresolved forced-stop claim; nothing is selectable");
  const { openingExecutionClaimHash: _oldClaim, openingProcessOutcomeHash: _oldProcess, openingCleanupHash: _oldCleanup,
    openingMediaSelectionHash: _oldSelection, openingApprovalHash: _oldApproval, ...oldPointer } = held.job.guidedHandoffV2!;
  const { openingExecutionClaimHash: _newClaim, openingProcessOutcomeHash: _newProcess, openingCleanupHash: _newCleanup,
    openingMediaSelectionHash: _newSelection, openingApprovalHash: _newApproval, ...currentPointer } = pointer!;
  void _oldClaim; void _oldCleanup; void _newClaim; void _newCleanup; void _oldProcess; void _newProcess; void _oldSelection; void _newSelection;
  void _oldApproval; void _newApproval;
  if (_oldSelection !== undefined || _oldApproval !== undefined) throw new Error("Opening cleanup was claimed after a selection or approval; lineage is not exact");
  if (row.claimHash !== held.claimHash || row.clockHash !== held.claim.clockHash || row.generationStartedAt !== held.claim.generationStartedAt
      || current.job.status !== "treatment_admitted" || current.job.token !== held.job.token || current.job.attempts !== held.job.attempts
      || canonicalJsonSha256(current.job.ctx) !== canonicalJsonSha256(held.job.ctx) || canonicalJsonSha256(oldPointer) !== canonicalJsonSha256(currentPointer)
      || String(row.createdAt) > current.job.updatedAt) throw new Error("Opening cleanup is not the exact retained job/draft/claim");
  const evidence = attemptEvidence(dir, row, held);
  return { ...current, held, receipt: row, cleanupHash: hash, evidence,
    observationScope: "historical-exact-resource-cleanup-not-current-media-approval" as const, mediaSelected: false as const };
}

/** Current reader retains its exact current-journal observation before and after every proof read. */
export function readCommittedOpeningCleanup(dir: string) {
  const remaining = proofReadRemainder(), current = observeHumanCutJob(dir), result = cleanupForJournal(dir, current, autoEditJobPath(dir), remaining);
  if (observeHumanCutJob(dir).sha256 !== current.sha256) throw new Error("Opening cleanup pointer changed during observation");
  if ("readBudgetScope" in result) { assertSourceColorFinalCleanupMetadata(result); remaining(); finalProofReads.set(result, result); }
  return result;
}

/** Explicit retained bytes only. A caller must separately prove any current body-claim edge before using history. */
export function readHistoricalOpeningCleanup(dir: string, journalHash: string) {
  const remaining = proofReadRemainder();
  const file = path.join(dir, "human-cut-job-snapshots", `${sha256(journalHash, "historical opening journal")}.json`);
  const snapshot = readCutPreviewObject(file), job = parseAutoEditJobRecord(snapshot.value);
  if (snapshot.sha256 !== journalHash || job.ctx.dir !== dir) throw new Error("Historical opening journal changed or names another project");
  const result = cleanupForJournal(dir, { ...snapshot, job }, file, remaining);
  if (readCutPreviewObject(file).sha256 !== journalHash) throw new Error("Historical opening journal changed during proof read");
  const historical = { ...result, observationScope: "held-historical-journal-cleanup-not-current-selection-or-source-freshness" as const };
  if ("readBudgetScope" in result) {
    Object.freeze(historical); assertSourceColorFinalCleanupMetadata(result); remaining(); finalProofReads.set(historical, result);
  }
  return historical;
}

/** Actual source-color store returns only; copied/legacy/prepared data cannot inherit a final proof.
 * This is a callback-free metadata sweep, not a proof-budget renewal or an old assertCurrent replay.
 * The caller retains its own enclosing deadline; V1 readers and their existing semantics are unchanged.
 */
export function assertOpeningCleanupMetadata(value: ReturnType<typeof readCommittedOpeningCleanup> | ReturnType<typeof readHistoricalOpeningCleanup>): void {
  const original = finalProofReads.get(value);
  if (!original) throw new Error("Opening cleanup metadata requires its actual source-color final cleanup store read");
  assertSourceColorFinalCleanupMetadata(original);
}
