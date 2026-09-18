import { exactKeys, objectValue, stringValue } from "./validation";
import { parseTreatmentProposalV2, type ProposalOperationV2, type TreatmentProposalV2 } from "./treatment-proposal-v2";

/** Declared creative intent only. Actual alpha, placement, legibility and pixels remain unqualified. */
export interface GraphicPresentationV1 {
  schemaVersion: 1;
  anchor: "own-screen" | "free-band";
  placement: "full-canvas" | "measured-free-region";
  compositeMode: "normal";
  baseTreatment: "preserve";
  rationale: string;
}
export interface ProposalOperationV3 extends ProposalOperationV2 {
  presentation: GraphicPresentationV1 | null;
}
export interface TreatmentProposalV3 extends Omit<TreatmentProposalV2, "schemaVersion" | "operations"> {
  schemaVersion: 3;
  operations: ProposalOperationV3[];
}
export type TreatmentProposal = TreatmentProposalV2 | TreatmentProposalV3;

export const PROPOSAL_PRESENTATION_POLICY = Object.freeze({
  schemaVersion: 1,
  scope: "explicit-presentation-intent-not-alpha-placement-or-pixel-proof",
  choices: [
    { anchor: "own-screen", placement: "full-canvas", compositeMode: "normal", baseTreatment: "preserve" },
    { anchor: "free-band", placement: "measured-free-region", compositeMode: "normal", baseTreatment: "preserve" },
  ],
});

/** No missing-anchor/default-free-band interpretation is permitted for a V3 graphic. */
export function parseGraphicPresentation(value: unknown): GraphicPresentationV1 {
  const row = objectValue(value, "graphic presentation");
  const keys = ["schemaVersion", "anchor", "placement", "compositeMode", "baseTreatment", "rationale"];
  exactKeys(row, keys, keys, "graphic presentation");
  const pair = row.anchor === "own-screen" ? "full-canvas" : row.anchor === "free-band" ? "measured-free-region" : null;
  if (row.schemaVersion !== 1 || !pair || row.placement !== pair || row.compositeMode !== "normal" || row.baseTreatment !== "preserve") {
    throw new Error("Unsupported graphic presentation; no inferred anchor, crop, blur or placement");
  }
  stringValue(row.rationale, "presentation rationale", 2000);
  return row as unknown as GraphicPresentationV1;
}

/** Reuse unchanged V2 clause/beat/value validation without adding fields to stored V2 objects. */
export function parseTreatmentProposalV3(value: unknown): TreatmentProposalV3 {
  const row = objectValue(value, "TreatmentProposalV3");
  if (row.schemaVersion !== 3 || !Array.isArray(row.operations) || row.operations.length > 128) throw new Error("Invalid V3 proposal");
  const presentations = row.operations.map((value) => {
    const operation = objectValue(value, "V3 operation");
    if (!Object.hasOwn(operation, "presentation")) throw new Error("V3 operation requires explicit presentation or null");
    return operation.presentation === null ? null : parseGraphicPresentation(operation.presentation);
  });
  const legacy = parseTreatmentProposalV2({ ...row, schemaVersion: 2,
    operations: row.operations.map((value) => { const { presentation, ...rest } = value; void presentation; return rest; }) });
  const operations = legacy.operations.map((operation, index) => {
    if ((operation.type === "catalog-graphic") !== (presentations[index] !== null)) throw new Error("Only catalog graphics require non-null presentation");
    return { ...operation, presentation: presentations[index] };
  });
  return { ...legacy, schemaVersion: 3, operations };
}

export function parseTreatmentProposal(value: unknown): TreatmentProposal {
  return objectValue(value, "treatment proposal").schemaVersion === 3 ? parseTreatmentProposalV3(value) : parseTreatmentProposalV2(value);
}
