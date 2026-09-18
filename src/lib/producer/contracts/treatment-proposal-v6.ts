/** Explicit V6 authoring; historical V5 stays closed and the default stays separately qualified. */
import { exactKeys, objectValue, stringValue } from "./validation";
import { MIN_OPERATION_REASON_CHARS } from "./treatment-proposal-v4";
import { parseTreatmentProposalV5, parseCurrentTreatmentProposal as parseThroughV5,
  type CurrentTreatmentProposal as ThroughV5Proposal, type ProposalOperationV5, type TreatmentProposalV5 } from "./treatment-proposal-v5";

export interface ProposalManualReframeV1 {
  schemaVersion: 1; sourceId: string; layout: "fill";
  crop: [number, number, number, number]; track: false;
}
export interface ProposalOperationV6 extends Omit<ProposalOperationV5, "type"> {
  type: ProposalOperationV5["type"] | "reframe-manual-short";
  reframe: ProposalManualReframeV1 | null;
}
export interface TreatmentProposalV6 extends Omit<TreatmentProposalV5, "schemaVersion" | "operations"> {
  schemaVersion: 6; operations: ProposalOperationV6[];
}
export type CurrentTreatmentProposal = ThroughV5Proposal | TreatmentProposalV6;

/** Exact-version dispatch. This does not activate V6 by default or open historical parsers. */
export function parseCurrentTreatmentProposal(value: unknown): CurrentTreatmentProposal {
  return objectValue(value, "current treatment proposal").schemaVersion === 6
    ? parseTreatmentProposalV6(value) : parseThroughV5(value);
}

/** Existing REFRAME_SPLIT.crop_min_frac; parity-tested, never a changed renderer bound. */
export const MANUAL_REFRAME_MIN_FRACTION = 0.05;

export function parseProposalManualReframe(value: unknown): ProposalManualReframeV1 {
  const row = objectValue(value, "manual reframe selection");
  const keys = ["schemaVersion", "sourceId", "layout", "crop", "track"];
  exactKeys(row, keys, keys, "manual reframe selection");
  if (row.schemaVersion !== 1 || row.layout !== "fill" || row.track !== false) {
    throw new Error("Manual reframe requires explicit schema1 fill/crop/track:false");
  }
  const crop = row.crop;
  if (!Array.isArray(crop) || crop.length !== 4 || crop.some((item) => typeof item !== "number" || !Number.isFinite(item))) {
    throw new Error("Manual reframe crop needs four finite nonboolean numbers");
  }
  const [x, y, width, height] = crop;
  if (!(x >= 0 && y >= 0 && width >= MANUAL_REFRAME_MIN_FRACTION && height >= MANUAL_REFRAME_MIN_FRACTION
      && x + width <= 1 && y + height <= 1)) throw new Error("Manual reframe crop is outside normalized source bounds");
  return { schemaVersion: 1, sourceId: stringValue(row.sourceId, "reframe sourceId", 128), layout: "fill",
    crop: [x, y, width, height], track: false };
}

function reframeOperation(value: unknown) {
  const row = objectValue(value, "V6 operation");
  if (!Object.hasOwn(row, "reframe")) throw new Error("Every V6 operation requires reframe selection or null");
  const { reframe, ...base } = row;
  if (row.type !== "reframe-manual-short") {
    if (reframe !== null) throw new Error("Only reframe-manual-short carries reframe selection");
    return { base, reframe: null, reason: row.reason };
  }
  const reason = stringValue(row.reason, "manual reframe reason", 2000);
  if (Array.from(reason.trim()).length < MIN_OPERATION_REASON_CHARS) throw new Error("Manual reframe needs a substantive reason");
  // Validation-only surrogate; V5 checks every other field, null and enum.
  return { base: { ...base, type: "preserve-cut", reason: null }, reframe: parseProposalManualReframe(reframe), reason };
}

function assertCaptionedCrop(operations: ProposalOperationV6[]): void {
  const crops = operations.filter((item) => item.type === "reframe-manual-short");
  if (!crops.length) return;
  if (crops.length !== 1) throw new Error("V6 supports exactly one full-program manual crop; duplicates/conflicts are blocked");
  const captions = operations.filter((item) => item.type === "captions-full-program");
  if (!captions.length) throw new Error("Manual crop requires a separate explicit all-kept caption preset operation");
  if (new Set(captions.map((item) => item.captions!.preset)).size !== 1) throw new Error("Manual crop caption presets conflict");
}

/** Parse actual V6 operations without persisting a crop as a historical preserve-cut. */
export function parseTreatmentProposalV6(value: unknown): TreatmentProposalV6 {
  const row = objectValue(value, "TreatmentProposalV6");
  if (row.schemaVersion !== 6 || !Array.isArray(row.operations) || row.operations.length > 128) throw new Error("Invalid V6 proposal");
  const parsed = row.operations.map(reframeOperation);
  const prior = parseTreatmentProposalV5({ ...row, schemaVersion: 5, operations: parsed.map((item) => item.base) });
  const operations: ProposalOperationV6[] = prior.operations.map((operation, index) => {
    const item = parsed[index];
    return item.reframe ? { ...operation, type: "reframe-manual-short", reframe: item.reframe, reason: String(item.reason) }
      : { ...operation, reframe: null };
  });
  assertCaptionedCrop(operations);
  return { ...prior, schemaVersion: 6, operations };
}

/** Validation/projection input only. Never store this view as proposal or fulfilled operation evidence. */
export function proposalV6ValidationView(proposal: TreatmentProposalV6): TreatmentProposalV5 {
  const current = parseTreatmentProposalV6(proposal);
  return parseTreatmentProposalV5({ ...current, schemaVersion: 5, operations: current.operations.map((item) => {
    const { reframe, ...operation } = item;
    return reframe ? { ...operation, type: "preserve-cut", reason: null } : operation;
  }) });
}
