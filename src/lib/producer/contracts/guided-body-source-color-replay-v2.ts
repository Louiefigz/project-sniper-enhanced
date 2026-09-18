/** Closed original-opening replay references only. JSON grants no source, native,
 * cleanup, body execution or approval authority; the server retains actual proofs.
 */
import { exactKeys, objectValue, sha256, uuid } from "./validation";
import { openingAbsolutePath } from "./guided-opening-media-v1";

export const BODY_SOURCE_COLOR_REPLAY_SCOPE = "original-opening-source-color-replay-not-execution-or-approval" as const;
const MAX_REFERENCE_BYTES = 8 * 1024 * 1024;
const OPENING_HASHES = ["selectionHash", "claimHash", "cleanupHash", "inputSha256", "executionInputHash", "mediaResultSha256", "receiptHash"] as const;
export interface BodySourceColorReplayFile { path: string; sha256: string; sizeBytes: number }
export interface BodySourceColorReplayReferencesV2 {
  schemaVersion: 2; kind: "guided-body-source-color-replay-references"; scope: typeof BODY_SOURCE_COLOR_REPLAY_SCOPE;
  opening: Record<typeof OPENING_HASHES[number], string> & { executionId: string };
  sourceColorHash: string; input: BodySourceColorReplayFile; reservationArchive: BodySourceColorReplayFile;
  executable: false; bodyApproved: false; deliveryApproved: false;
}

function exact(value: unknown, keys: readonly string[], label: string) {
  const row = objectValue(value, label); exactKeys(row, keys, keys, label); return row;
}

function identifier(value: unknown, label: string): string {
  const result = uuid(value, label);
  if (result[14] !== "4") throw new Error(`${label} must be UUIDv4`);
  return result;
}

function reference(value: unknown): BodySourceColorReplayFile {
  const row = exact(value, ["path", "sha256", "sizeBytes"], "body source-color raw reference");
  openingAbsolutePath(row.path); sha256(row.sha256, "body source-color raw SHA");
  if (!Number.isSafeInteger(row.sizeBytes) || Number(row.sizeBytes) < 1 || Number(row.sizeBytes) > MAX_REFERENCE_BYTES) {
    throw new Error("Body source-color raw reference exceeds its original metadata bound");
  }
  return row as unknown as BodySourceColorReplayFile;
}

/** Exact paths and cross-reference roots only, never raw-byte authentication or discovery. */
function paths(input: BodySourceColorReplayFile, archive: BodySourceColorReplayFile, executionId: string): void {
  const suffix = `/executions/${executionId}/source-color/input.json`;
  if (!input.path.endsWith(suffix)) throw new Error("Body source-color input differs from its opening execution");
  const execution = input.path.slice(0, -"/source-color/input.json".length), prefix = `${execution}/cleanup-attempts/`;
  if (!archive.path.startsWith(prefix)) throw new Error("Body source-color archive differs from its opening execution root");
  const parts = archive.path.slice(prefix.length).split("/");
  if (parts.length !== 2 || parts[1] !== "reservation.json") throw new Error("Body source-color archive has the wrong artifact role");
  identifier(parts[0], "body source-color cleanup attempt");
}

/** Detached schema2 data only. A different well-formed hash still requires the genuine server's original-proof join. */
export function parseBodySourceColorReplayReferences(value: unknown): BodySourceColorReplayReferencesV2 {
  const row = exact(value, ["schemaVersion", "kind", "scope", "opening", "sourceColorHash", "input", "reservationArchive",
    "executable", "bodyApproved", "deliveryApproved"], "body source-color replay references");
  if (row.schemaVersion !== 2 || row.kind !== "guided-body-source-color-replay-references" || row.scope !== BODY_SOURCE_COLOR_REPLAY_SCOPE
      || row.executable !== false || row.bodyApproved !== false || row.deliveryApproved !== false) {
    throw new Error("Body source-color replay reference version or non-authorizing scope differs");
  }
  const opening = exact(row.opening, [...OPENING_HASHES, "executionId"], "body source-color original opening");
  OPENING_HASHES.forEach(key => sha256(opening[key], key));
  const executionId = identifier(opening.executionId, "body source-color opening execution");
  sha256(row.sourceColorHash, "sourceColorHash"); paths(reference(row.input), reference(row.reservationArchive), executionId);
  return structuredClone(row) as unknown as BodySourceColorReplayReferencesV2;
}
