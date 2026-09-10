/** Closed two-CAS cleanup metadata. Parsing grants no process, lease, cleanup,
 * retirement or approval authority; actual readers join the original raw records
 * and journal edges. Legacy cleanup facts and the opening input schema are unchanged.
 */
import { exactKeys, isoDate, objectValue, sha256, uuid } from "./validation";
import { openingAbsolutePath } from "./guided-opening-media-v1";
import type { OpeningSourceColorCleanupEvidence } from "./guided-opening-cleanup-v2";

export type RawSourceColorCleanupRef = OpeningSourceColorCleanupEvidence["reservation"];
interface CleanupIdentity {
  claimHash: string; executionId: string; cleanupAttemptId: string;
  mediaSelected: false; openingApproved: false; deliveryApproved: false;
}
interface CleanupClock extends CleanupIdentity {
  clockHash: string; generationStartedAt: string; createdAt: string;
}
export interface PreparedSourceColorCleanupFact extends CleanupClock {
  schemaVersion: 2; kind: "guided-opening-source-color-cleanup-prepared";
  scope: "exact-owned-resource-cleanup-awaiting-reservation-retirement-not-approval";
  phase: "awaiting-retirement"; claimRetained: true;
  beforeJournalHash: string; processOutcomeSha256: string; cleanupStartSha256: string;
  cleanupOutputSha256: string; cleanupResultHash: string; cleanupInvocationSha256: string;
  reservation: RawSourceColorCleanupRef; archive: RawSourceColorCleanupRef; sourceColorHash: string;
}
export interface FinalSourceColorCleanupFact extends CleanupClock {
  schemaVersion: 2; kind: "guided-opening-source-color-cleanup-commit";
  scope: "exact-owned-resource-cleanup-and-reservation-retirement-not-approval";
  phase: "retired"; claimRetained: false;
  preparedFactHash: string; pendingJournalHash: string; retirementAck: RawSourceColorCleanupRef;
}
export interface SourceColorRetirementAck extends CleanupIdentity {
  schemaVersion: 1; kind: "guided-opening-source-color-retirement";
  scope: "exact-reservation-retirement-not-process-cleanup-or-approval";
  preparedFactHash: string; pendingJournalHash: string;
  reservation: RawSourceColorCleanupRef; archive: RawSourceColorCleanupRef;
  observedAt: string; disposition: "unlinked-original" | "already-absent-after-committed-intent";
}

const IDENTITY_KEYS = ["schemaVersion", "kind", "scope", "claimHash", "executionId", "cleanupAttemptId",
  "mediaSelected", "openingApproved", "deliveryApproved"];
const CLOCK_KEYS = [...IDENTITY_KEYS, "phase", "claimRetained", "clockHash", "generationStartedAt", "createdAt"];
const PREPARED_HASHES = ["beforeJournalHash", "processOutcomeSha256", "cleanupStartSha256", "cleanupOutputSha256",
  "cleanupResultHash", "cleanupInvocationSha256", "sourceColorHash"];
const PREPARED_KEYS = [...CLOCK_KEYS, ...PREPARED_HASHES, "reservation", "archive"];
const FINAL_KEYS = [...CLOCK_KEYS, "preparedFactHash", "pendingJournalHash", "retirementAck"];
const ACK_KEYS = [...IDENTITY_KEYS, "preparedFactHash", "pendingJournalHash", "reservation", "archive", "observedAt", "disposition"];
const MAX_RESERVATION_BYTES = 8 * 1024 * 1024;

