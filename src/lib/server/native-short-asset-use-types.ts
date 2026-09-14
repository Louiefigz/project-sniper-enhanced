/** Native use decisions reuse the shared rights record; they never grant publication. */
import type { AssetRecordV1, AssetUseV1 } from "@/lib/producer/contracts/asset-record";
import type { ShortMediaPolicy } from "@/lib/producer/short-direction";
import type { NativeBox, NativeWindow } from "./native-short-composition";
import type { NativeShortProjectInput } from "./native-short-project";
import type { NativeWebCaptureBinding } from "./native-web-capture";

export interface NativeAssetOriginBinding { path: string; sha256: string }
export type NativeAcquisitionKind = "provided" | "local-library" | "public-download" | "public-web-capture";
export interface NativeAssetOriginReceipt {
  schemaVersion: 1; kind: "native-short-asset-origin"; assetFile: string;
  record: AssetRecordV1;
  acquisition: {
    kind: NativeAcquisitionKind;
    sourceFrameRate?: string;
    accessScope: "public" | "operator-private" | "project-private";
    /** Pinned observations/receipts, never an assertion that semantic review passed. */
    evidence: NativeAssetOriginBinding[];
    webCapture?: NativeWebCaptureBinding;
  };
}
export type NativeAssetUsePolicy = ShortMediaPolicy;
export interface NativeAssetUseSpeech extends NativeWindow {
  occurrenceIds: number[]; text: string;
}
export interface NativeAssetUseSelection extends NativeWindow {
  assetFile: string; targetId: string;
  kind: "image" | "logo" | "video" | "web" | "creator-image" | "creator-excerpt";
  /** Source pixel coordinates; frame review must establish actual unobscured visibility. */
  essentialRegion: NativeBox;
  essentialContent: string;
  audio: "none" | "muted";
  sourceRange?: { startSeconds: number; endSeconds: number; frameRate: string };
  /** Exact source URL/account/post, or the supplied/local source named in provenance. */
  sourceIdentity: string;
  attribution: { text: string; placement: string } | null;
}
export interface NativeAssetUseDecision {
  id: string;
  decision: "insert" | "no-insert";
  speech: NativeAssetUseSpeech;
  entity: {
    name: string;
    role: "subject" | "quoted-source" | "comparison" | "style-reference" | "none";
    canonicalIdentity: string | null;
  };
  purpose: "identify" | "demonstrate" | "analyze-quote" | "illustrate" | "style-direction" | "no-insert";
  reason: string; rejectedAlternative: string; claimLimit: string;
  /** Source context/negation/hypothetical framing the editor must preserve. */
  context: string;
  inspection: { method: "local-source-review" | "not-reviewed"; observations: string[]; limitations: string[] };
  selection: NativeAssetUseSelection | null;
}
export interface NativeShortAssetUsePlan {
  schemaVersion: 1; revisionHash: string; policy: NativeAssetUsePolicy;
  intendedUse: { use: AssetUseV1; platform: "local-review" };
  decisions: NativeAssetUseDecision[];
}
/** Intersections let new standalone validators coexist with cold-readable legacy plans. */
export type NativeAssetUseInput = NativeShortProjectInput & {
  assets: Array<NativeShortProjectInput["assets"][number] & { origin?: NativeAssetOriginBinding }>;
  strategy: NativeShortProjectInput["strategy"] & { assetUse?: NativeShortAssetUsePlan };
};
export interface NativeAssetUseOptions {
  required: boolean;
  expectedPolicy: NativeAssetUsePolicy;
  /** Required when a prepared packet exists; root resolves its supplied inventory. */
  providedAssets?: Array<{ file: string; sha256: string }>;
}
