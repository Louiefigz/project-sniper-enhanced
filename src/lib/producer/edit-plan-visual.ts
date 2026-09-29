/** Visual direction and execution receipts attached to an ordinary edit plan. */
export interface OrdinaryStyleChoice {
  graphicId: string;
  viewerNeed: string;
  familyId: string;
  contenderRef: string;
  anatomy: string;
  configuration: string;
  development: string;
  consideredContenders: string[];
  selectionReason: string;
  repeatMode: "new" | "varied" | "signature" | "callback" | "necessary-repeat";
  repeatReason: string;
}

export interface OrdinarySupplementalStyleChoice {
  graphicId: string;
  viewerNeed: string;
  /** Measured ordinary catalog adapter identity; must equal graphicsTrack[].kind. */
  catalogId: string;
  anatomy: string;
  configuration: string;
  development: string;
  selectionReason: string;
  relationshipMode: "coherent" | "justified-exception";
  relationshipEvidence: string;
  repeatMode: "new" | "varied" | "signature" | "callback" | "necessary-repeat";
  repeatReason: string;
}

export interface OrdinaryStyleApplication {
  schemaVersion: 1;
  vocabulary: { path: string; sha256: string; referenceId: string };
  choices: OrdinaryStyleChoice[];
  supplementalChoices?: OrdinarySupplementalStyleChoice[];
  limitations: string[];
}

export type OrdinaryVisualPlanLane =
  "graphicsTrack" | "transitions" | "punchIns" | "cutTrack" | "brollTrack";

export interface OrdinaryVisualPlanElementRef {
  lane: OrdinaryVisualPlanLane;
  index: number;
}

interface FrameRange { startFrame: number; endFrameExclusive: number }
export type OrdinaryVisualPlanExecutionBinding =
  | { kind: "catalog"; element: OrdinaryVisualPlanElementRef; mountId: string;
    catalogId: string; sourceSha256: string; adapterKind: string; implementationSha256: string }
  | { kind: "media"; element: OrdinaryVisualPlanElementRef; assetId: string;
    sourceSha256: string; sourceRange: FrameRange; outputRange: FrameRange;
    implementationSha256: string }
  | { kind: "text"; element: OrdinaryVisualPlanElementRef; visibleId: string;
    visibleText: string[]; contentSha256: string }
  | { kind: "transition"; element: OrdinaryVisualPlanElementRef; transitionId: string;
    mechanism: string; atFrame: number; configurationSha256: string }
  | { kind: "custom-native"; elements: Array<{ element: OrdinaryVisualPlanElementRef;
    visibleId: string; implementationPath: string; implementationSha256: string;
    rowSha256: string }> }
  | { kind: "presenter"; element: OrdinaryVisualPlanElementRef; sourceId: string;
    sourceRange: FrameRange; outputRange: FrameRange; implementationSha256: string }
  | { kind: "omit" };

export interface OrdinaryVisualPlanDecisionApplication {
  opportunityId: string;
  candidateId: string;
  modality: string;
  execution: "elements" | "presenter-hold" | "intentional-omit";
  timing: { startFrame: number; endFrameExclusive: number };
  elements: OrdinaryVisualPlanElementRef[];
  binding: OrdinaryVisualPlanExecutionBinding;
}

/** Deterministic receipt proving the shared allocation was compiled into this plan. */
export interface OrdinaryVisualPlanApplication {
  schemaVersion: 1;
  route: "ordinary";
  visualPlan: { byteHash: string; visualPlanSha256: string };
  decisions: OrdinaryVisualPlanDecisionApplication[];
}
