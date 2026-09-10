import { enumValue, exactKeys, objectValue, stringValue } from "./validation";
import { parseTreatmentProposalV2, proposalInteger, type TreatmentProposalV2 } from "./treatment-proposal-v2";
import { parseTreatmentProposalV3, type ProposalOperationV3, type TreatmentProposalV3 } from "./treatment-proposal-v3";

/** Renderer gate constants, mirrored from the pinned Python contracts they must satisfy. */
export const MIN_OPERATION_REASON_CHARS = 8; // plan_lint_motion: every graphicsTrack entry needs a purposeful reason.
export const MIN_BEAT_REASON_CHARS = 20; // graphics/intro_semantic_binding.MIN_REASON_CHARS
export const MIN_SELECTION_REASON_CHARS = 20; // graphics/intro_semantic_binding.MIN_SELECTION_REASON_CHARS
export const MIN_SEAM_EVIDENCE_CHARS = 12; // intro_transition_contract.MIN_EVIDENCE_CHARS
export const MIN_SEAM_REASON_CHARS = 20; // intro_transition_contract.MIN_REASON_CHARS
export const PROPOSAL_GRAPHICS_STYLES = ["cutaway-only", "overlay-rich", "face-bridge"] as const;
export type ProposalGraphicsStyle = (typeof PROPOSAL_GRAPHICS_STYLES)[number];

export interface ProposalOperationV4 extends ProposalOperationV3 {
  reason: string | null;
}
/** One deterministic transcript beat discharged by exactly one authored catalog graphic. */
export interface ProposalBeatDecisionV4 {
  beatId: string; decision: "graphic"; reason: string; kind: string;
  alternativesConsidered: string[]; selectionReason: string; operationIndex: number;
}
/** One intro cut seam retained as a hard cut, bound to evidence.introSeams[seamIndex]. */
export interface ProposalHookSeamDecisionV4 {
  seamIndex: number; decision: "clean-hook"; reason: string; evidence: string;
}
export interface TreatmentProposalV4 extends Omit<TreatmentProposalV3, "schemaVersion" | "operations"> {
  schemaVersion: 4; operations: ProposalOperationV4[];
  graphicsStyle: ProposalGraphicsStyle; graphicsStyleRationale: string;
  beatDecisions: ProposalBeatDecisionV4[]; hookSeamDecisions: ProposalHookSeamDecisionV4[];
}
export type TreatmentProposal = TreatmentProposalV2 | TreatmentProposalV3 | TreatmentProposalV4;

const V4_KEYS = ["schemaVersion", "summary", "clauses", "beats", "operations", "openingEndAnchor", "continuityEndAnchor",
  "audioPolicy", "colorPolicy", "graphicsStyle", "graphicsStyleRationale", "beatDecisions", "hookSeamDecisions"];

/** Code-point minimum, matching the Python gates' len(str(...).strip()) floors. */
function boundedText(value: unknown, label: string, minimum: number, maximum = 2000): string {
  const text = stringValue(value, label, maximum);
  if (Array.from(text.trim()).length < minimum) throw new Error(`${label} must carry at least ${minimum} substantive characters`);
  return text;
}
function boundedList<T>(value: unknown, label: string, parser: (item: unknown) => T): T[] {
  if (!Array.isArray(value) || value.length > 128) throw new Error(`${label} must be a bounded array`);
  return value.map(parser);
}
function uniqueBy<T>(rows: T[], key: (row: T) => string | number, label: string): T[] {
  if (new Set(rows.map(key)).size !== rows.length) throw new Error(`${label} must be unique; one obligation cannot be discharged twice`);
  return rows;
}

/** No omit/broll fallback: the b-roll lane is off for guided work, so the gate would reject either one. */
function beatDecision(value: unknown): ProposalBeatDecisionV4 {
  const row = objectValue(value, "beat decision");
  const keys = ["beatId", "decision", "reason", "kind", "alternativesConsidered", "selectionReason", "operationIndex"];
  exactKeys(row, keys, keys, "beat decision");
  if (row.decision !== "graphic") throw new Error('Guided V4 supports only decision "graphic" for a required semantic beat; "omit" and "broll" are unsupported');
  const kind = stringValue(row.kind, "beat decision kind", 100);
  const alternatives = boundedList(row.alternativesConsidered, "alternativesConsidered", (item) => stringValue(item, "alternative kind", 100));
  uniqueBy(alternatives, (item) => item, "alternativesConsidered");
  if (alternatives.includes(kind)) throw new Error("alternativesConsidered must name other compatible anatomies, never the selected kind");
  return { beatId: stringValue(row.beatId, "beat decision beatId", 128), decision: "graphic",
    reason: boundedText(row.reason, "beat decision reason", MIN_BEAT_REASON_CHARS), kind, alternativesConsidered: alternatives,
    selectionReason: boundedText(row.selectionReason, "beat decision selectionReason", MIN_SELECTION_REASON_CHARS),
    operationIndex: proposalInteger(row.operationIndex, "beat decision operationIndex", 127) };
}

