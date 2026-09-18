/** Explicit timed presenter layout authoring; no default dispatch, execution or framing approval. */
import { objectValue, stringValue } from "./validation";
import { proposalInteger } from "./treatment-proposal-v2";
import { MIN_OPERATION_REASON_CHARS } from "./treatment-proposal-v4";
import { parseTreatmentProposalV7, parseCurrentTreatmentProposal as parseThroughV7,
  type CurrentTreatmentProposal as ThroughV7, type ProposalOperationV7, type TreatmentProposalV7 } from "./treatment-proposal-v7";
import { parsePresenterLayoutV1, type PresenterLayoutV1 } from "./presenter-layout-v1";

export interface ProposalOperationV8 extends Omit<ProposalOperationV7, "type"> {
  type: ProposalOperationV7["type"] | "presenter-layout-window";
  presenterLayout: PresenterLayoutV1 | null;
}
export interface TreatmentProposalV8 extends Omit<TreatmentProposalV7, "schemaVersion" | "operations"> {
  schemaVersion: 8; operations: ProposalOperationV8[];
}
export type CurrentTreatmentProposal = ThroughV7 | TreatmentProposalV8;

function layoutOperation(value: unknown) {
  const row = objectValue(value, "V8 operation");
  if (!Object.hasOwn(row, "presenterLayout")) throw new Error("Every V8 operation requires presenterLayout selection or null");
  const { presenterLayout, ...base } = row;
  if (row.type !== "presenter-layout-window") {
    if (presenterLayout !== null) throw new Error("Only presenter-layout-window carries presenter geometry");
    return { base, timed: null };
  }
  const reason = stringValue(row.reason, "presenter layout reason", 2000);
  if (Array.from(reason.trim()).length < MIN_OPERATION_REASON_CHARS) throw new Error("Presenter layout needs a substantive reason");
  const beatIndex = proposalInteger(row.beatIndex, "presenter beatIndex", 127);
  const startAnchor = proposalInteger(row.startAnchor, "presenter startAnchor", 60001);
  const endAnchorExclusive = proposalInteger(row.endAnchorExclusive, "presenter endAnchorExclusive", 60001);
  if (startAnchor >= endAnchorExclusive) throw new Error("Presenter layout needs a positive anchor window");
  const timed = { reason, beatIndex, startAnchor, endAnchorExclusive, presenterLayout: parsePresenterLayoutV1(presenterLayout) };
  // Only this validation view removes timing; the actual V8 array retains every field and index.
  return { base: { ...base, type: "preserve-cut", reason: null, beatIndex: null, startAnchor: null, endAnchorExclusive: null }, timed };
}

function assertLayoutBeats(proposal: TreatmentProposalV8): void {
  for (const operation of proposal.operations) {
    if (operation.type !== "presenter-layout-window") continue;
    const beat = proposal.beats[operation.beatIndex!];
    if (!beat || operation.startAnchor! < beat.startAnchor || operation.endAnchorExclusive! > beat.endAnchorExclusive) {
      throw new Error("Presenter layout must remain within its actual referenced story beat");
    }
  }
}

/** Preserve real timed operations. Source/asset/clock, overlap and target geometry are owner rederivations. */
export function parseTreatmentProposalV8(value: unknown): TreatmentProposalV8 {
  const row = objectValue(value, "TreatmentProposalV8");
  if (row.schemaVersion !== 8 || !Array.isArray(row.operations) || row.operations.length > 128) throw new Error("Invalid V8 proposal");
  const parsed = row.operations.map(layoutOperation);
  const prior = parseTreatmentProposalV7({ ...row, schemaVersion: 7, operations: parsed.map((item) => item.base) });
  const operations: ProposalOperationV8[] = prior.operations.map((operation, index) => {
    const timed = parsed[index].timed;
    return timed ? { ...operation, ...timed, type: "presenter-layout-window" } : { ...operation, presenterLayout: null };
  });
  const proposal: TreatmentProposalV8 = { ...prior, schemaVersion: 8, operations };
  assertLayoutBeats(proposal);
  return proposal;
}

/** Version-aware authoring/history parser; the default compiler and executable media profiles are unchanged. */
export function parseCurrentTreatmentProposal(value: unknown): CurrentTreatmentProposal {
  return objectValue(value, "current treatment proposal").schemaVersion === 8 ? parseTreatmentProposalV8(value) : parseThroughV7(value);
}

/** Historical validation/projection only; never persist this as request, clause fulfillment or execution evidence. */
export function proposalV8ValidationView(value: TreatmentProposalV8): TreatmentProposalV7 {
  const current = parseTreatmentProposalV8(value);
  return parseTreatmentProposalV7({ ...current, schemaVersion: 7, operations: current.operations.map((item) => layoutOperation(item).base) });
}
