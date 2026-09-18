import { enumValue, exactKeys, objectValue, stringValue } from "./validation";
import { parseTreatmentProposal as parseHistoricalTreatmentProposal, parseTreatmentProposalV4,
  type ProposalOperationV4, type TreatmentProposalV4, type TreatmentProposal as HistoricalTreatmentProposal } from "./treatment-proposal-v4";

/** An explicit choice of the captured Producer configuration, never generated typography or word timing. */
export const GUIDED_CAPTION_PRESETS = ["producer-config-line-v1", "producer-config-karaoke-v1"] as const;
export type GuidedCaptionPreset = (typeof GUIDED_CAPTION_PRESETS)[number];
export interface ProposalCaptionSelectionV1 {
  schemaVersion: 1; preset: GuidedCaptionPreset;
  coverage: "all-kept-transcript-words"; suppression: "none";
}
export interface ProposalOperationV5 extends Omit<ProposalOperationV4, "type"> {
  type: ProposalOperationV4["type"] | "captions-full-program";
  captions: ProposalCaptionSelectionV1 | null;
}
export interface TreatmentProposalV5 extends Omit<TreatmentProposalV4, "schemaVersion" | "operations"> {
  schemaVersion: 5; operations: ProposalOperationV5[];
}
export type CurrentTreatmentProposal = HistoricalTreatmentProposal | TreatmentProposalV5;
// Current authoring uses V5 after actual shared-caption longform/portrait media
// tests. Historical parsers remain closed; this is not creative/source approval.
export const CURRENT_TREATMENT_PROPOSAL_VERSION: 4 | 5 = 5;

/** Closed current caption preset request. It supplies neither replacement speech nor suppression rules. */
export function parseProposalCaptionSelection(value: unknown): ProposalCaptionSelectionV1 {
  const row = objectValue(value, "proposal caption selection");
  const keys = ["schemaVersion", "preset", "coverage", "suppression"];
  exactKeys(row, keys, keys, "proposal caption selection");
  if (row.schemaVersion !== 1 || row.coverage !== "all-kept-transcript-words" || row.suppression !== "none") {
    throw new Error("Caption selection requires all kept transcript words without suppression");
  }
  return { schemaVersion: 1, preset: enumValue(row.preset, GUIDED_CAPTION_PRESETS, "caption preset"),
    coverage: "all-kept-transcript-words", suppression: "none" };
}

function captionOperation(value: unknown) {
  const row = objectValue(value, "V5 operation");
  if (typeof row.type !== "string" || row.grade !== null && typeof row.grade !== "string") {
    throw new Error("V5 operation type and grade must use actual string enums or the permitted null grade");
  }
  if (!Object.hasOwn(row, "captions")) throw new Error("V5 operations require an explicit captions selection or null");
  const { captions, ...base } = row;
  if (row.type !== "captions-full-program") {
    if (captions !== null) throw new Error("Only captions-full-program carries a caption selection");
    return { base, captions: null, reason: row.reason };
  }
  const reason = stringValue(row.reason, "caption operation reason", 2000);
  if (Array.from(reason.trim()).length < 8) throw new Error("Caption operation needs a substantive reason");
  // V4 checks every remaining field, reference and nullability. This projection
  // is validation-only; the caller retains the actual V5 caption operation.
  return { base: { ...base, type: "preserve-cut", reason: null },
    captions: parseProposalCaptionSelection(captions), reason };
}

/** Keep V2/V3/V4 parsers closed: only this explicit entry point accepts the new caption operation. */
export function parseTreatmentProposalV5(value: unknown): TreatmentProposalV5 {
  const row = objectValue(value, "TreatmentProposalV5");
  if (row.schemaVersion !== 5 || !Array.isArray(row.operations) || row.operations.length > 128) throw new Error("Invalid V5 proposal");
  assertActualEnums(row);
  const parsed = row.operations.map(captionOperation);
  const legacy = parseTreatmentProposalV4({ ...row, schemaVersion: 4, operations: parsed.map((item) => item.base) });
  const operations: ProposalOperationV5[] = legacy.operations.map((operation, index) => {
    const item = parsed[index];
    return item.captions ? { ...operation, type: "captions-full-program", captions: item.captions, reason: String(item.reason) }
      : { ...operation, captions: null };
  });
  return { ...legacy, schemaVersion: 5, operations };
}

function assertActualEnums(row: Record<string, unknown>): void {
  if (typeof row.colorPolicy !== "string") throw new Error("V5 colorPolicy must be an actual string enum");
  for (const [name, field] of [["clauses", "disposition"], ["beats", "purpose"]]) {
    if (!Array.isArray(row[name])) throw new Error(`V5 ${name} must be an array`);
    if (row[name].some((item) => typeof objectValue(item, `V5 ${name}`)[field] !== "string")) {
      throw new Error(`V5 ${field} must be an actual string enum`);
    }
  }
}

/** Current explicit dispatcher; historical parser entry points retain their original closed versions. */
export function parseCurrentTreatmentProposal(value: unknown): CurrentTreatmentProposal {
  return objectValue(value, "current treatment proposal").schemaVersion === 5
    ? parseTreatmentProposalV5(value) : parseHistoricalTreatmentProposal(value);
}

/** Reuse unchanged V4 story/graphic rules only. Never persist this as the original request or fulfilled result. */
export function proposalV5GraphicValidationView(proposal: TreatmentProposalV5): TreatmentProposalV4 {
  const current = parseTreatmentProposalV5(proposal);
  return parseTreatmentProposalV4({ ...current, schemaVersion: 4, operations: current.operations.map((item) => {
    const { captions, ...operation } = item;
    return captions ? { ...operation, type: "preserve-cut", reason: null } : operation;
  }) });
}
