/** Read-only private opening observations. This is not a public launch or an approval contract. */
export const GUIDED_OPENING_STATUS_SCOPE = "private-opening-not-opening-body-or-delivery-approval" as const;

export interface GuidedOpeningTimingV1 {
  generationStartedAt: string | null;
  /** Populated only from a strongly bound owned stopped-process receipt. Never active liveness. */
  engineElapsedMs: number | null;
  cleanupElapsedMs: number | null;
  elapsedStatus: "completed" | "unavailable";
  /** This excludes earlier proposal/preview work, despite preserving the original request origin. */
  coverage: "recorded-owned-attempt-only" | "unavailable";
}

interface GuidedOpeningStatusBaseV1 {
  ok: true;
  schemaVersion: 1;
  scope: typeof GUIDED_OPENING_STATUS_SCOPE;
  requestId: string | null;
  executionId: string | null;
  claimHash: string | null;
  /** True only in ready-for-review with a verified `approval` object bound to the current exact selection. */
  openingApproved: boolean;
  deliveryApproved: false;
  subjectiveListening: "not-performed-by-system";
  detail: string;
  timing: GuidedOpeningTimingV1;
}

/** The server derives each local URL; no artifact path, tool path or worker identity is returned. */
export interface GuidedOpeningMediaDescriptorV1 {
  url: string;
  mediaSha256: string;
  sizeBytes: number;
  width: number;
  height: number;
  frameRate: string;
  videoFrames: number;
  startFrame: number;
  endFrameExclusive: number;
  audioSamples: number;
}

export type GuidedOpeningStatusV1 = GuidedOpeningStatusBaseV1 & (
  | { state: "unavailable" | "pending-owned-execution" | "pending-cleanup" | "failed" }
  | {
    /** Mechanical playback only. Human opening review and independent visual/listening gates remain separate. */
    state: "ready-for-review";
    selectionHash: string;
    receiptHash: string;
    receiptSha256: string;
    /** Last actual full source/pipeline/context/media qualification, not a fresh status-poll observation. */
    selectionQualifiedAt: string;
    sourceFreshness: "not-rechecked-by-status";
    media: { core: GuidedOpeningMediaDescriptorV1; review: GuidedOpeningMediaDescriptorV1 };
    /** Exact journal identity a human approval submission must name; never authority by itself. */
    journal: { token: string; sha256: string };
    /** Verified local-operator approval of THIS selection, or null. Body generation and delivery stay separate. */
    approval: { approvalHash: string; approvedAt: string } | null;
  }
);

/** Routes must enforce local-origin policy and closed, bounded query parsing before this server-derived resolver. */
export interface GuidedOpeningMediaSelectorV1 {
  dir: string;
  selectionHash: string;
  mediaSha256: string;
  range: "core" | "review";
}