function exact(value: unknown, keys: readonly string[], label: string) {
  const row = objectValue(value, label); exactKeys(row, keys, keys, label); return row;
}
function identifier(value: unknown, label: string): string {
  const result = uuid(value, label);
  if (result[14] !== "4") throw new Error(`${label} must be UUIDv4`);
  return result;
}
function stamp(value: unknown, label: string): string {
  const result = isoDate(value, label);
  if (new Date(result).toISOString() !== result) throw new Error(`${label} must have canonical UTC millisecond spelling`);
  return result;
}
function identity(row: Record<string, unknown>): void {
  sha256(row.claimHash, "cleanup claimHash"); identifier(row.executionId, "cleanup executionId");
  identifier(row.cleanupAttemptId, "cleanupAttemptId");
  if (row.mediaSelected !== false || row.openingApproved !== false || row.deliveryApproved !== false) {
    throw new Error("Source color cleanup facts cannot select or approve media");
  }
}
function clock(row: Record<string, unknown>): void {
  identity(row); sha256(row.clockHash, "cleanup clockHash");
  const start = stamp(row.generationStartedAt, "generationStartedAt"), end = stamp(row.createdAt, "createdAt");
  if (end < start) throw new Error("Cleanup fact predates its original generation clock");
}
function rawReference(value: unknown, maximum: number, label: string): RawSourceColorCleanupRef {
  const row = exact(value, ["path", "sha256", "sizeBytes"], label);
  openingAbsolutePath(row.path); sha256(row.sha256, `${label} raw SHA`);
  if (!Number.isSafeInteger(row.sizeBytes) || Number(row.sizeBytes) < 1 || Number(row.sizeBytes) > maximum) {
    throw new Error(`${label} raw size is outside its metadata bound`);
  }
  return row as unknown as RawSourceColorCleanupRef;
}
function attemptSuffix(row: Record<string, unknown>, file: RawSourceColorCleanupRef, name: string): void {
  const suffix = `/executions/${row.executionId}/cleanup-attempts/${row.cleanupAttemptId}/${name}`;
  if (!file.path.endsWith(suffix)) throw new Error("Cleanup metadata does not name its declared execution/attempt artifact");
}
function reservationArchive(row: Record<string, unknown>): void {
  const reservation = rawReference(row.reservation, MAX_RESERVATION_BYTES, "cleanup reservation");
  const archive = rawReference(row.archive, MAX_RESERVATION_BYTES, "cleanup reservation archive");
  if (!reservation.path.endsWith("/.sniper-color-resource/active.json")
      || reservation.sha256 !== archive.sha256 || reservation.sizeBytes !== archive.sizeBytes) {
    throw new Error("Cleanup archive must preserve the exact original active raw reference");
  }
  attemptSuffix(row, archive, "reservation.json");
}

/** A journal-held prepared fact is still pending: its claim must remain fenced. */
export function parsePreparedSourceColorCleanupFact(value: unknown): PreparedSourceColorCleanupFact {
  const row = exact(value, PREPARED_KEYS, "prepared source color cleanup fact");
  if (row.schemaVersion !== 2 || row.kind !== "guided-opening-source-color-cleanup-prepared"
      || row.scope !== "exact-owned-resource-cleanup-awaiting-reservation-retirement-not-approval"
      || row.phase !== "awaiting-retirement" || row.claimRetained !== true) throw new Error("Unsupported pending source color cleanup fact");
  clock(row); PREPARED_HASHES.forEach(key => sha256(row[key], key)); reservationArchive(row);
  return structuredClone(row) as unknown as PreparedSourceColorCleanupFact;
}

/** Final shape only. Actual readers must prove the pending-parent edge and raw acknowledgement. */
export function parseFinalSourceColorCleanupFact(value: unknown): FinalSourceColorCleanupFact {
  const row = exact(value, FINAL_KEYS, "final source color cleanup fact");
  if (row.schemaVersion !== 2 || row.kind !== "guided-opening-source-color-cleanup-commit"
      || row.scope !== "exact-owned-resource-cleanup-and-reservation-retirement-not-approval"
      || row.phase !== "retired" || row.claimRetained !== false) throw new Error("Unsupported final source color cleanup fact");
  clock(row); sha256(row.preparedFactHash, "preparedFactHash"); sha256(row.pendingJournalHash, "pendingJournalHash");
  attemptSuffix(row, rawReference(row.retirementAck, 128 * 1024, "retirement acknowledgement"), "retirement-ack.json");
  return structuredClone(row) as unknown as FinalSourceColorCleanupFact;
}

/** Honest disposition is retained verbatim; absent metadata is not proof of an earlier unlink. */
export function parseSourceColorRetirementAck(value: unknown): SourceColorRetirementAck {
  const row = exact(value, ACK_KEYS, "source color retirement acknowledgement");
  if (row.schemaVersion !== 1 || row.kind !== "guided-opening-source-color-retirement"
      || row.scope !== "exact-reservation-retirement-not-process-cleanup-or-approval"
      || !["unlinked-original", "already-absent-after-committed-intent"].includes(String(row.disposition))
      || typeof row.disposition !== "string") throw new Error("Unsupported source color retirement acknowledgement");
  identity(row); sha256(row.preparedFactHash, "preparedFactHash"); sha256(row.pendingJournalHash, "pendingJournalHash");
  stamp(row.observedAt, "retirement observedAt"); reservationArchive(row);
  return structuredClone(row) as unknown as SourceColorRetirementAck;
}
