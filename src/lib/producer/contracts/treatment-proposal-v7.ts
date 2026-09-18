/** Explicit admitted-music authoring; not a default-version change or render qualification. */
import { exactKeys, objectValue, stringValue } from "./validation";
import { MIN_OPERATION_REASON_CHARS } from "./treatment-proposal-v4";
import { parseTreatmentProposalV6, parseCurrentTreatmentProposal as parseThroughV6,
  type CurrentTreatmentProposal as ThroughV6, type ProposalOperationV6, type TreatmentProposalV6 } from "./treatment-proposal-v6";

/** Mirrors the existing voice-first plan linter, not a new loudness or taste guarantee. */
export const GUIDED_MUSIC_GAP_DB = { minimum: 3, maximum: 40 } as const;
export interface ProposalMusicSelectionV1 {
  schemaVersion: 1; assetId: string; gapDb: number; duck: true;
}
export interface ProposalOperationV7 extends Omit<ProposalOperationV6, "type"> {
  type: ProposalOperationV6["type"] | "music-bed-full-program";
  music: ProposalMusicSelectionV1 | null;
}
export interface TreatmentProposalV7 extends Omit<TreatmentProposalV6, "schemaVersion" | "operations"> {
  schemaVersion: 7; operations: ProposalOperationV7[];
}
export type CurrentTreatmentProposal = ThroughV6 | TreatmentProposalV7;

/** Selection references only admitted catalog identity; arbitrary files, search and downloads stay closed. */
export function parseProposalMusicSelection(value: unknown): ProposalMusicSelectionV1 {
  const row = objectValue(value, "proposal music selection");
  const keys = ["schemaVersion", "assetId", "gapDb", "duck"];
  exactKeys(row, keys, keys, "proposal music selection");
  if (row.schemaVersion !== 1 || row.duck !== true || typeof row.gapDb !== "number" || !Number.isFinite(row.gapDb)
      || row.gapDb < GUIDED_MUSIC_GAP_DB.minimum || row.gapDb > GUIDED_MUSIC_GAP_DB.maximum) {
    throw new Error("Music requires exact schema1, duck:true and a finite voice-first gapDb in [3, 40]");
  }
  return { schemaVersion: 1, assetId: stringValue(row.assetId, "music assetId", 128), gapDb: row.gapDb, duck: true };
}

function musicOperation(value: unknown) {
  const row = objectValue(value, "V7 operation");
  if (!Object.hasOwn(row, "music")) throw new Error("Every V7 operation requires an explicit music selection or null");
  const { music, ...base } = row;
  if (row.type !== "music-bed-full-program") {
    if (music !== null) throw new Error("Only music-bed-full-program carries a music selection");
    return { base, music: null, reason: row.reason };
  }
  const reason = stringValue(row.reason, "music operation reason", 2000);
  if (Array.from(reason.trim()).length < MIN_OPERATION_REASON_CHARS) throw new Error("Music operation needs a substantive reason");
  // Validation-only view. Actual operation indices and payloads remain in the V7 proposal.
  return { base: { ...base, type: "preserve-cut", reason: null }, music: parseProposalMusicSelection(music), reason };
}

/** One explicit full-program bed; repeated or conflicting requests require clarification, not replacement. */
export function parseTreatmentProposalV7(value: unknown): TreatmentProposalV7 {
  const row = objectValue(value, "TreatmentProposalV7");
  if (row.schemaVersion !== 7 || !Array.isArray(row.operations) || row.operations.length > 128) throw new Error("Invalid V7 proposal");
  const parsed = row.operations.map(musicOperation);
  if (parsed.filter((item) => item.music !== null).length > 1) throw new Error("V7 supports only one explicit full-program music bed");
  const prior = parseTreatmentProposalV6({ ...row, schemaVersion: 6, operations: parsed.map((item) => item.base) });
  const operations: ProposalOperationV7[] = prior.operations.map((operation, index) => {
    const item = parsed[index];
    return item.music ? { ...operation, type: "music-bed-full-program", music: item.music, reason: String(item.reason) }
      : { ...operation, music: null };
  });
  return { ...prior, schemaVersion: 7, operations };
}

/** Exact dispatch only. Historical entry points stay closed and current default remains separately qualified. */
export function parseCurrentTreatmentProposal(value: unknown): CurrentTreatmentProposal {
  return objectValue(value, "current treatment proposal").schemaVersion === 7
    ? parseTreatmentProposalV7(value) : parseThroughV6(value);
}

/** Validation/projection view only; never persist it as the request, a fulfilled clause or execution evidence. */
export function proposalV7ValidationView(proposal: TreatmentProposalV7): TreatmentProposalV6 {
  const current = parseTreatmentProposalV7(proposal);
  return parseTreatmentProposalV6({ ...current, schemaVersion: 6, operations: current.operations.map((item) => {
    const { music, ...operation } = item;
    return music ? { ...operation, type: "preserve-cut", reason: null } : operation;
  }) });
}