function hookSeamDecision(value: unknown): ProposalHookSeamDecisionV4 {
  const row = objectValue(value, "hook seam decision"), keys = ["seamIndex", "decision", "reason", "evidence"];
  exactKeys(row, keys, keys, "hook seam decision");
  if (row.decision !== "clean-hook") throw new Error('Guided V4 authors no transitions, so every intro seam decision must be "clean-hook"');
  return { seamIndex: proposalInteger(row.seamIndex, "hook seam decision seamIndex", 127), decision: "clean-hook",
    reason: boundedText(row.reason, "hook seam decision reason", MIN_SEAM_REASON_CHARS),
    evidence: boundedText(row.evidence, "hook seam decision evidence", MIN_SEAM_EVIDENCE_CHARS) };
}

function operationReasons(operations: unknown[]): Array<string | null> {
  return operations.map((value) => {
    const operation = objectValue(value, "V4 operation");
    if (!Object.hasOwn(operation, "reason")) throw new Error("V4 operation requires an explicit purposeful reason or null");
    return operation.reason === null ? null : boundedText(operation.reason, "operation reason", MIN_OPERATION_REASON_CHARS);
  });
}

/** Reuse unchanged V3/V2 clause/beat/presentation validation without adding fields to stored V2/V3 objects. */
export function parseTreatmentProposalV4(value: unknown): TreatmentProposalV4 {
  const row = objectValue(value, "TreatmentProposalV4");
  exactKeys(row, V4_KEYS, V4_KEYS, "TreatmentProposalV4");
  if (row.schemaVersion !== 4 || !Array.isArray(row.operations) || row.operations.length > 128) throw new Error("Invalid V4 proposal");
  const reasons = operationReasons(row.operations);
  const legacy = parseTreatmentProposalV3({ schemaVersion: 3, summary: row.summary, clauses: row.clauses, beats: row.beats,
    openingEndAnchor: row.openingEndAnchor, continuityEndAnchor: row.continuityEndAnchor, audioPolicy: row.audioPolicy, colorPolicy: row.colorPolicy,
    operations: row.operations.map((item) => { const { reason: _reason, ...rest } = objectValue(item, "V4 operation"); void _reason; return rest; }) });
  const operations = legacy.operations.map((operation, index) => {
    if ((operation.type === "catalog-graphic") !== (reasons[index] !== null)) throw new Error("Only catalog graphics carry a non-null operation reason");
    return { ...operation, reason: reasons[index] };
  });
  const beatDecisions = uniqueBy(uniqueBy(boundedList(row.beatDecisions, "beatDecisions", beatDecision),
    (item) => item.beatId, "beat decision beatId"), (item) => item.operationIndex, "beat decision operationIndex");
  const hookSeamDecisions = uniqueBy(boundedList(row.hookSeamDecisions, "hookSeamDecisions", hookSeamDecision),
    (item) => item.seamIndex, "hook seam decision seamIndex");
  return { ...legacy, schemaVersion: 4, operations, beatDecisions, hookSeamDecisions,
    graphicsStyle: enumValue(row.graphicsStyle, PROPOSAL_GRAPHICS_STYLES, "graphicsStyle"),
    graphicsStyleRationale: boundedText(row.graphicsStyleRationale, "graphicsStyleRationale", MIN_BEAT_REASON_CHARS) };
}

export function parseTreatmentProposal(value: unknown): TreatmentProposal {
  const version = objectValue(value, "treatment proposal").schemaVersion;
  if (version === 4) return parseTreatmentProposalV4(value);
  return version === 3 ? parseTreatmentProposalV3(value) : parseTreatmentProposalV2(value);
}
